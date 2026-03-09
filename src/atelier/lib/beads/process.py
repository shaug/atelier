"""Process-backed async Beads client with JSON-first command coverage."""

from __future__ import annotations

import asyncio
import json
import os
from asyncio.subprocess import PIPE
from collections.abc import Mapping, Sequence
from pathlib import Path
from re import Pattern, compile
from typing import Protocol, cast

from pydantic import ValidationError

from .client import Beads, BeadsTransport
from .compatibility import DEFAULT_COMPATIBILITY_POLICY, CompatibilityPolicy
from .errors import (
    BeadsCommandError,
    BeadsParseError,
    BeadsTimeoutError,
    UnsupportedOperationError,
)
from .models import (
    BeadsCapability,
    BeadsCommandHelp,
    BeadsCommandRequest,
    BeadsCommandResult,
    BeadsEnvironment,
    BeadsStartupState,
    CloseIssueRequest,
    CreateIssueRequest,
    DependencyMutationRequest,
    IssueRecord,
    ListIssuesRequest,
    ReadyIssuesRequest,
    SemanticVersion,
    ShowIssueRequest,
    SupportedOperation,
    UpdateIssueRequest,
)

_SEMVER_SEARCH: Pattern[str] = compile(r"\bv?(\d+)\.(\d+)\.(\d+)\b")
_FLAG_SEARCH: Pattern[str] = compile(r"--[a-z0-9][a-z0-9-]*")
_JSON_FLAG = "--json"
_STARTUP_COUNT_SKEW_RECHECK_ATTEMPTS = 2
_STARTUP_HEALTHY = "healthy_dolt"
_STARTUP_MISSING_DOLT = "missing_dolt_with_legacy_sqlite"
_STARTUP_INSUFFICIENT_DOLT = "insufficient_dolt_vs_legacy_data"
_STARTUP_UNKNOWN = "startup_state_unknown"
_EMBEDDED_BACKEND_PANIC_MARKERS = (
    "panic: runtime error",
    "invalid memory address or nil pointer dereference",
    "setcrashonfatalerror",
)
_CAPABILITY_PROBES = (
    (BeadsCapability.ISSUE_JSON, (("show", "--help"), ("list", "--help"))),
    (
        BeadsCapability.ISSUE_MUTATION,
        (("create", "--help"), ("update", "--help"), ("close", "--help")),
    ),
    (
        BeadsCapability.DEPENDENCY_MUTATION,
        (("dep", "add", "--help"), ("dep", "remove", "--help")),
    ),
    (BeadsCapability.READY_DISCOVERY, (("ready", "--help"),)),
)


class _SpawnedProcess(Protocol):
    @property
    def returncode(self) -> int | None: ...

    async def communicate(self) -> tuple[bytes, bytes]: ...

    def kill(self) -> None: ...


class _ProcessSpawner(Protocol):
    async def __call__(
        self,
        *argv: str,
        cwd: str | None,
        env: Mapping[str, str],
    ) -> _SpawnedProcess: ...


async def _spawn_process(
    *argv: str,
    cwd: str | None,
    env: Mapping[str, str],
) -> _SpawnedProcess:
    return cast(
        _SpawnedProcess,
        await asyncio.create_subprocess_exec(
            *argv,
            cwd=cwd,
            env=dict(env),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=PIPE,
            stderr=PIPE,
        ),
    )


class SubprocessBeadsTransport(BeadsTransport):
    def __init__(self, *, spawn: _ProcessSpawner = _spawn_process) -> None:
        self._spawn = spawn

    async def execute(self, request: BeadsCommandRequest) -> BeadsCommandResult:
        env = dict(os.environ)
        if request.env:
            env.update(request.env)

        try:
            process = await self._spawn(
                *request.argv,
                cwd=str(request.cwd) if request.cwd else None,
                env=env,
            )
        except OSError as exc:
            raise BeadsCommandError(f"failed to spawn {' '.join(request.argv)}: {exc}") from exc

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(),
                timeout=request.timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            process.kill()
            try:
                stdout_bytes, stderr_bytes = await process.communicate()
            except Exception:
                stdout_bytes, stderr_bytes = (b"", b"")
            raise BeadsTimeoutError(
                f"command timed out after {request.timeout_seconds} seconds: "
                f"{' '.join(request.argv)}"
            ) from exc

        return BeadsCommandResult(
            argv=request.argv,
            returncode=process.returncode or 0,
            stdout=stdout_bytes.decode("utf-8", errors="replace"),
            stderr=stderr_bytes.decode("utf-8", errors="replace"),
            timed_out=False,
        )


def _extend_optional_args(argv: list[str], *items: tuple[str, object | None]) -> None:
    for flag, value in items:
        if value is not None:
            argv.extend([flag, str(value)])


def _short_detail(value: str | None) -> str | None:
    if not value:
        return None
    flattened = " ".join(part for part in value.strip().splitlines() if part.strip())
    if not flattened:
        return None
    return flattened[:220]


def _configured_backend(beads_root: Path) -> str | None:
    metadata_path = beads_root / "metadata.json"
    try:
        raw = metadata_path.read_text(encoding="utf-8")
    except OSError:
        return None
    if not raw.strip():
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    value = payload.get("backend")
    if not isinstance(value, str):
        return None
    backend = value.strip().lower()
    return backend or None


def _startup_dolt_store_exists(beads_root: Path) -> bool:
    dolt_root = beads_root / "dolt"
    if not dolt_root.is_dir():
        return False
    return any(candidate.is_dir() for candidate in dolt_root.glob("**/.dolt"))


def _extract_total_issues(payload: object) -> int | None:
    if not isinstance(payload, dict):
        return None
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        return None
    total = summary.get("total_issues")
    return total if isinstance(total, int) else None


def _is_embedded_backend_panic(detail: str) -> bool:
    normalized = detail.lower()
    return any(marker in normalized for marker in _EMBEDDED_BACKEND_PANIC_MARKERS)


class SubprocessBeadsClient(Beads):
    def __init__(
        self,
        *,
        transport: BeadsTransport | None = None,
        compatibility_policy: CompatibilityPolicy = DEFAULT_COMPATIBILITY_POLICY,
        executable: str = "bd",
        cwd: Path | None = None,
        beads_root: Path | None = None,
        env: Mapping[str, str] | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._transport = transport or SubprocessBeadsTransport()
        self._compatibility_policy = compatibility_policy
        self._executable = executable
        self._cwd = cwd
        self._beads_root = beads_root
        self._env = dict(env or {})
        self._timeout_seconds = timeout_seconds
        self._environment_cache: BeadsEnvironment | None = None

    @property
    def compatibility_policy(self) -> CompatibilityPolicy:
        return self._compatibility_policy

    async def inspect_environment(self) -> BeadsEnvironment:
        if self._environment_cache is not None:
            return self._environment_cache

        version = _parse_version(
            await self._execute(SupportedOperation.INSPECT_ENVIRONMENT, "--version")
        )
        probes = await asyncio.gather(
            *(
                self._probe_capability(capability, commands)
                for capability, commands in _CAPABILITY_PROBES
            )
        )
        environment = BeadsEnvironment(
            version=version,
            capabilities=(
                BeadsCapability.VERSION_REPORTING,
                *(capability for capability in probes if capability is not None),
            ),
        )
        self.compatibility_policy.assert_environment_supports(environment)
        for operation in (contract.operation for contract in self.compatibility_policy.operations):
            self.compatibility_policy.assert_environment_supports(environment, operation=operation)
        self._environment_cache = environment
        return environment

    async def inspect_startup_state(self) -> BeadsStartupState:
        beads_root = self._resolve_beads_root()
        if beads_root is None:
            return BeadsStartupState(
                classification=_STARTUP_UNKNOWN,
                migration_eligible=False,
                has_dolt_store=False,
                has_legacy_sqlite=False,
                dolt_issue_total=None,
                legacy_issue_total=None,
                reason="beads_root_not_configured",
            )

        has_legacy_sqlite = (beads_root / "beads.db").is_file()
        has_dolt_store = _startup_dolt_store_exists(beads_root)
        configured_backend = _configured_backend(beads_root)
        dolt_backend_expected = configured_backend in {None, "dolt"}
        if not beads_root.exists():
            return BeadsStartupState(
                classification=_STARTUP_UNKNOWN,
                migration_eligible=False,
                has_dolt_store=has_dolt_store,
                has_legacy_sqlite=has_legacy_sqlite,
                dolt_issue_total=None,
                legacy_issue_total=None,
                reason="beads_root_missing",
                backend=configured_backend,
            )

        (
            dolt_issue_total,
            dolt_detail,
            legacy_issue_total,
            legacy_detail,
        ) = await self._read_startup_issue_totals(
            beads_root=beads_root, has_legacy_sqlite=has_legacy_sqlite
        )
        (
            dolt_issue_total,
            dolt_detail,
            legacy_issue_total,
            legacy_detail,
        ) = await self._stabilize_startup_issue_totals(
            beads_root=beads_root,
            has_dolt_store=has_dolt_store,
            has_legacy_sqlite=has_legacy_sqlite,
            dolt_issue_total=dolt_issue_total,
            dolt_detail=dolt_detail,
            legacy_issue_total=legacy_issue_total,
            legacy_detail=legacy_detail,
        )

        if dolt_issue_total is None:
            dolt_count_source = "unavailable"
        elif has_dolt_store:
            dolt_count_source = "bd_stats_dolt_store"
        elif dolt_backend_expected:
            dolt_count_source = "bd_stats_without_dolt_store"
        else:
            dolt_count_source = "bd_stats_non_dolt_backend"

        legacy_count_source = (
            "bd_stats_legacy_sqlite" if legacy_issue_total is not None else "unavailable"
        )
        legacy_has_data = bool(legacy_issue_total and legacy_issue_total > 0)
        common_state = {
            "has_dolt_store": has_dolt_store,
            "has_legacy_sqlite": has_legacy_sqlite,
            "dolt_issue_total": dolt_issue_total,
            "legacy_issue_total": legacy_issue_total,
            "backend": configured_backend,
            "dolt_count_source": dolt_count_source,
            "legacy_count_source": legacy_count_source,
            "dolt_detail": dolt_detail,
            "legacy_detail": legacy_detail,
        }

        if not has_dolt_store:
            if legacy_has_data and dolt_backend_expected:
                return BeadsStartupState(
                    classification=_STARTUP_MISSING_DOLT,
                    migration_eligible=True,
                    reason="legacy_sqlite_has_data_while_dolt_is_unavailable",
                    **common_state,
                )
            reason = "dolt_store_missing_without_recoverable_legacy_data"
            if configured_backend and configured_backend != "dolt":
                reason = "dolt_store_missing_for_non_dolt_backend"
            return BeadsStartupState(
                classification=_STARTUP_UNKNOWN,
                migration_eligible=False,
                reason=reason,
                **common_state,
            )

        if dolt_issue_total is not None:
            if (
                has_legacy_sqlite
                and legacy_issue_total is not None
                and legacy_issue_total > dolt_issue_total
            ):
                return BeadsStartupState(
                    classification=_STARTUP_INSUFFICIENT_DOLT,
                    migration_eligible=True,
                    reason="legacy_issue_total_exceeds_dolt_issue_total",
                    **common_state,
                )
            return BeadsStartupState(
                classification=_STARTUP_HEALTHY,
                migration_eligible=False,
                reason="dolt_issue_total_is_healthy",
                **common_state,
            )

        if legacy_has_data and _is_embedded_backend_panic(dolt_detail or ""):
            return BeadsStartupState(
                classification=_STARTUP_MISSING_DOLT,
                migration_eligible=True,
                reason="legacy_sqlite_has_data_while_dolt_is_unavailable",
                **common_state,
            )
        return BeadsStartupState(
            classification=_STARTUP_UNKNOWN,
            migration_eligible=False,
            reason="insufficient_signals_for_classification",
            **common_state,
        )

    async def show(self, request: ShowIssueRequest) -> IssueRecord:
        await self._ensure_environment_supports(SupportedOperation.SHOW)
        result = await self._execute(
            SupportedOperation.SHOW,
            "show",
            request.issue_id,
            "--json",
        )
        return _parse_single_issue(result, operation=SupportedOperation.SHOW)

    async def list(self, request: ListIssuesRequest) -> tuple[IssueRecord, ...]:
        await self._ensure_environment_supports(SupportedOperation.LIST)
        argv = ["list", "--json"]
        _extend_optional_args(
            argv,
            ("--parent", request.parent_id),
            ("--status", request.status),
            ("--assignee", request.assignee),
            ("--title-contains", request.title_query),
        )
        for label in request.labels:
            argv.extend(["--label", label])
        if request.include_closed:
            argv.append("--all")
        if request.limit is not None:
            argv.extend(["--limit", str(request.limit)])

        result = await self._execute(SupportedOperation.LIST, *argv)
        return _parse_issue_list(result, operation=SupportedOperation.LIST)

    async def ready(self, request: ReadyIssuesRequest) -> tuple[IssueRecord, ...]:
        await self._ensure_environment_supports(SupportedOperation.READY)
        argv = ["ready", "--json"]
        if request.parent_id:
            argv.extend(["--parent", request.parent_id])

        result = await self._execute(SupportedOperation.READY, *argv)
        return _parse_issue_list(result, operation=SupportedOperation.READY)

    async def create(self, request: CreateIssueRequest) -> IssueRecord:
        await self._ensure_environment_supports(SupportedOperation.CREATE)
        if request.status is not None:
            raise UnsupportedOperationError(
                "bd create does not support setting status during creation"
            )

        argv = [
            "create",
            "--title",
            request.title,
            "--type",
            request.issue_type,
            "--json",
        ]
        _extend_optional_args(
            argv,
            ("--description", request.description),
            ("--design", request.design),
            ("--acceptance", request.acceptance_criteria),
            ("--assignee", request.assignee),
            ("--parent", request.parent_id),
            ("--priority", request.priority),
            ("--estimate", request.estimate),
        )
        if request.labels:
            argv.extend(["--labels", ",".join(request.labels)])

        result = await self._execute(SupportedOperation.CREATE, *argv)
        return _parse_single_issue(result, operation=SupportedOperation.CREATE)

    async def update(self, request: UpdateIssueRequest) -> IssueRecord:
        await self._ensure_environment_supports(SupportedOperation.UPDATE)
        if request.labels == ():
            raise UnsupportedOperationError(
                "bd update label clearing is not supported by this client"
            )

        argv = ["update", request.issue_id, "--json"]
        _extend_optional_args(
            argv,
            ("--title", request.title),
            ("--description", request.description),
            ("--design", request.design),
            ("--acceptance", request.acceptance_criteria),
            ("--status", request.status),
            ("--assignee", request.assignee),
            ("--priority", request.priority),
            ("--estimate", request.estimate),
        )
        if request.labels:
            for label in request.labels:
                argv.extend(["--set-labels", label])

        result = await self._execute(SupportedOperation.UPDATE, *argv)
        return _parse_single_issue(result, operation=SupportedOperation.UPDATE)

    async def close(self, request: CloseIssueRequest) -> IssueRecord:
        await self._ensure_environment_supports(SupportedOperation.CLOSE)
        argv = ["close", request.issue_id, "--json"]
        if request.reason:
            argv.extend(["--reason", request.reason])

        result = await self._execute(SupportedOperation.CLOSE, *argv)
        return _parse_single_issue(result, operation=SupportedOperation.CLOSE)

    async def add_dependency(self, request: DependencyMutationRequest) -> IssueRecord:
        return await self._mutate_dependency(SupportedOperation.DEPENDENCY_ADD, request, "add")

    async def remove_dependency(self, request: DependencyMutationRequest) -> IssueRecord:
        return await self._mutate_dependency(
            SupportedOperation.DEPENDENCY_REMOVE, request, "remove"
        )

    async def _mutate_dependency(
        self,
        operation: SupportedOperation,
        request: DependencyMutationRequest,
        command: str,
    ) -> IssueRecord:
        await self._ensure_environment_supports(operation)
        result = await self._execute(
            operation,
            "dep",
            command,
            request.issue_id,
            request.dependency_id,
            "--json",
        )
        payload = _load_payload(result, operation=operation)
        if not isinstance(payload, dict) or any(
            not isinstance(payload.get(field), str)
            for field in ("issue_id", "depends_on_id", "status")
        ):
            raise _parse_error(
                "failed to decode dependency mutation output",
                result,
                operation=operation,
            )
        return await self.show(ShowIssueRequest(issue_id=request.issue_id))

    async def _probe_capability(
        self,
        capability: BeadsCapability,
        commands: tuple[tuple[str, ...], ...],
    ) -> BeadsCapability | None:
        for command in commands:
            result = await self._execute_raw(command)
            if result.returncode != 0:
                return None
            if not decode_help_output(result).supports_json_output:
                return None
        return capability

    async def _ensure_environment_supports(self, operation: SupportedOperation) -> None:
        self.compatibility_policy.assert_environment_supports(
            await self.inspect_environment(),
            operation=operation,
        )

    def _resolve_beads_root(self) -> Path | None:
        if self._beads_root is not None:
            return self._beads_root
        if isinstance(raw := self._env.get("BEADS_DIR"), str) and raw.strip():
            return Path(raw)
        if isinstance(raw := os.environ.get("BEADS_DIR"), str) and raw.strip():
            return Path(raw)
        return None

    async def _read_stats_total(self, argv: Sequence[str]) -> tuple[int | None, str | None]:
        result = await self._execute_raw(argv, operation=SupportedOperation.INSPECT_STARTUP_STATE)
        if result.returncode != 0:
            return None, _short_detail(result.stderr.strip() or result.stdout.strip())
        raw = (result.stdout or "").strip()
        if not raw:
            return None, "empty stats payload"
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            return None, f"invalid stats payload ({exc})"
        issue_total = _extract_total_issues(payload)
        if issue_total is None:
            return None, "stats payload missing summary.total_issues"
        return issue_total, None

    async def _read_startup_issue_totals(
        self,
        *,
        beads_root: Path,
        has_legacy_sqlite: bool,
    ) -> tuple[int | None, str | None, int | None, str | None]:
        dolt_issue_total, dolt_detail = await self._read_stats_total(("stats", "--json"))
        legacy_issue_total: int | None = None
        legacy_detail: str | None = None
        if has_legacy_sqlite:
            legacy_issue_total, legacy_detail = await self._read_stats_total(
                ("--db", str(beads_root / "beads.db"), "stats", "--json")
            )
        return dolt_issue_total, dolt_detail, legacy_issue_total, legacy_detail

    async def _stabilize_startup_issue_totals(
        self,
        *,
        beads_root: Path,
        has_dolt_store: bool,
        has_legacy_sqlite: bool,
        dolt_issue_total: int | None,
        dolt_detail: str | None,
        legacy_issue_total: int | None,
        legacy_detail: str | None,
    ) -> tuple[int | None, str | None, int | None, str | None]:
        if not has_dolt_store or not has_legacy_sqlite:
            return dolt_issue_total, dolt_detail, legacy_issue_total, legacy_detail
        for _ in range(_STARTUP_COUNT_SKEW_RECHECK_ATTEMPTS):
            if dolt_issue_total is None or legacy_issue_total is None:
                return dolt_issue_total, dolt_detail, legacy_issue_total, legacy_detail
            if legacy_issue_total <= dolt_issue_total:
                return dolt_issue_total, dolt_detail, legacy_issue_total, legacy_detail
            (
                dolt_issue_total,
                dolt_detail,
                legacy_issue_total,
                legacy_detail,
            ) = await self._read_startup_issue_totals(
                beads_root=beads_root,
                has_legacy_sqlite=has_legacy_sqlite,
            )
        return dolt_issue_total, dolt_detail, legacy_issue_total, legacy_detail

    async def _execute(self, operation: SupportedOperation, *argv: str) -> BeadsCommandResult:
        result = await self._execute_raw(argv, operation=operation)
        if result.returncode != 0:
            command_text = " ".join(result.argv)
            detail = result.stderr.strip() or result.stdout.strip()
            message = f"bd command failed ({result.returncode}): {command_text}"
            if detail:
                message = f"{message}\n{detail}"
            raise BeadsCommandError(message)
        return result

    async def _execute_raw(
        self,
        argv: Sequence[str],
        *,
        operation: SupportedOperation = SupportedOperation.INSPECT_ENVIRONMENT,
    ) -> BeadsCommandResult:
        return await self._transport.execute(
            BeadsCommandRequest(
                operation=operation,
                argv=(self._executable, *argv),
                expects_json="--json" in argv,
                cwd=self._cwd,
                env=self._env or None,
                timeout_seconds=self._timeout_seconds,
            )
        )


def _parse_version(result: BeadsCommandResult) -> SemanticVersion:
    return decode_version_output(result)


def decode_version_output(result: BeadsCommandResult) -> SemanticVersion:
    """Decode ``bd --version`` output into a semantic version.

    Args:
        result: Raw command result from the Beads transport.

    Returns:
        Parsed semantic version for the installed ``bd`` executable.

    Raises:
        BeadsParseError: If no semantic version can be decoded.
    """

    output = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
    match = _SEMVER_SEARCH.search(output)
    if match is not None:
        return SemanticVersion(
            major=int(match.group(1)),
            minor=int(match.group(2)),
            patch=int(match.group(3)),
        )
    try:
        return SemanticVersion.model_validate(output)
    except ValidationError as exc:
        raise _parse_error(
            f"failed to parse bd version output: {output or '<empty>'}",
            result,
            operation=SupportedOperation.INSPECT_ENVIRONMENT,
        ) from exc


def decode_help_output(result: BeadsCommandResult) -> BeadsCommandHelp:
    """Decode ``bd ... --help`` output into normalized command metadata.

    Args:
        result: Raw command result from the Beads transport.

    Returns:
        Typed help metadata including normalized long flags.
    """

    output = "\n".join(part for part in (result.stdout, result.stderr) if part)
    flags = tuple(_FLAG_SEARCH.findall(output))
    return BeadsCommandHelp(
        argv=result.argv,
        flags=flags,
        supports_json_output=_JSON_FLAG in flags,
    )


def _parse_single_issue(
    result: BeadsCommandResult,
    *,
    operation: SupportedOperation,
) -> IssueRecord:
    issues = _parse_issue_list(result, operation=operation)
    if len(issues) != 1:
        raise _parse_error(
            f"expected exactly one issue from {operation.value}, got {len(issues)}",
            result,
            operation=operation,
        )
    return issues[0]


def _parse_issue_list(
    result: BeadsCommandResult,
    *,
    operation: SupportedOperation,
) -> tuple[IssueRecord, ...]:
    payload = _load_payload(result, operation=operation)
    if not isinstance(payload, (list, dict)):
        raise _parse_error(
            f"expected JSON object or array from {operation.value}",
            result,
            operation=operation,
        )
    items = payload if isinstance(payload, list) else [payload]
    try:
        return tuple(IssueRecord.model_validate(item) for item in items)
    except ValidationError as exc:
        raise _parse_error(
            f"failed to decode issue payload: {exc}",
            result,
            operation=operation,
        ) from exc


def _load_payload(
    result: BeadsCommandResult,
    *,
    operation: SupportedOperation,
) -> object:
    raw = result.stdout.strip()
    if not raw:
        raise _parse_error(
            f"expected JSON output from {operation.value}, received empty stdout",
            result,
            operation=operation,
        )
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise _parse_error(
            f"failed to parse JSON output from {operation.value}: {exc}",
            result,
            operation=operation,
        ) from exc


def _parse_error(
    message: str,
    result: BeadsCommandResult,
    *,
    operation: SupportedOperation,
) -> BeadsParseError:
    del result, operation
    return BeadsParseError(message)

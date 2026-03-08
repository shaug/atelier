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
    BeadsCommandRequest,
    BeadsCommandResult,
    BeadsEnvironment,
    BeadsModel,
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


class _DependencyMutationResult(BeadsModel):
    issue_id: str
    depends_on_id: str
    status: str
    type: str | None = None


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
            stdout=_decode_output(stdout_bytes),
            stderr=_decode_output(stderr_bytes),
            timed_out=False,
        )


def _decode_output(value: bytes) -> str:
    return value.decode("utf-8", errors="replace")


def _extend_optional_args(argv: list[str], *items: tuple[str, object | None]) -> None:
    for flag, value in items:
        if value is not None:
            argv.extend([flag, str(value)])


class SubprocessBeadsClient(Beads):
    def __init__(
        self,
        *,
        transport: BeadsTransport | None = None,
        compatibility_policy: CompatibilityPolicy = DEFAULT_COMPATIBILITY_POLICY,
        executable: str = "bd",
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._transport = transport or SubprocessBeadsTransport()
        self._compatibility_policy = compatibility_policy
        self._executable = executable
        self._cwd = cwd
        self._env = dict(env or {})
        self._timeout_seconds = timeout_seconds
        self._environment_cache: BeadsEnvironment | None = None

    @property
    def compatibility_policy(self) -> CompatibilityPolicy:
        return self._compatibility_policy

    async def inspect_environment(self) -> BeadsEnvironment:
        if self._environment_cache is not None:
            return self._environment_cache

        version_result = await self._execute(
            SupportedOperation.INSPECT_ENVIRONMENT,
            "--version",
        )
        version = _parse_version(version_result)

        probes = await asyncio.gather(
            *(
                self._probe_capability(capability, commands)
                for capability, commands in _CAPABILITY_PROBES
            )
        )

        capabilities = [BeadsCapability.VERSION_REPORTING]
        capabilities.extend(capability for capability in probes if capability is not None)
        environment = BeadsEnvironment(version=version, capabilities=tuple(capabilities))
        self.compatibility_policy.assert_environment_supports(environment)
        self._environment_cache = environment
        return environment

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
        try:
            _DependencyMutationResult.model_validate(payload)
        except ValidationError as exc:
            raise _parse_error(
                f"failed to decode dependency mutation output: {exc}",
                result,
                operation=operation,
            ) from exc
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
        return capability

    async def _ensure_environment_supports(self, operation: SupportedOperation) -> None:
        environment = await self.inspect_environment()
        self.compatibility_policy.assert_environment_supports(
            environment,
            operation=operation,
        )

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
    items: list[object]
    if isinstance(payload, list):
        items = list(payload)
    elif isinstance(payload, dict):
        items = [payload]
    else:
        raise _parse_error(
            f"expected JSON object or array from {operation.value}",
            result,
            operation=operation,
        )

    issues: list[IssueRecord] = []
    for index, item in enumerate(items):
        try:
            issues.append(IssueRecord.model_validate(item))
        except ValidationError as exc:
            raise _parse_error(
                f"failed to decode issue payload at index {index}: {exc}",
                result,
                operation=operation,
            ) from exc
    return tuple(issues)


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

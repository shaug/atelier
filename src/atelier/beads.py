"""Beads CLI helpers for Atelier."""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import sqlite3
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field

from . import bd_invocation, changesets, exec, messages
from .external_tickets import (
    ExternalTicketRef,
    external_ticket_payload,
    normalize_external_ticket_entry,
)
from .io import die
from .worker.models_boundary import BeadsIssueBoundary, parse_issue_boundary

POLICY_LABEL = "at:policy"
POLICY_SCOPE_LABEL = "scope:project"
EXTERNAL_TICKETS_KEY = "external_tickets"
PRESERVED_DESCRIPTION_KEYS = (EXTERNAL_TICKETS_KEY,)
HOOK_SLOT_NAME = "hook"
ATELIER_CUSTOM_TYPES = ("agent", "policy")
ATELIER_ISSUE_PREFIX = "at"
_AGENT_ISSUE_TYPE = "agent"
_FALLBACK_ISSUE_TYPE = "task"
_ISSUE_TYPE_CACHE: dict[Path, set[str]] = {}
_STORE_REPAIR_ATTEMPTED: set[Path] = set()
_EMBEDDED_PANIC_REPAIR_ATTEMPTED: set[Path] = set()
_STORE_REPAIR_ERROR_MARKERS = (
    "no beads database found",
    "database not initialized: issue_prefix config is missing",
    "fresh clone detected",
)
_EMBEDDED_BACKEND_PANIC_MARKERS = (
    "panic: runtime error",
    "invalid memory address or nil pointer dereference",
    "setcrashonfatalerror",
)
_TERMINAL_DEPENDENCY_STATUSES = {"closed", "done"}


class _IssueTypeModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str | None = None


class _IssueTypesPayloadModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    core_types: list[_IssueTypeModel | str] = Field(default_factory=list)
    custom_types: list[_IssueTypeModel | str] = Field(default_factory=list)
    types: list[_IssueTypeModel | str] = Field(default_factory=list)

    def as_payload(self) -> dict[str, object]:
        return {
            "core_types": [
                entry.model_dump(exclude_none=True) if isinstance(entry, _IssueTypeModel) else entry
                for entry in self.core_types
            ],
            "custom_types": [
                entry.model_dump(exclude_none=True) if isinstance(entry, _IssueTypeModel) else entry
                for entry in self.custom_types
            ],
            "types": [
                entry.model_dump(exclude_none=True) if isinstance(entry, _IssueTypeModel) else entry
                for entry in self.types
            ],
        }


@dataclass(frozen=True)
class BeadsIssueRecord:
    """Validated Beads issue payload with both raw and normalized views."""

    raw: dict[str, object]
    issue: BeadsIssueBoundary


@dataclass(frozen=True)
class BeadsClient:
    """Typed Beads command boundary for issue-centric queries."""

    beads_root: Path
    cwd: Path

    def run_command(
        self,
        args: list[str],
        *,
        allow_failure: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        return run_bd_command(
            args,
            beads_root=self.beads_root,
            cwd=self.cwd,
            allow_failure=allow_failure,
        )

    def run_json(self, args: list[str]) -> list[dict[str, object]]:
        return run_bd_json(args, beads_root=self.beads_root, cwd=self.cwd)

    def issue_records(self, args: list[str], *, source: str) -> list[BeadsIssueRecord]:
        return run_bd_issue_records(args, beads_root=self.beads_root, cwd=self.cwd, source=source)

    def issues(self, args: list[str], *, source: str) -> list[BeadsIssueBoundary]:
        return run_bd_issues(args, beads_root=self.beads_root, cwd=self.cwd, source=source)

    def show_issue(self, issue_id: str, *, source: str) -> BeadsIssueRecord | None:
        records = self.issue_records(["show", issue_id], source=source)
        return records[0] if records else None


def create_client(*, beads_root: Path, cwd: Path) -> BeadsClient:
    """Create a typed Beads client for a given store and working directory."""
    return BeadsClient(beads_root=beads_root, cwd=cwd)


@dataclass(frozen=True)
class ChangesetSummary:
    total: int
    ready: int
    merged: int
    abandoned: int
    remaining: int

    @property
    def ready_to_close(self) -> bool:
        return self.total > 0 and self.remaining == 0

    def as_dict(self) -> dict[str, int]:
        return {
            "total": self.total,
            "ready": self.ready,
            "merged": self.merged,
            "abandoned": self.abandoned,
            "remaining": self.remaining,
        }


@dataclass(frozen=True)
class ExternalTicketMetadataGap:
    issue_id: str
    providers: tuple[str, ...]


@dataclass(frozen=True)
class ExternalTicketMetadataRepairResult:
    issue_id: str
    providers: tuple[str, ...]
    recovered: bool
    repaired: bool
    ticket_count: int


@dataclass(frozen=True)
class ExternalTicketReconcileResult:
    issue_id: str
    stale_exported_github_tickets: int
    reconciled_tickets: int
    updated: bool
    needs_decision_notes: tuple[str, ...]


def beads_env(beads_root: Path) -> dict[str, str]:
    """Return an environment mapping with BEADS_DIR set."""
    env = os.environ.copy()
    env["BEADS_DIR"] = str(beads_root)
    env.setdefault("BEADS_DB", str(beads_root / "beads.db"))
    agent_id = env.get("ATELIER_AGENT_ID")
    if agent_id:
        env.setdefault("BD_ACTOR", agent_id)
        env.setdefault("BEADS_AGENT_NAME", agent_id)
    return env


def _command_output_detail(result: exec.CommandResult) -> str:
    return (result.stderr or result.stdout or "").strip()


def _is_missing_store_error(detail: str) -> bool:
    normalized = detail.lower()
    return any(marker in normalized for marker in _STORE_REPAIR_ERROR_MARKERS)


def _is_embedded_backend_panic(detail: str) -> bool:
    normalized = detail.lower()
    return any(marker in normalized for marker in _EMBEDDED_BACKEND_PANIC_MARKERS)


def _is_embedded_panic_repairable_command(args: list[str]) -> bool:
    if not args:
        return False
    command = args[0].strip().lower()
    if command in {"blocked", "list", "prime", "ready", "show", "stats"}:
        return True
    return command == "config" and len(args) >= 2 and args[1].strip().lower() == "get"


def _has_db_flag(args: list[str]) -> bool:
    return any(token == "--db" or token.startswith("--db=") for token in args)


def _store_repair_cwd(*, beads_root: Path, cwd: Path) -> Path:
    """Return the directory where Beads repair commands should run."""
    candidate = beads_root.parent
    if candidate.exists():
        return candidate
    return cwd


def _run_raw_bd_command(
    argv: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
) -> exec.CommandResult | None:
    return exec.run_with_runner(
        exec.CommandRequest(
            argv=tuple(argv),
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
        )
    )


def _repair_beads_store(*, beads_root: Path, cwd: Path, env: dict[str, str]) -> bool:
    """Attempt to repair a missing or stale Beads store.

    This routine intentionally avoids raising; callers decide whether to retry
    the original command or surface the original failure.
    """

    key = beads_root.resolve()
    if key in _STORE_REPAIR_ATTEMPTED:
        return False
    _STORE_REPAIR_ATTEMPTED.add(key)

    repair_cwd = _store_repair_cwd(beads_root=beads_root, cwd=cwd)

    _run_raw_bd_command(["bd", "doctor", "--fix", "--yes"], cwd=repair_cwd, env=env)

    init_args = ["bd", "init", "--prefix", ATELIER_ISSUE_PREFIX]
    if (beads_root / "issues.jsonl").exists():
        init_args.append("--from-jsonl")
    _run_raw_bd_command(init_args, cwd=repair_cwd, env=env)

    _run_raw_bd_command(
        ["bd", "config", "set", "issue_prefix", ATELIER_ISSUE_PREFIX],
        cwd=repair_cwd,
        env=env,
    )
    _run_raw_bd_command(
        ["bd", "config", "set", "beads.role", "maintainer"],
        cwd=repair_cwd,
        env=env,
    )
    verify = _run_raw_bd_command(
        ["bd", "config", "get", "issue_prefix", "--json"],
        cwd=repair_cwd,
        env=env,
    )
    return verify is not None and verify.returncode == 0


def _attempt_embedded_panic_repair(*, beads_root: Path, cwd: Path, env: dict[str, str]) -> bool:
    """Run a one-time embedded-store repair attempt for panic recovery."""
    key = beads_root.resolve()
    if key in _EMBEDDED_PANIC_REPAIR_ATTEMPTED:
        return False
    _EMBEDDED_PANIC_REPAIR_ATTEMPTED.add(key)
    repair_cwd = _store_repair_cwd(beads_root=beads_root, cwd=cwd)
    _run_raw_bd_command(["bd", "doctor", "--fix", "--yes"], cwd=repair_cwd, env=env)
    return True


def _is_repairable_command(args: list[str]) -> bool:
    if not args:
        return False
    command = args[0]
    if command in {"doctor", "init"}:
        return False
    if command == "config" and len(args) >= 3 and args[1] == "set":
        key = args[2].strip().lower()
        if key in {"issue_prefix", "beads.role"}:
            return False
    return True


def _embedded_panic_guidance(*, repair_attempted: bool) -> str:
    if repair_attempted:
        return (
            "Detected an embedded storage panic from bd. Atelier retried with an explicit sqlite "
            "database path and ran `bd doctor --fix --yes`, but the command still failed. "
            "Verify store health with `bd doctor` and retry once `bd show --json <issue-id>` "
            "succeeds."
        )
    return (
        "Detected an embedded storage panic from bd. Atelier retried with an explicit sqlite "
        "database path, but automatic repair was skipped because this command may mutate state. "
        "Run `bd doctor --fix --yes` and retry."
    )


def _missing_store_guidance(*, beads_root: Path) -> str:
    return (
        "Detected a missing or uninitialized Beads store. Verify `BEADS_DIR` points at "
        f"{beads_root} and run `bd doctor --fix --yes`, then retry."
    )


def _update_in_progress_targets(args: list[str]) -> tuple[str, ...]:
    if not args or args[0] != "update":
        return ()
    status: str | None = None
    for index, token in enumerate(args):
        if token != "--status":
            continue
        if index + 1 < len(args):
            status = str(args[index + 1]).strip().lower()
        break
    if status != "in_progress":
        return ()
    targets: list[str] = []
    index = 1
    while index < len(args):
        token = args[index]
        if token.startswith("-"):
            break
        cleaned = token.strip()
        if cleaned:
            targets.append(cleaned)
        index += 1
    return tuple(targets)


def _raw_bd_json(
    args: list[str],
    *,
    beads_root: Path,
    cwd: Path,
    env: dict[str, str],
) -> tuple[list[dict[str, object]], str | None]:
    command = list(args)
    if "--json" not in command:
        command.append("--json")
    has_db_flag = _has_db_flag(command)
    result = _run_raw_bd_command(["bd", *command], cwd=cwd, env=env)
    if result is None:
        return [], "missing required command: bd"
    detail = _command_output_detail(result)
    fallback_command: list[str] | None = None
    if result.returncode != 0 and _is_embedded_backend_panic(detail) and not has_db_flag:
        fallback = bd_invocation.with_bd_mode(
            *command,
            beads_dir=str(beads_root),
            env=env,
        )
        fallback_command = fallback
        retried = _run_raw_bd_command(fallback, cwd=cwd, env=env)
        if retried is None:
            return [], "missing required command: bd"
        result = retried
        detail = _command_output_detail(result)
    panic_repair_attempted = False
    if (
        result.returncode != 0
        and _is_embedded_backend_panic(detail)
        and _is_embedded_panic_repairable_command(command)
    ):
        panic_repair_attempted = _attempt_embedded_panic_repair(
            beads_root=beads_root,
            cwd=cwd,
            env=env,
        )
        if panic_repair_attempted:
            retry_command = fallback_command or ["bd", *command]
            retried_after_repair = _run_raw_bd_command(retry_command, cwd=cwd, env=env)
            if retried_after_repair is None:
                return [], "missing required command: bd"
            result = retried_after_repair
            detail = _command_output_detail(result)
    if (
        result.returncode != 0
        and _is_repairable_command(command)
        and _is_missing_store_error(detail)
        and _repair_beads_store(beads_root=beads_root, cwd=cwd, env=env)
    ):
        retried_after_store_repair = _run_raw_bd_command(["bd", *command], cwd=cwd, env=env)
        if retried_after_store_repair is None:
            return [], "missing required command: bd"
        result = retried_after_store_repair
        detail = _command_output_detail(result)
    if result.returncode != 0:
        guidance = ""
        if _is_embedded_backend_panic(detail):
            guidance = _embedded_panic_guidance(repair_attempted=panic_repair_attempted)
        elif _is_missing_store_error(detail):
            guidance = _missing_store_guidance(beads_root=beads_root)
        if guidance:
            return [], f"{detail or 'bd command failed'}\n{guidance}"
        return [], (detail or "bd command failed")
    raw = (result.stdout or "").strip()
    if not raw:
        return [], None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        return [], f"failed to parse bd json output: {exc}"
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)], None
    if isinstance(payload, dict):
        return [payload], None
    return [], None


def _show_issue_for_gate(
    issue_id: str,
    *,
    beads_root: Path,
    cwd: Path,
    env: dict[str, str],
) -> tuple[dict[str, object] | None, str | None]:
    payload, error = _raw_bd_json(
        ["show", issue_id],
        beads_root=beads_root,
        cwd=cwd,
        env=env,
    )
    if error:
        return None, error
    if not payload:
        return None, f"issue {issue_id} not found"
    return payload[0], None


def _issue_has_label(issue: dict[str, object], label: str) -> bool:
    labels = issue.get("labels")
    if not isinstance(labels, list):
        return False
    for entry in labels:
        if entry is None:
            continue
        if str(entry).strip() == label:
            return True
    return False


def _blocking_dependency_states(
    issue: dict[str, object],
    *,
    beads_root: Path,
    cwd: Path,
    env: dict[str, str],
) -> tuple[str, ...]:
    try:
        boundary = parse_issue_boundary(issue, source="beads:in_progress_gate")
    except ValueError as exc:
        return (f"invalid issue payload ({exc})",)
    blockers: list[str] = []
    for dependency_id in boundary.dependency_ids:
        dependency_issue, error = _show_issue_for_gate(
            dependency_id,
            beads_root=beads_root,
            cwd=cwd,
            env=env,
        )
        if error or dependency_issue is None:
            blockers.append(f"{dependency_id}(unavailable)")
            continue
        status = str(dependency_issue.get("status") or "").strip().lower()
        if status in _TERMINAL_DEPENDENCY_STATUSES:
            continue
        blockers.append(f"{dependency_id}({status or 'unknown'})")
    return tuple(blockers)


def _enforce_in_progress_dependency_gate(
    args: list[str],
    *,
    beads_root: Path,
    cwd: Path,
    env: dict[str, str],
) -> None:
    targets = _update_in_progress_targets(args)
    if not targets:
        return
    for issue_id in targets:
        issue, error = _show_issue_for_gate(
            issue_id,
            beads_root=beads_root,
            cwd=cwd,
            env=env,
        )
        if error:
            die(
                "cannot set issue "
                f"{issue_id} to in_progress: unable to evaluate dependencies ({error})"
            )
        if issue is None or not _issue_has_label(issue, "at:changeset"):
            continue
        blockers = _blocking_dependency_states(
            issue,
            beads_root=beads_root,
            cwd=cwd,
            env=env,
        )
        if not blockers:
            continue
        detail = ", ".join(blockers)
        die(
            f"cannot set changeset {issue_id} to in_progress: blocking dependencies "
            f"not complete ({detail}). Close dependencies before retrying."
        )


def run_bd_command(
    args: list[str],
    *,
    beads_root: Path,
    cwd: Path,
    allow_failure: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run a bd command and return the CompletedProcess.

    Raises a user-facing error when bd is missing or returns a non-zero status
    unless allow_failure is True.
    """
    cmd = ["bd", *args]
    env = beads_env(beads_root)
    try:
        bd_invocation.ensure_supported_bd_version(env=env)
    except RuntimeError as exc:
        die(str(exc))
    _enforce_in_progress_dependency_gate(args, beads_root=beads_root, cwd=cwd, env=env)
    request = exec.CommandRequest(
        argv=tuple(cmd),
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
    )
    result = exec.run_with_runner(request)
    if result is None:
        die("missing required command: bd")
    detail = _command_output_detail(result)
    has_db_flag = _has_db_flag(args)
    fallback_request: exec.CommandRequest | None = None
    if result.returncode != 0 and _is_embedded_backend_panic(detail) and not has_db_flag:
        fallback_cmd = bd_invocation.with_bd_mode(
            *args,
            beads_dir=str(beads_root),
            env=env,
        )
        fallback_request = replace(request, argv=tuple(fallback_cmd))
        retried = exec.run_with_runner(fallback_request)
        if retried is None:
            die("missing required command: bd")
        result = retried
        detail = _command_output_detail(result)
    panic_repair_attempted = False
    if (
        result.returncode != 0
        and not allow_failure
        and _is_embedded_backend_panic(detail)
        and _is_embedded_panic_repairable_command(args)
    ):
        panic_repair_attempted = _attempt_embedded_panic_repair(
            beads_root=beads_root,
            cwd=cwd,
            env=env,
        )
        if panic_repair_attempted:
            retry_request = fallback_request or request
            retried_after_repair = exec.run_with_runner(retry_request)
            if retried_after_repair is None:
                die("missing required command: bd")
            result = retried_after_repair
            detail = _command_output_detail(result)
    if (
        result.returncode != 0
        and not allow_failure
        and _is_repairable_command(args)
        and _is_missing_store_error(detail)
        and _repair_beads_store(beads_root=beads_root, cwd=cwd, env=env)
    ):
        result = exec.run_with_runner(request)
        if result is None:
            die("missing required command: bd")
        detail = _command_output_detail(result)

    if result.returncode != 0 and not allow_failure:
        message = f"command failed: {' '.join(cmd)}"
        if detail:
            message = f"{message}\n{detail}"
        if _is_embedded_backend_panic(detail):
            message = (
                f"{message}\n{_embedded_panic_guidance(repair_attempted=panic_repair_attempted)}"
            )
        elif _is_missing_store_error(detail):
            message = f"{message}\n{_missing_store_guidance(beads_root=beads_root)}"
        die(message)
    return subprocess.CompletedProcess(
        args=list(result.argv),
        returncode=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
    )


def close_issue(
    issue_id: str,
    *,
    beads_root: Path,
    cwd: Path,
    allow_failure: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Close a Beads issue and reconcile exported GitHub ticket metadata.

    Args:
        issue_id: Bead identifier to close.
        beads_root: Path to the Beads data directory.
        cwd: Working directory for `bd` invocation.
        allow_failure: Whether to allow close failures without exiting.

    Returns:
        `CompletedProcess` for the underlying `bd close` command.
    """
    cleaned_issue_id = issue_id.strip()
    if not cleaned_issue_id:
        raise ValueError("issue_id must not be empty")
    result = run_bd_command(
        ["close", cleaned_issue_id],
        beads_root=beads_root,
        cwd=cwd,
        allow_failure=allow_failure,
    )
    if result.returncode == 0:
        reconcile_closed_issue_exported_github_tickets(
            cleaned_issue_id,
            beads_root=beads_root,
            cwd=cwd,
        )
    return result


def run_bd_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:
    """Run a bd command with --json and return parsed output."""
    cmd = list(args)
    if "--json" not in cmd:
        cmd.append("--json")
    result = run_bd_command(cmd, beads_root=beads_root, cwd=cwd)
    raw = result.stdout.strip() if result.stdout else ""
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        die(f"failed to parse bd json output: {exc}")
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        return [payload]
    return []


def parse_issue_records(issues: list[dict[str, object]], *, source: str) -> list[BeadsIssueRecord]:
    """Validate Beads issue payloads while preserving raw issue mappings."""
    records: list[BeadsIssueRecord] = []
    for index, raw in enumerate(issues):
        issue = parse_issue_boundary(raw, source=f"{source}[{index}]")
        records.append(BeadsIssueRecord(raw=raw, issue=issue))
    return records


def run_bd_issue_records(
    args: list[str], *, beads_root: Path, cwd: Path, source: str
) -> list[BeadsIssueRecord]:
    """Run a Beads query and return validated issue records."""
    return parse_issue_records(run_bd_json(args, beads_root=beads_root, cwd=cwd), source=source)


def run_bd_issues(
    args: list[str], *, beads_root: Path, cwd: Path, source: str
) -> list[BeadsIssueBoundary]:
    """Run a Beads query and return validated issue boundary models."""
    return [
        record.issue
        for record in run_bd_issue_records(args, beads_root=beads_root, cwd=cwd, source=source)
    ]


def prime_addendum(*, beads_root: Path, cwd: Path) -> str | None:
    """Return `bd prime --full` markdown without failing the caller."""
    env = beads_env(beads_root)
    command = ["bd", "prime", "--full"]
    result = exec.run_with_runner(
        exec.CommandRequest(
            argv=tuple(command),
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
        )
    )
    if result is None:
        return None
    if result.returncode != 0:
        return None
    output = (result.stdout or "").strip()
    return output or None


def _parse_types_payload(raw: str) -> dict[str, object] | None:
    if not raw:
        return None
    raw = raw.strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            return json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            return None


def _extract_issue_types(payload: object) -> set[str]:
    if not isinstance(payload, dict):
        return set()
    types: set[str] = set()
    for key in ("core_types", "custom_types", "types"):
        items = payload.get(key)
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, dict):
                name = item.get("name")
                if isinstance(name, str) and name:
                    types.add(name)
            elif isinstance(item, str) and item:
                types.add(item)
    return types


def _list_issue_types(*, beads_root: Path, cwd: Path) -> set[str]:
    cached = _ISSUE_TYPE_CACHE.get(beads_root)
    if cached is not None:
        return cached
    env = beads_env(beads_root)
    command = ["bd", "types", "--json"]
    result = exec.run_with_runner(
        exec.CommandRequest(
            argv=tuple(command),
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
        )
    )
    if result is None:
        types = {_FALLBACK_ISSUE_TYPE}
        _ISSUE_TYPE_CACHE[beads_root] = types
        return types
    if result.returncode != 0:
        types = {_FALLBACK_ISSUE_TYPE}
        _ISSUE_TYPE_CACHE[beads_root] = types
        return types
    payload: dict[str, object] | None = None
    try:
        parsed = exec.parse_json_model_optional(
            result, model_type=_IssueTypesPayloadModel, context="bd types"
        )
        payload = parsed.as_payload() if parsed is not None else None
    except exec.CommandParseError:
        payload = _parse_types_payload(result.stdout or "")
    types = _extract_issue_types(payload)
    if not types:
        types = {_FALLBACK_ISSUE_TYPE}
    _ISSUE_TYPE_CACHE[beads_root] = types
    return types


def _agent_issue_type(*, beads_root: Path, cwd: Path) -> str:
    types = _list_issue_types(beads_root=beads_root, cwd=cwd)
    if _AGENT_ISSUE_TYPE in types:
        return _AGENT_ISSUE_TYPE
    return _FALLBACK_ISSUE_TYPE


def _parse_custom_types(value: str | None) -> list[str]:
    if not value:
        return []
    entries = []
    seen = set()
    for part in value.split(","):
        entry = part.strip()
        if not entry or entry in seen:
            continue
        seen.add(entry)
        entries.append(entry)
    return entries


def ensure_atelier_store(*, beads_root: Path, cwd: Path) -> bool:
    """Ensure the Atelier Beads store exists with the expected prefix."""
    if beads_root.exists():
        return False
    run_bd_command(
        ["init", "--prefix", ATELIER_ISSUE_PREFIX, "--quiet"],
        beads_root=beads_root,
        cwd=cwd,
    )
    return True


def _current_issue_prefix(*, beads_root: Path, cwd: Path) -> str:
    result = run_bd_command(
        ["config", "get", "issue_prefix", "--json"], beads_root=beads_root, cwd=cwd
    )
    payload = _parse_types_payload(result.stdout or "")
    if isinstance(payload, dict):
        value = payload.get("value")
        if isinstance(value, str):
            return value.strip()
    return ""


def ensure_issue_prefix(
    prefix: str,
    *,
    beads_root: Path,
    cwd: Path,
) -> bool:
    """Ensure Beads uses the expected issue prefix."""
    expected = prefix.strip().lower()
    if not expected:
        return False
    current = _current_issue_prefix(beads_root=beads_root, cwd=cwd)
    if current == expected:
        return False
    run_bd_command(["config", "set", "issue_prefix", expected], beads_root=beads_root, cwd=cwd)
    # Keep existing issue ids aligned with configured prefix.
    run_bd_command(["rename-prefix", f"{expected}-", "--repair"], beads_root=beads_root, cwd=cwd)
    return True


def ensure_atelier_issue_prefix(*, beads_root: Path, cwd: Path) -> bool:
    """Ensure Atelier uses the canonical issue prefix."""
    return ensure_issue_prefix(ATELIER_ISSUE_PREFIX, beads_root=beads_root, cwd=cwd)


def ensure_custom_types(
    required: list[str],
    *,
    beads_root: Path,
    cwd: Path,
) -> bool:
    """Ensure the Beads config includes required custom issue types."""
    required_clean = []
    seen = set()
    for entry in required:
        value = entry.strip()
        if not value or value in seen:
            continue
        seen.add(value)
        required_clean.append(value)
    if not required_clean:
        return False
    result = run_bd_command(
        ["config", "get", "types.custom", "--json"],
        beads_root=beads_root,
        cwd=cwd,
    )
    payload = _parse_types_payload(result.stdout or "")
    current_value = ""
    if isinstance(payload, dict):
        value = payload.get("value")
        if isinstance(value, str):
            current_value = value
    existing = _parse_custom_types(current_value)
    missing = [entry for entry in required_clean if entry not in existing]
    if not missing:
        return False
    updated = ",".join([*existing, *missing])
    run_bd_command(["config", "set", "types.custom", updated], beads_root=beads_root, cwd=cwd)
    _ISSUE_TYPE_CACHE.pop(beads_root, None)
    return True


def ensure_atelier_types(*, beads_root: Path, cwd: Path) -> bool:
    """Ensure Atelier-required custom issue types are configured."""
    return ensure_custom_types(list(ATELIER_CUSTOM_TYPES), beads_root=beads_root, cwd=cwd)


def _issue_labels(issue: dict[str, object]) -> set[str]:
    labels = issue.get("labels")
    if not isinstance(labels, list):
        return set()
    return {str(label) for label in labels if label}


def _is_standalone_changeset_without_epic_label(issue: dict[str, object]) -> bool:
    labels = _issue_labels(issue)
    if "at:changeset" not in labels or "at:epic" in labels:
        return False
    try:
        boundary = parse_issue_boundary(issue, source="beads:claim_epic")
    except ValueError:
        return False
    return boundary.parent_id is None


def _agent_role(agent_id: object) -> str | None:
    if not isinstance(agent_id, str):
        return None
    parts = [part for part in agent_id.split("/") if part]
    if len(parts) >= 2 and parts[0] == "atelier":
        return parts[1].strip().lower() or None
    if parts:
        value = parts[0].strip().lower()
        return value or None
    return None


def _is_planner_assignee(agent_id: object) -> bool:
    return _agent_role(agent_id) == "planner"


def summarize_changesets(
    changesets: list[dict[str, object]],
    *,
    ready: list[dict[str, object]] | None = None,
) -> ChangesetSummary:
    """Return a summary of changeset lifecycle counts."""
    ready_count = len(ready) if ready is not None else 0
    merged = 0
    abandoned = 0
    for issue in changesets:
        labels = _issue_labels(issue)
        if "cs:merged" in labels:
            merged += 1
        if "cs:abandoned" in labels:
            abandoned += 1
    total = len(changesets)
    remaining = max(total - merged - abandoned, 0)
    return ChangesetSummary(
        total=total,
        ready=ready_count,
        merged=merged,
        abandoned=abandoned,
        remaining=remaining,
    )


def list_child_changesets(
    parent_id: str,
    *,
    beads_root: Path,
    cwd: Path,
    include_closed: bool = False,
) -> list[dict[str, object]]:
    """List direct child changesets for a parent issue."""
    args = ["list", "--parent", parent_id, "--label", "at:changeset"]
    if include_closed:
        args.append("--all")
    return run_bd_json(args, beads_root=beads_root, cwd=cwd)


def list_descendant_changesets(
    parent_id: str,
    *,
    beads_root: Path,
    cwd: Path,
    include_closed: bool = False,
) -> list[dict[str, object]]:
    """List descendant changesets (children + deeper descendants)."""
    descendants: list[dict[str, object]] = []
    seen: set[str] = set()
    queue = [parent_id]
    while queue:
        current = queue.pop(0)
        children = list_child_changesets(
            current,
            beads_root=beads_root,
            cwd=cwd,
            include_closed=include_closed,
        )
        for issue in children:
            issue_id = issue.get("id")
            if not isinstance(issue_id, str) or not issue_id:
                continue
            if issue_id in seen:
                continue
            seen.add(issue_id)
            descendants.append(issue)
            queue.append(issue_id)
    return descendants


def _normalize_description(description: str | None) -> str:
    if not description:
        return ""
    return description.rstrip("\n")


def _parse_description_fields(description: str | None) -> dict[str, str]:
    fields: dict[str, str] = {}
    if not description:
        return fields
    for line in description.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        if not key:
            continue
        fields[key] = value.strip()
    return fields


def parse_description_fields(description: str | None) -> dict[str, str]:
    """Parse key/value fields from a bead description."""
    return _parse_description_fields(description)


def issue_description_fields(
    issue_id: str,
    *,
    beads_root: Path,
    cwd: Path,
) -> dict[str, str]:
    """Read parsed description fields for a bead.

    Args:
        issue_id: Bead identifier to inspect.
        beads_root: Path to the Beads store.
        cwd: Repository working directory for `bd`.

    Returns:
        Parsed description key/value fields, or an empty dict when the issue is
        missing.
    """
    issues = run_bd_json(["show", issue_id], beads_root=beads_root, cwd=cwd)
    if not issues:
        return {}
    description = issues[0].get("description")
    text = description if isinstance(description, str) else ""
    return _parse_description_fields(text)


def update_issue_description_fields(
    issue_id: str,
    fields: dict[str, str | None],
    *,
    beads_root: Path,
    cwd: Path,
) -> dict[str, object]:
    """Upsert multiple description fields on a bead.

    Args:
        issue_id: Bead identifier to update.
        fields: Mapping of description keys to values. `None` stores `null`.
        beads_root: Path to the Beads store.
        cwd: Repository working directory for `bd`.

    Returns:
        Refreshed issue payload when available, otherwise the pre-update issue.
    """
    issues = run_bd_json(["show", issue_id], beads_root=beads_root, cwd=cwd)
    if not issues:
        die(f"issue not found: {issue_id}")
    issue = issues[0]
    description = issue.get("description")
    updated = description if isinstance(description, str) else ""
    changed = False
    for key, value in fields.items():
        next_value = _update_description_field(updated, key=key, value=value)
        if next_value != updated:
            changed = True
            updated = next_value
    if changed:
        _update_issue_description(issue_id, updated, beads_root=beads_root, cwd=cwd)
    refreshed = run_bd_json(["show", issue_id], beads_root=beads_root, cwd=cwd)
    return refreshed[0] if refreshed else issue


def _normalize_hook_value(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned or cleaned.lower() == "null":
            return None
        return cleaned
    if isinstance(value, (int, float)):
        return str(value)
    return None


def _extract_hook_from_slot_payload(payload: object) -> str | None:
    if isinstance(payload, str):
        return _normalize_hook_value(payload)
    if isinstance(payload, list):
        for item in payload:
            hook = _extract_hook_from_slot_payload(item)
            if hook:
                return hook
        return None
    if not isinstance(payload, dict):
        return None
    if "hook" in payload:
        return _extract_hook_from_slot_payload(payload.get("hook"))
    if "slots" in payload and isinstance(payload["slots"], dict):
        return _extract_hook_from_slot_payload(payload["slots"].get("hook"))
    if "id" in payload:
        return _normalize_hook_value(payload.get("id"))
    if "issue_id" in payload:
        return _normalize_hook_value(payload.get("issue_id"))
    if "bead_id" in payload:
        return _normalize_hook_value(payload.get("bead_id"))
    if "bead" in payload:
        return _normalize_hook_value(payload.get("bead"))
    return None


def _slot_show_hook(
    agent_bead_id: str,
    *,
    beads_root: Path,
    cwd: Path,
) -> str | None:
    result = run_bd_command(
        ["slot", "show", agent_bead_id, "--json"],
        beads_root=beads_root,
        cwd=cwd,
        allow_failure=True,
    )
    if result.returncode != 0:
        return None
    raw = result.stdout.strip() if result.stdout else ""
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return _extract_hook_from_slot_payload(payload)


def _slot_set_hook(
    agent_bead_id: str,
    epic_id: str,
    *,
    beads_root: Path,
    cwd: Path,
) -> None:
    run_bd_command(
        ["slot", "set", agent_bead_id, HOOK_SLOT_NAME, epic_id],
        beads_root=beads_root,
        cwd=cwd,
        allow_failure=True,
    )


def get_agent_hook(
    agent_bead_id: str,
    *,
    beads_root: Path,
    cwd: Path,
) -> str | None:
    """Return the currently hooked epic id for an agent bead."""
    slot_hook = _slot_show_hook(agent_bead_id, beads_root=beads_root, cwd=cwd)
    if slot_hook:
        return slot_hook
    issues = run_bd_json(["show", agent_bead_id], beads_root=beads_root, cwd=cwd)
    if not issues:
        return None
    issue = issues[0]
    description = issue.get("description")
    fields = _parse_description_fields(description if isinstance(description, str) else "")
    hook = _normalize_hook_value(fields.get("hook_bead"))
    if hook:
        _slot_set_hook(agent_bead_id, hook, beads_root=beads_root, cwd=cwd)
    return hook


def workspace_label(root_branch: str) -> str:
    """Return the workspace label for a root branch."""
    return f"workspace:{root_branch}"


def external_label(provider: str) -> str:
    """Return the external ticket label for a provider."""
    return f"ext:{provider}"


def policy_role_label(role: str) -> str:
    """Return the policy role label."""
    return f"role:{role}"


def extract_workspace_root_branch(issue: dict[str, object]) -> str | None:
    """Extract the workspace root branch from a bead."""
    description = issue.get("description")
    fields = _parse_description_fields(description if isinstance(description, str) else "")
    root_branch = fields.get("workspace.root_branch")
    if root_branch:
        return root_branch
    labels = issue.get("labels")
    if isinstance(labels, list):
        for label in labels:
            if isinstance(label, str) and label.startswith("workspace:"):
                return label[len("workspace:") :]
    return None


def extract_worktree_path(issue: dict[str, object]) -> str | None:
    """Extract the worktree path from a bead description."""
    description = issue.get("description")
    fields = _parse_description_fields(description if isinstance(description, str) else "")
    worktree_path = fields.get("worktree_path")
    if worktree_path:
        return worktree_path
    return None


def parse_external_tickets(description: str | None) -> list[ExternalTicketRef]:
    """Parse external ticket references from a description."""
    if not description:
        return []
    fields = _parse_description_fields(description)
    tickets_raw = fields.get(EXTERNAL_TICKETS_KEY)
    if not tickets_raw or tickets_raw.lower() == "null":
        return []
    try:
        payload = json.loads(tickets_raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    tickets: list[ExternalTicketRef] = []
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        normalized = normalize_external_ticket_entry(entry)
        if normalized is None:
            continue
        tickets.append(normalized)
    return tickets


_GITHUB_API_ISSUE_PATH = re.compile(r"^/repos/(?P<owner>[^/]+)/(?P<repo>[^/]+)/issues/[^/]+$")
_GITHUB_WEB_ISSUE_PATH = re.compile(r"^/(?P<owner>[^/]+)/(?P<repo>[^/]+)/issues/[^/]+$")
_EXTERNAL_CLOSE_NOTE_PREFIX = "external_close_pending:"


def _github_repo_from_ticket_url(url: str | None) -> str | None:
    cleaned = (url or "").strip()
    if not cleaned:
        return None
    parsed = urlparse(cleaned)
    host = parsed.netloc.lower().split(":", 1)[0]
    path = parsed.path or ""
    if host == "api.github.com":
        match = _GITHUB_API_ISSUE_PATH.match(path)
    elif host in {"github.com", "www.github.com"}:
        match = _GITHUB_WEB_ISSUE_PATH.match(path)
    else:
        return None
    if not match:
        return None
    owner = match.group("owner").strip()
    repo = match.group("repo").strip()
    if not owner or not repo:
        return None
    return f"{owner}/{repo}"


def _close_action_for_ticket(ticket: ExternalTicketRef) -> str:
    # Keep context and explicit opt-out links untouched on local close.
    if ticket.relation == "context" or ticket.on_close == "none":
        return "none"
    if ticket.on_close in {"close", "comment"}:
        return "close"
    if ticket.on_close == "sync":
        return "sync"
    if ticket.direction != "exported":
        return "none"
    return "close"


def _merge_ticket_state(
    ticket: ExternalTicketRef,
    refreshed: ExternalTicketRef,
    *,
    assume_closed: bool = False,
) -> ExternalTicketRef:
    return replace(
        ticket,
        url=refreshed.url or ticket.url,
        state=refreshed.state or ("closed" if assume_closed else ticket.state),
        raw_state=refreshed.raw_state or ticket.raw_state,
        state_updated_at=refreshed.state_updated_at or ticket.state_updated_at,
        content_updated_at=refreshed.content_updated_at or ticket.content_updated_at,
        notes_updated_at=refreshed.notes_updated_at or ticket.notes_updated_at,
        last_synced_at=dt.datetime.now(tz=dt.timezone.utc).isoformat(),
    )


def _append_external_close_note(
    issue_id: str,
    note: str,
    *,
    beads_root: Path,
    cwd: Path,
) -> None:
    run_bd_command(
        ["update", issue_id, "--append-notes", f"{_EXTERNAL_CLOSE_NOTE_PREFIX} {note}"],
        beads_root=beads_root,
        cwd=cwd,
        allow_failure=True,
    )


def reconcile_closed_issue_exported_github_tickets(
    issue_id: str,
    *,
    beads_root: Path,
    cwd: Path,
) -> ExternalTicketReconcileResult:
    """Reconcile stale exported GitHub ticket metadata for a closed bead.

    Exported GitHub links default to close-on-bead-close unless the ticket is
    `relation=context` or explicitly sets `on_close=none`.
    """
    issues = run_bd_json(["show", issue_id], beads_root=beads_root, cwd=cwd)
    if not issues:
        return ExternalTicketReconcileResult(
            issue_id=issue_id,
            stale_exported_github_tickets=0,
            reconciled_tickets=0,
            updated=False,
            needs_decision_notes=tuple(),
        )
    issue = issues[0]
    status = str(issue.get("status") or "").strip().lower()
    if status not in {"closed", "done"}:
        return ExternalTicketReconcileResult(
            issue_id=issue_id,
            stale_exported_github_tickets=0,
            reconciled_tickets=0,
            updated=False,
            needs_decision_notes=tuple(),
        )
    description = issue.get("description")
    existing_tickets = parse_external_tickets(description if isinstance(description, str) else None)
    if not existing_tickets:
        return ExternalTicketReconcileResult(
            issue_id=issue_id,
            stale_exported_github_tickets=0,
            reconciled_tickets=0,
            updated=False,
            needs_decision_notes=tuple(),
        )

    from .github_issues_provider import GithubIssuesProvider

    stale = 0
    reconciled = 0
    updated = False
    notes: list[str] = []
    provider_cache: dict[str, GithubIssuesProvider] = {}
    merged_tickets: list[ExternalTicketRef] = []
    for ticket in existing_tickets:
        if ticket.provider != "github" or ticket.direction != "exported":
            merged_tickets.append(ticket)
            continue
        if ticket.state == "closed":
            merged_tickets.append(ticket)
            continue
        stale += 1
        action = _close_action_for_ticket(ticket)
        if action == "none":
            merged_tickets.append(ticket)
            continue
        repo_slug = _github_repo_from_ticket_url(ticket.url)
        if not repo_slug:
            notes.append(
                f"github:{ticket.ticket_id} missing repo slug; "
                "cannot reconcile exported ticket state"
            )
            merged_tickets.append(ticket)
            continue
        provider = provider_cache.get(repo_slug)
        if provider is None:
            provider = GithubIssuesProvider(repo=repo_slug)
            provider_cache[repo_slug] = provider
        close_comment = None
        if ticket.on_close == "comment":
            close_comment = f"Closing external ticket because local bead {issue_id} is closed."
        try:
            if action == "close":
                refreshed = provider.close_ticket(ticket, comment=close_comment)
                merged = _merge_ticket_state(ticket, refreshed, assume_closed=True)
            else:
                refreshed = provider.sync_state(ticket)
                merged = _merge_ticket_state(ticket, refreshed, assume_closed=False)
        except RuntimeError as exc:
            notes.append(f"github:{ticket.ticket_id} {exc}")
            merged_tickets.append(ticket)
            continue
        merged_tickets.append(merged)
        reconciled += 1
        if merged != ticket:
            updated = True

    if updated:
        update_external_tickets(issue_id, merged_tickets, beads_root=beads_root, cwd=cwd)

    unique_notes: list[str] = []
    seen_notes: set[str] = set()
    for note in notes:
        if note in seen_notes:
            continue
        seen_notes.add(note)
        unique_notes.append(note)
        _append_external_close_note(issue_id, note, beads_root=beads_root, cwd=cwd)

    return ExternalTicketReconcileResult(
        issue_id=issue_id,
        stale_exported_github_tickets=stale,
        reconciled_tickets=reconciled,
        updated=updated,
        needs_decision_notes=tuple(unique_notes),
    )


def merge_description_preserving_metadata(
    existing_description: str | None,
    next_description: str | None,
    *,
    preserved_keys: tuple[str, ...] = PRESERVED_DESCRIPTION_KEYS,
) -> str:
    """Merge a replacement description while preserving metadata fields."""
    merged = _normalize_description(next_description)
    existing_fields = _parse_description_fields(existing_description)
    for key in preserved_keys:
        if key not in existing_fields:
            continue
        merged = _update_description_field(merged, key=key, value=existing_fields[key])
    return merged


def _external_providers_from_labels(labels: set[str]) -> tuple[str, ...]:
    providers = sorted(
        {
            label[len("ext:") :].strip()
            for label in labels
            if label.startswith("ext:") and label not in {"ext:no-export", "ext:skip-export"}
        }
    )
    return tuple(provider for provider in providers if provider)


def list_external_ticket_metadata_gaps(
    *,
    beads_root: Path,
    cwd: Path,
    issue_ids: list[str] | None = None,
) -> list[ExternalTicketMetadataGap]:
    """List issues with ext:* labels but missing external_tickets metadata."""
    if issue_ids:
        issues: list[dict[str, object]] = []
        for issue_id in issue_ids:
            issues.extend(run_bd_json(["show", issue_id], beads_root=beads_root, cwd=cwd))
    else:
        issues = run_bd_json(["list", "--all"], beads_root=beads_root, cwd=cwd)

    gaps: list[ExternalTicketMetadataGap] = []
    for issue in issues:
        issue_id = issue.get("id")
        if not isinstance(issue_id, str) or not issue_id.strip():
            continue
        providers = _external_providers_from_labels(_issue_labels(issue))
        if not providers:
            continue
        description = issue.get("description")
        if parse_external_tickets(description if isinstance(description, str) else None):
            continue
        gaps.append(ExternalTicketMetadataGap(issue_id=issue_id.strip(), providers=providers))
    return sorted(gaps, key=lambda gap: gap.issue_id)


def _description_from_event_payload(payload: object) -> str | None:
    if not isinstance(payload, str) or not payload.strip():
        return None
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    description = parsed.get("description")
    return description if isinstance(description, str) else None


def recover_external_tickets_from_history(
    issue_id: str,
    *,
    beads_root: Path,
) -> list[ExternalTicketRef]:
    """Recover external ticket metadata from Beads event history."""
    db_path = beads_root / "beads.db"
    if not db_path.exists():
        return []
    try:
        with sqlite3.connect(db_path) as connection:
            rows = connection.execute(
                """
                SELECT old_value, new_value
                FROM events
                WHERE issue_id = ?
                  AND event_type = 'updated'
                ORDER BY id DESC
                """,
                (issue_id,),
            )
            for old_value, new_value in rows:
                for candidate in (new_value, old_value):
                    description = _description_from_event_payload(candidate)
                    if not description:
                        continue
                    tickets = parse_external_tickets(description)
                    if tickets:
                        return tickets
    except sqlite3.Error:
        return []
    return []


def repair_external_ticket_metadata_from_history(
    *,
    beads_root: Path,
    cwd: Path,
    issue_ids: list[str] | None = None,
    apply: bool = False,
) -> list[ExternalTicketMetadataRepairResult]:
    """Recover dropped external_tickets metadata from event history."""
    results: list[ExternalTicketMetadataRepairResult] = []
    gaps = list_external_ticket_metadata_gaps(
        beads_root=beads_root,
        cwd=cwd,
        issue_ids=issue_ids,
    )
    for gap in gaps:
        tickets = recover_external_tickets_from_history(gap.issue_id, beads_root=beads_root)
        recovered = bool(tickets)
        repaired = False
        if recovered and apply:
            update_external_tickets(gap.issue_id, tickets, beads_root=beads_root, cwd=cwd)
            repaired = True
        results.append(
            ExternalTicketMetadataRepairResult(
                issue_id=gap.issue_id,
                providers=gap.providers,
                recovered=recovered,
                repaired=repaired,
                ticket_count=len(tickets),
            )
        )
    return results


def list_epics_by_workspace_label(
    root_branch: str, *, beads_root: Path, cwd: Path
) -> list[dict[str, object]]:
    """List epic beads with the workspace label."""
    return run_bd_json(
        ["list", "--label", "at:epic", "--label", workspace_label(root_branch)],
        beads_root=beads_root,
        cwd=cwd,
    )


def find_epics_by_root_branch(
    root_branch: str, *, beads_root: Path, cwd: Path
) -> list[dict[str, object]]:
    """Find epic beads by root branch label or description."""
    issues = list_epics_by_workspace_label(root_branch, beads_root=beads_root, cwd=cwd)
    if issues:
        return issues
    issues = run_bd_json(
        ["list", "--label", "at:epic"],
        beads_root=beads_root,
        cwd=cwd,
    )
    return [issue for issue in issues if extract_workspace_root_branch(issue) == root_branch]


def update_workspace_root_branch(
    epic_id: str,
    root_branch: str,
    *,
    beads_root: Path,
    cwd: Path,
    allow_override: bool = False,
) -> dict[str, object]:
    """Update the workspace root branch field + label for an epic."""
    issues = run_bd_json(["show", epic_id], beads_root=beads_root, cwd=cwd)
    if not issues:
        die(f"epic not found: {epic_id}")
    issue = issues[0]
    current = extract_workspace_root_branch(issue)
    if current and current != root_branch and not allow_override:
        die("workspace root branch already set; override not permitted")

    description = issue.get("description")
    updated = _update_description_field(
        description if isinstance(description, str) else "",
        key="workspace.root_branch",
        value=root_branch,
    )
    label = workspace_label(root_branch)
    labels = sorted(_issue_labels(issue))
    remove_labels = [
        existing for existing in labels if existing.startswith("workspace:") and existing != label
    ]

    if label not in labels or remove_labels:
        args = ["update", epic_id]
        if label not in labels:
            args.extend(["--add-label", label])
        for existing in remove_labels:
            args.extend(["--remove-label", existing])
        run_bd_command(args, beads_root=beads_root, cwd=cwd)

    _update_issue_description(epic_id, updated, beads_root=beads_root, cwd=cwd)
    refreshed = run_bd_json(["show", epic_id], beads_root=beads_root, cwd=cwd)
    return refreshed[0] if refreshed else issue


def update_workspace_parent_branch(
    epic_id: str,
    parent_branch: str,
    *,
    beads_root: Path,
    cwd: Path,
    allow_override: bool = False,
) -> dict[str, object]:
    """Update the workspace parent branch field for an epic."""
    if not parent_branch:
        die("parent branch must not be empty")
    issues = run_bd_json(["show", epic_id], beads_root=beads_root, cwd=cwd)
    if not issues:
        die(f"epic not found: {epic_id}")
    issue = issues[0]
    description = issue.get("description")
    fields = _parse_description_fields(description if isinstance(description, str) else "")
    current = fields.get("workspace.parent_branch")
    if current and current.lower() != "null" and current != parent_branch:
        if not allow_override:
            die("workspace parent branch already set; override not permitted")
    if current == parent_branch:
        return issue
    updated = _update_description_field(
        description if isinstance(description, str) else "",
        key="workspace.parent_branch",
        value=parent_branch,
    )
    _update_issue_description(epic_id, updated, beads_root=beads_root, cwd=cwd)
    refreshed = run_bd_json(["show", epic_id], beads_root=beads_root, cwd=cwd)
    return refreshed[0] if refreshed else issue


def update_worktree_path(
    epic_id: str,
    worktree_path: str,
    *,
    beads_root: Path,
    cwd: Path,
    allow_override: bool = False,
) -> dict[str, object]:
    """Update the worktree_path field for an epic."""
    issues = run_bd_json(["show", epic_id], beads_root=beads_root, cwd=cwd)
    if not issues:
        die(f"epic not found: {epic_id}")
    issue = issues[0]
    current = extract_worktree_path(issue)
    if current and current != worktree_path and not allow_override:
        die("worktree path already set; override not permitted")
    description = issue.get("description")
    updated = _update_description_field(
        description if isinstance(description, str) else "",
        key="worktree_path",
        value=worktree_path,
    )
    _update_issue_description(epic_id, updated, beads_root=beads_root, cwd=cwd)
    refreshed = run_bd_json(["show", epic_id], beads_root=beads_root, cwd=cwd)
    return refreshed[0] if refreshed else issue


def update_changeset_branch_metadata(
    changeset_id: str,
    *,
    root_branch: str | None,
    parent_branch: str | None,
    work_branch: str | None,
    root_base: str | None = None,
    parent_base: str | None = None,
    beads_root: Path,
    cwd: Path,
    allow_override: bool = False,
) -> dict[str, object]:
    """Update branch lineage metadata fields for a changeset."""
    issues = run_bd_json(["show", changeset_id], beads_root=beads_root, cwd=cwd)
    if not issues:
        die(f"changeset not found: {changeset_id}")
    issue = issues[0]
    description = issue.get("description")
    fields = _parse_description_fields(description if isinstance(description, str) else "")

    def normalize(value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned or cleaned.lower() == "null":
            return None
        return cleaned

    updated = description if isinstance(description, str) else ""
    changed = False

    def apply(key: str, value: str | None) -> None:
        nonlocal updated, changed
        normalized = normalize(value)
        if normalized is None:
            return
        current = normalize(fields.get(key))
        if current and current != normalized and not allow_override:
            if key in {"changeset.root_base", "changeset.parent_base"}:
                # Preserve originally recorded lineage bases on subsequent
                # worker runs unless an explicit override was requested.
                return
            die(f"{key} already set; override not permitted")
        if current == normalized:
            return
        updated = _update_description_field(updated, key=key, value=normalized)
        changed = True

    apply("changeset.root_branch", root_branch)
    apply("changeset.parent_branch", parent_branch)
    apply("changeset.work_branch", work_branch)
    apply("changeset.root_base", root_base)
    apply("changeset.parent_base", parent_base)

    if changed:
        _update_issue_description(changeset_id, updated, beads_root=beads_root, cwd=cwd)
        refreshed = run_bd_json(["show", changeset_id], beads_root=beads_root, cwd=cwd)
        return refreshed[0] if refreshed else issue
    return issue


def update_external_tickets(
    issue_id: str,
    tickets: list[ExternalTicketRef],
    *,
    beads_root: Path,
    cwd: Path,
) -> dict[str, object]:
    """Update external ticket references and labels on a bead."""
    issues = run_bd_json(["show", issue_id], beads_root=beads_root, cwd=cwd)
    if not issues:
        die(f"issue not found: {issue_id}")
    issue = issues[0]
    payload = [external_ticket_payload(ticket) for ticket in tickets]
    serialized = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    description = issue.get("description")
    updated = _update_description_field(
        description if isinstance(description, str) else "",
        key=EXTERNAL_TICKETS_KEY,
        value=serialized,
    )

    desired_labels = {external_label(ticket.provider) for ticket in tickets}
    labels = sorted(_issue_labels(issue))
    remove_labels = [
        label for label in labels if label.startswith("ext:") and label not in desired_labels
    ]
    add_labels = [label for label in desired_labels if label not in labels]
    if add_labels or remove_labels:
        args = ["update", issue_id]
        for label in add_labels:
            args.extend(["--add-label", label])
        for label in remove_labels:
            args.extend(["--remove-label", label])
        run_bd_command(args, beads_root=beads_root, cwd=cwd)

    _update_issue_description(issue_id, updated, beads_root=beads_root, cwd=cwd)
    refreshed = run_bd_json(["show", issue_id], beads_root=beads_root, cwd=cwd)
    return refreshed[0] if refreshed else issue


def clear_agent_hook(
    agent_bead_id: str,
    *,
    beads_root: Path,
    cwd: Path,
) -> None:
    """Clear the hooked epic id on the agent bead description."""
    issues = run_bd_json(["show", agent_bead_id], beads_root=beads_root, cwd=cwd)
    if not issues:
        die(f"agent bead not found: {agent_bead_id}")
    run_bd_command(
        ["slot", "clear", agent_bead_id, HOOK_SLOT_NAME],
        beads_root=beads_root,
        cwd=cwd,
        allow_failure=True,
    )
    issue = issues[0]
    description = issue.get("description")
    updated = _update_description_field(
        description if isinstance(description, str) else "",
        key="hook_bead",
        value=None,
    )
    _update_issue_description(agent_bead_id, updated, beads_root=beads_root, cwd=cwd)


def list_policy_beads(role: str | None, *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:
    """List project policy beads for the given role."""
    args = ["list", "--label", POLICY_LABEL, "--label", POLICY_SCOPE_LABEL]
    if role:
        args.extend(["--label", policy_role_label(role)])
    return run_bd_json(args, beads_root=beads_root, cwd=cwd)


def extract_policy_body(issue: dict[str, object]) -> str:
    """Extract the policy body from a bead."""
    description = issue.get("description")
    if isinstance(description, str):
        return description.rstrip("\n")
    return ""


def create_policy_bead(
    role: str,
    body: str,
    *,
    beads_root: Path,
    cwd: Path,
) -> str:
    """Create a project policy bead for the role and return its id."""
    title = f"Project policy ({role})"
    with NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
        handle.write(body.rstrip("\n") + "\n" if body else "")
        temp_path = Path(handle.name)
    try:
        labels = ",".join([POLICY_LABEL, POLICY_SCOPE_LABEL, policy_role_label(role)])
        args = [
            "create",
            "--type",
            "policy",
            "--labels",
            labels,
            "--title",
            title,
            "--body-file",
            str(temp_path),
            "--silent",
        ]
        result = run_bd_command(args, beads_root=beads_root, cwd=cwd)
    finally:
        temp_path.unlink(missing_ok=True)
    issue_id = result.stdout.strip() if result.stdout else ""
    if not issue_id:
        die("failed to create policy bead")
    return issue_id


def update_policy_bead(
    issue_id: str,
    body: str,
    *,
    beads_root: Path,
    cwd: Path,
) -> None:
    """Update a project policy bead body."""
    _update_issue_description(issue_id, body, beads_root=beads_root, cwd=cwd)


def _update_description_field(description: str | None, *, key: str, value: str | None) -> str:
    target = _normalize_description(description)
    lines = target.splitlines() if target else []
    updated: list[str] = []
    needle = f"{key}:"
    found = False
    for line in lines:
        if line.strip().startswith(needle):
            if not found:
                replacement = value if value is not None else "null"
                updated.append(f"{key}: {replacement}")
                found = True
            continue
        updated.append(line)
    if not found:
        replacement = value if value is not None else "null"
        updated.append(f"{key}: {replacement}")
    return "\n".join(updated).rstrip("\n") + "\n"


def _update_issue_description(
    issue_id: str,
    description: str,
    *,
    beads_root: Path,
    cwd: Path,
) -> None:
    with NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
        handle.write(description)
        temp_path = Path(handle.name)
    try:
        run_bd_command(
            ["update", issue_id, "--body-file", str(temp_path)],
            beads_root=beads_root,
            cwd=cwd,
        )
    finally:
        temp_path.unlink(missing_ok=True)


def _create_issue_with_body(
    args: list[str],
    description: str,
    *,
    beads_root: Path,
    cwd: Path,
) -> str:
    with NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
        handle.write(description)
        temp_path = Path(handle.name)
    try:
        result = run_bd_command(
            [*args, "--body-file", str(temp_path), "--silent"],
            beads_root=beads_root,
            cwd=cwd,
        )
    finally:
        temp_path.unlink(missing_ok=True)
    issue_id = result.stdout.strip() if result.stdout else ""
    if not issue_id:
        die("failed to create bead")
    return issue_id


def find_agent_bead(agent_id: str, *, beads_root: Path, cwd: Path) -> dict[str, object] | None:
    """Find an agent bead by agent identity."""
    issues = run_bd_json(
        ["list", "--label", "at:agent", "--title", agent_id],
        beads_root=beads_root,
        cwd=cwd,
    )
    for issue in issues:
        title = issue.get("title")
        if isinstance(title, str) and title == agent_id:
            return issue
    for issue in issues:
        description = issue.get("description")
        fields = _parse_description_fields(description if isinstance(description, str) else "")
        if fields.get("agent_id") == agent_id:
            return issue
    return None


def ensure_agent_bead(
    agent_id: str,
    *,
    beads_root: Path,
    cwd: Path,
    role: str | None = None,
) -> dict[str, object]:
    """Ensure an agent bead exists for the given identity."""
    existing = find_agent_bead(agent_id, beads_root=beads_root, cwd=cwd)
    if existing:
        return existing
    description = f"agent_id: {agent_id}\n"
    if role:
        description += f"role_type: {role}\n"
    issue_type = _agent_issue_type(beads_root=beads_root, cwd=cwd)
    result = run_bd_command(
        [
            "create",
            "--type",
            issue_type,
            "--labels",
            "at:agent",
            "--title",
            agent_id,
            "--description",
            description,
            "--silent",
        ],
        beads_root=beads_root,
        cwd=cwd,
    )
    issue_id = result.stdout.strip() if result.stdout else ""
    if not issue_id:
        die("failed to create agent bead")
    issues = run_bd_json(["show", issue_id], beads_root=beads_root, cwd=cwd)
    if issues:
        return issues[0]
    return {"id": issue_id, "title": agent_id}


def claim_epic(
    epic_id: str,
    agent_id: str,
    *,
    beads_root: Path,
    cwd: Path,
    allow_takeover_from: str | None = None,
) -> dict[str, object]:
    """Claim an epic by assigning it to the agent."""
    issues = run_bd_json(["show", epic_id], beads_root=beads_root, cwd=cwd)
    if not issues:
        die(f"epic not found: {epic_id}")
    issue = issues[0]
    labels = _issue_labels(issue)
    executable_labels = {"at:epic", "at:changeset"} & labels
    if executable_labels and "at:draft" in labels:
        die(
            f"epic {epic_id} carries legacy at:draft label; "
            "remove at:draft and rely on at:ready for executable readiness"
        )
    if executable_labels and "at:ready" not in labels:
        die(f"epic {epic_id} is not marked at:ready")
    if executable_labels and _is_planner_assignee(agent_id):
        die(
            f"epic {epic_id} claim rejected for planner {agent_id}; "
            "planner agents cannot claim executable work"
        )
    existing_assignee = issue.get("assignee")
    if _is_planner_assignee(existing_assignee) and executable_labels:
        die(
            f"epic {epic_id} is assigned to planner {existing_assignee}; "
            "planner agents cannot own executable work"
        )
    if (
        existing_assignee
        and existing_assignee != agent_id
        and existing_assignee != allow_takeover_from
    ):
        die(f"epic {epic_id} already has an assignee")
    update_args = [
        "update",
        epic_id,
        "--assignee",
        agent_id,
        "--status",
        "hooked",
        "--add-label",
        "at:hooked",
    ]
    if _is_standalone_changeset_without_epic_label(issue):
        update_args.extend(["--add-label", "at:epic"])
    run_bd_command(
        update_args,
        beads_root=beads_root,
        cwd=cwd,
    )
    refreshed = run_bd_json(["show", epic_id], beads_root=beads_root, cwd=cwd)
    if refreshed:
        updated = refreshed[0]
        assignee = updated.get("assignee")
        if assignee != agent_id:
            die(f"epic {epic_id} claim failed; already assigned")
        return updated
    return issue


def epic_changeset_summary(
    epic_id: str,
    *,
    beads_root: Path,
    cwd: Path,
) -> ChangesetSummary:
    """Summarize changesets under an epic."""
    changesets = list_descendant_changesets(
        epic_id,
        beads_root=beads_root,
        cwd=cwd,
        include_closed=True,
    )
    return summarize_changesets(changesets)


def close_epic_if_complete(
    epic_id: str,
    agent_bead_id: str | None,
    *,
    beads_root: Path,
    cwd: Path,
    confirm: Callable[[ChangesetSummary], bool] | None = None,
) -> bool:
    """Close an epic and clear hook if all changesets are complete."""
    issues = run_bd_json(["show", epic_id], beads_root=beads_root, cwd=cwd)
    if not issues:
        return False
    issue = issues[0]
    labels = _issue_labels(issue)
    is_standalone_changeset = "at:changeset" in labels and (
        "cs:merged" in labels or "cs:abandoned" in labels
    )
    summary = epic_changeset_summary(epic_id, beads_root=beads_root, cwd=cwd)
    if not is_standalone_changeset and not summary.ready_to_close:
        return False
    if confirm is not None and not confirm(summary):
        return False
    close_issue(
        epic_id,
        beads_root=beads_root,
        cwd=cwd,
    )
    if agent_bead_id:
        clear_agent_hook(agent_bead_id, beads_root=beads_root, cwd=cwd)
    return True


def set_agent_hook(
    agent_bead_id: str,
    epic_id: str,
    *,
    beads_root: Path,
    cwd: Path,
) -> None:
    """Store the hooked epic id on the agent bead description."""
    issues = run_bd_json(["show", agent_bead_id], beads_root=beads_root, cwd=cwd)
    if not issues:
        die(f"agent bead not found: {agent_bead_id}")
    run_bd_command(
        ["slot", "set", agent_bead_id, HOOK_SLOT_NAME, epic_id],
        beads_root=beads_root,
        cwd=cwd,
        allow_failure=True,
    )
    issue = issues[0]
    description = issue.get("description")
    updated = _update_description_field(
        description if isinstance(description, str) else "",
        key="hook_bead",
        value=epic_id,
    )
    _update_issue_description(agent_bead_id, updated, beads_root=beads_root, cwd=cwd)


def create_message_bead(
    *,
    subject: str,
    body: str,
    metadata: dict[str, object],
    assignee: str | None = None,
    beads_root: Path,
    cwd: Path,
) -> dict[str, object]:
    """Create a message bead and return its data."""
    description = messages.render_message(metadata, body)
    args = [
        "create",
        "--type",
        "task",
        "--labels",
        "at:message,at:unread",
        "--title",
        subject,
    ]
    if assignee:
        args.extend(["--assignee", assignee])
    issue_id = _create_issue_with_body(args, description, beads_root=beads_root, cwd=cwd)
    issues = run_bd_json(["show", issue_id], beads_root=beads_root, cwd=cwd)
    return issues[0] if issues else {"id": issue_id, "title": subject}


def list_inbox_messages(
    agent_id: str,
    *,
    beads_root: Path,
    cwd: Path,
    unread_only: bool = True,
) -> list[dict[str, object]]:
    """List message beads assigned to the agent."""
    args = ["list", "--label", "at:message", "--assignee", agent_id]
    if unread_only:
        args.extend(["--label", "at:unread"])
    return run_bd_json(args, beads_root=beads_root, cwd=cwd)


def list_queue_messages(
    *,
    beads_root: Path,
    cwd: Path,
    queue: str | None = None,
    unclaimed_only: bool = True,
    unread_only: bool = True,
) -> list[dict[str, object]]:
    """List queued message beads, optionally filtered by queue name."""
    args = ["list", "--label", "at:message"]
    if unread_only:
        args.extend(["--label", "at:unread"])
    issues = run_bd_json(args, beads_root=beads_root, cwd=cwd)
    matches: list[dict[str, object]] = []
    for issue in issues:
        description = issue.get("description")
        if not isinstance(description, str):
            continue
        payload = messages.parse_message(description)
        queue_name = payload.metadata.get("queue")
        if not isinstance(queue_name, str) or not queue_name.strip():
            continue
        if queue is not None and queue_name != queue:
            continue
        claimed_by = payload.metadata.get("claimed_by")
        if unclaimed_only and isinstance(claimed_by, str) and claimed_by.strip():
            continue
        enriched = dict(issue)
        enriched["queue"] = queue_name
        enriched["claimed_by"] = claimed_by
        matches.append(enriched)
    return matches


def claim_queue_message(
    message_id: str,
    agent_id: str,
    *,
    beads_root: Path,
    cwd: Path,
    queue: str | None = None,
) -> dict[str, object]:
    """Claim a queued message bead by setting claimed metadata."""
    issues = run_bd_json(["show", message_id], beads_root=beads_root, cwd=cwd)
    if not issues:
        die(f"message not found: {message_id}")
    issue = issues[0]
    description = issue.get("description")
    payload = messages.parse_message(description if isinstance(description, str) else "")
    queue_name = payload.metadata.get("queue")
    if not isinstance(queue_name, str) or not queue_name.strip():
        die(f"message {message_id} is not in a queue")
    if queue is not None and queue_name != queue:
        die(f"message {message_id} is not in queue {queue!r}")
    claimed_by = payload.metadata.get("claimed_by")
    if isinstance(claimed_by, str) and claimed_by.strip():
        die(f"message {message_id} already claimed by {claimed_by}")
    payload.metadata["claimed_by"] = agent_id
    payload.metadata["claimed_at"] = dt.datetime.now(tz=dt.timezone.utc).isoformat()
    updated = messages.render_message(payload.metadata, payload.body)
    _update_issue_description(message_id, updated, beads_root=beads_root, cwd=cwd)
    refreshed = run_bd_json(["show", message_id], beads_root=beads_root, cwd=cwd)
    return refreshed[0] if refreshed else issue


def mark_message_read(
    message_id: str,
    *,
    beads_root: Path,
    cwd: Path,
) -> None:
    """Mark a message bead as read."""
    run_bd_command(
        ["update", message_id, "--remove-label", "at:unread"],
        beads_root=beads_root,
        cwd=cwd,
    )


def update_changeset_integrated_sha(
    changeset_id: str,
    integrated_sha: str,
    *,
    beads_root: Path,
    cwd: Path,
    allow_override: bool = False,
) -> dict[str, object]:
    """Update the integrated SHA field for a changeset bead."""
    if not integrated_sha:
        die("integrated sha must not be empty")
    issues = run_bd_json(["show", changeset_id], beads_root=beads_root, cwd=cwd)
    if not issues:
        die(f"changeset not found: {changeset_id}")
    issue = issues[0]
    description = issue.get("description")
    fields = _parse_description_fields(description if isinstance(description, str) else "")
    current = fields.get("changeset.integrated_sha")
    if current and current.lower() != "null" and current != integrated_sha:
        if not allow_override:
            die("changeset integrated sha already set; override not permitted")
    if current == integrated_sha:
        return issue
    updated = _update_description_field(
        description if isinstance(description, str) else "",
        key="changeset.integrated_sha",
        value=integrated_sha,
    )
    _update_issue_description(changeset_id, updated, beads_root=beads_root, cwd=cwd)
    refreshed = run_bd_json(["show", changeset_id], beads_root=beads_root, cwd=cwd)
    return refreshed[0] if refreshed else issue


def update_changeset_review(
    changeset_id: str,
    metadata: changesets.ReviewMetadata,
    *,
    beads_root: Path,
    cwd: Path,
) -> None:
    """Update review metadata fields for a changeset bead."""
    issues = run_bd_json(["show", changeset_id], beads_root=beads_root, cwd=cwd)
    if not issues:
        die(f"changeset not found: {changeset_id}")
    issue = issues[0]
    description = issue.get("description")
    updated = changesets.apply_review_metadata(
        description if isinstance(description, str) else "",
        metadata,
    )
    _update_issue_description(changeset_id, updated, beads_root=beads_root, cwd=cwd)


def update_changeset_review_feedback_cursor(
    changeset_id: str,
    latest_feedback_at: str,
    *,
    beads_root: Path,
    cwd: Path,
) -> None:
    """Persist the latest handled review feedback timestamp on a changeset."""
    issues = run_bd_json(["show", changeset_id], beads_root=beads_root, cwd=cwd)
    if not issues:
        die(f"changeset not found: {changeset_id}")
    issue = issues[0]
    description = issue.get("description")
    updated = _update_description_field(
        description if isinstance(description, str) else "",
        key="review.last_feedback_seen_at",
        value=latest_feedback_at,
    )
    _update_issue_description(changeset_id, updated, beads_root=beads_root, cwd=cwd)

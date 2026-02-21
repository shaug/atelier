"""Shared worker runtime helper functions for `atelier work`."""

from __future__ import annotations

import datetime as dt
import os
from collections.abc import Callable

from .. import beads, lifecycle
from .. import log as atelier_log
from ..io import die, say
from ..worker import selection as worker_selection
from ..worker import telemetry as worker_telemetry
from ..worker.models import WorkerRunSummary
from ..worker.models_boundary import parse_issue_boundary

_MODE_VALUES = {"prompt", "auto"}

_RUN_MODE_VALUES = {"once", "default", "watch"}

_WATCH_INTERVAL_SECONDS = 60


def _normalize_branch_value(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned or cleaned.lower() == "null":
        return None
    return cleaned


def _extract_changeset_root_branch(issue: dict[str, object]) -> str | None:
    description = issue.get("description")
    fields = beads.parse_description_fields(description if isinstance(description, str) else "")
    return _normalize_branch_value(fields.get("changeset.root_branch"))


def _extract_workspace_parent_branch(issue: dict[str, object]) -> str | None:
    description = issue.get("description")
    fields = beads.parse_description_fields(description if isinstance(description, str) else "")
    return _normalize_branch_value(fields.get("workspace.parent_branch"))


def _issue_parent_id(issue: dict[str, object]) -> str | None:
    boundary = parse_issue_boundary(issue, source="_issue_parent_id")
    return boundary.parent_id


def _issue_dependency_ids(issue: dict[str, object]) -> tuple[str, ...]:
    boundary = parse_issue_boundary(issue, source="_issue_dependency_ids")
    return boundary.dependency_ids


def _dry_run_log(message: str) -> None:
    say(f"DRY-RUN: {message}")


def _log_debug(message: str) -> None:
    atelier_log.debug(f"[work] {message}")


def _trace_enabled() -> bool:
    return worker_telemetry.trace_enabled("ATELIER_WORK_TRACE")


def _step(label: str, *, timings: list[tuple[str, float]], trace: bool) -> Callable:
    return worker_telemetry.step(label, timings=timings, trace=trace, say=say, log_debug=_log_debug)


def _report_timings(timings: list[tuple[str, float]], *, trace: bool) -> None:
    worker_telemetry.report_timings(timings, trace=trace, say=say)


def _report_worker_summary(summary: WorkerRunSummary, *, dry_run: bool) -> None:
    worker_telemetry.report_worker_summary(summary, dry_run=dry_run, say=say, log_debug=_log_debug)


def _with_codex_exec(cmd: list[str], opening_prompt: str) -> list[str]:
    """Return a codex command rewritten to run non-interactively via `exec`."""
    if not cmd:
        return cmd
    rewritten = list(cmd)
    if opening_prompt and rewritten[-1] == opening_prompt:
        return [*rewritten[:-1], "exec", opening_prompt]
    rewritten.append("exec")
    if opening_prompt:
        rewritten.append(opening_prompt)
    return rewritten


def _strip_flag_with_value(args: list[str], flag: str) -> list[str]:
    """Return args without instances of `flag` and its value."""
    cleaned: list[str] = []
    skip_next = False
    for token in args:
        if skip_next:
            skip_next = False
            continue
        if token == flag:
            skip_next = True
            continue
        if token.startswith(f"{flag}="):
            continue
        cleaned.append(token)
    return cleaned


def _ensure_exec_subcommand_flag(args: list[str], flag: str) -> list[str]:
    """Ensure a flag is present on the codex `exec` subcommand."""
    rewritten = list(args)
    try:
        exec_index = rewritten.index("exec")
    except ValueError:
        return rewritten
    prompt_start = len(rewritten)
    if exec_index + 1 < len(rewritten):
        prompt_start = exec_index + 1
        for index in range(exec_index + 1, len(rewritten)):
            token = rewritten[index]
            if token.startswith("-"):
                continue
            prompt_start = index
            break
    existing = rewritten[exec_index + 1 : prompt_start]
    if flag in existing:
        return rewritten
    rewritten.insert(exec_index + 1, flag)
    return rewritten


def _normalize_mode(value: str | None) -> str:
    if value is None:
        value = os.environ.get("ATELIER_MODE", "prompt")
    normalized = value.strip().lower()
    if normalized not in _MODE_VALUES:
        die("mode must be one of: prompt, auto")
    return normalized


def _normalize_run_mode(value: str | None) -> str:
    if value is None:
        value = os.environ.get("ATELIER_RUN_MODE", "default")
    normalized = value.strip().lower()
    if normalized not in _RUN_MODE_VALUES:
        die("run mode must be one of: once, default, watch")
    return normalized


def _watch_interval_seconds() -> int:
    raw = os.environ.get("ATELIER_WATCH_INTERVAL", "").strip()
    if not raw:
        return _WATCH_INTERVAL_SECONDS
    try:
        value = int(raw)
    except ValueError:
        die("ATELIER_WATCH_INTERVAL must be an integer number of seconds")
    if value <= 0:
        die("ATELIER_WATCH_INTERVAL must be a positive number of seconds")
    return value


def _issue_labels(issue: dict[str, object]) -> set[str]:
    boundary = parse_issue_boundary(issue, source="_issue_labels")
    return set(boundary.labels)


def _filter_epics(
    issues: list[dict[str, object]],
    *,
    assignee: str | None = None,
    require_unassigned: bool = False,
) -> list[dict[str, object]]:
    return worker_selection.filter_epics(
        issues,
        assignee=assignee,
        require_unassigned=require_unassigned,
        allow_hooked=assignee is not None,
        skip_draft=True,
    )


def _parse_issue_time(value: object) -> dt.datetime | None:
    return worker_selection.parse_issue_time(value)


def _is_closed_status(status: object) -> bool:
    return lifecycle.is_closed_status(status)


def _is_feedback_eligible_epic_status(status: object) -> bool:
    return not _is_closed_status(status)


normalize_branch_value = _normalize_branch_value
extract_changeset_root_branch = _extract_changeset_root_branch
extract_workspace_parent_branch = _extract_workspace_parent_branch
issue_parent_id = _issue_parent_id
issue_dependency_ids = _issue_dependency_ids
dry_run_log = _dry_run_log
log_debug = _log_debug
trace_enabled = _trace_enabled
step = _step
report_timings = _report_timings
report_worker_summary = _report_worker_summary
with_codex_exec = _with_codex_exec
strip_flag_with_value = _strip_flag_with_value
ensure_exec_subcommand_flag = _ensure_exec_subcommand_flag
normalize_mode = _normalize_mode
normalize_run_mode = _normalize_run_mode
watch_interval_seconds = _watch_interval_seconds
issue_labels = _issue_labels
filter_epics = _filter_epics
parse_issue_time = _parse_issue_time
is_closed_status = _is_closed_status
is_feedback_eligible_epic_status = _is_feedback_eligible_epic_status

__all__ = [
    "dry_run_log",
    "ensure_exec_subcommand_flag",
    "extract_changeset_root_branch",
    "extract_workspace_parent_branch",
    "filter_epics",
    "is_closed_status",
    "is_feedback_eligible_epic_status",
    "issue_dependency_ids",
    "issue_labels",
    "issue_parent_id",
    "log_debug",
    "normalize_branch_value",
    "normalize_mode",
    "normalize_run_mode",
    "parse_issue_time",
    "report_timings",
    "report_worker_summary",
    "step",
    "strip_flag_with_value",
    "trace_enabled",
    "watch_interval_seconds",
    "with_codex_exec",
]

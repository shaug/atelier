"""Shared worker runtime helper functions for `atelier work`."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable

from .. import beads, cli_defaults, lifecycle
from .. import log as atelier_log
from ..io import die, say
from ..worker import selection as worker_selection
from ..worker import telemetry as worker_telemetry
from ..worker.models import WorkerRunSummary
from ..worker.models_boundary import parse_issue_boundary

_MODE_VALUES = {"prompt", "auto"}

_RUN_MODE_VALUES = {"once", "default", "watch"}

_TRANSLATED_DEFAULT_MESSAGES_EMITTED: set[str] = set()


def normalize_branch_value(value: object) -> str | None:
    """Normalize a branch metadata value.

    Args:
        value: Raw branch metadata value from a bead field.

    Returns:
        A trimmed branch string, or ``None`` when empty/``null``.
    """
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned or cleaned.lower() == "null":
        return None
    return cleaned


def extract_changeset_root_branch(issue: dict[str, object]) -> str | None:
    """Extract changeset root branch metadata from an issue payload.

    Args:
        issue: Bead issue payload.

    Returns:
        Normalized ``changeset.root_branch`` value, or ``None``.
    """
    description = issue.get("description")
    fields = beads.parse_description_fields(description if isinstance(description, str) else "")
    return normalize_branch_value(fields.get("changeset.root_branch"))


def extract_workspace_parent_branch(issue: dict[str, object]) -> str | None:
    """Extract workspace parent branch metadata from an issue payload.

    Args:
        issue: Bead issue payload.

    Returns:
        Normalized ``workspace.parent_branch`` value, or ``None``.
    """
    description = issue.get("description")
    fields = beads.parse_description_fields(description if isinstance(description, str) else "")
    return normalize_branch_value(fields.get("workspace.parent_branch"))


def issue_parent_id(issue: dict[str, object]) -> str | None:
    """Return parent issue identifier for a bead payload.

    Args:
        issue: Bead issue payload.

    Returns:
        Parent issue id when present, else ``None``.
    """
    boundary = parse_issue_boundary(issue, source="issue_parent_id")
    return boundary.parent_id


def issue_dependency_ids(issue: dict[str, object]) -> tuple[str, ...]:
    """Return dependency ids declared by an issue payload.

    Args:
        issue: Bead issue payload.

    Returns:
        Tuple of dependency issue ids.
    """
    boundary = parse_issue_boundary(issue, source="issue_dependency_ids")
    return boundary.dependency_ids


def dry_run_log(message: str) -> None:
    """Emit a dry-run log line.

    Args:
        message: Message body to print.

    Returns:
        None.
    """
    say(f"DRY-RUN: {message}")


def log_debug(message: str) -> None:
    """Emit worker-scoped debug logging.

    Args:
        message: Debug message payload.

    Returns:
        None.
    """
    atelier_log.debug(f"[work] {message}")


def report_translated_cli_default(value: cli_defaults.ResolvedCliDefault[object]) -> None:
    """Emit diagnostics when an env var translated a CLI default.

    Args:
        value: Resolved CLI default metadata.

    Returns:
        None.
    """
    if value.source != "env":
        return
    message = cli_defaults.describe_translated_default(value)
    if message in _TRANSLATED_DEFAULT_MESSAGES_EMITTED:
        return
    _TRANSLATED_DEFAULT_MESSAGES_EMITTED.add(message)
    log_debug(message)
    if trace_enabled():
        say(f"TRACE: {message}")


def trace_enabled() -> bool:
    """Return whether worker trace logging is enabled.

    Returns:
        ``True`` when worker tracing should emit step timings.
    """
    return worker_telemetry.trace_enabled("ATELIER_WORK_TRACE")


def step(label: str, *, timings: list[tuple[str, float]], trace: bool) -> Callable:
    """Create a telemetry step finalizer.

    Args:
        label: Human-readable step label.
        timings: Accumulator list for timing samples.
        trace: Whether trace mode is enabled.

    Returns:
        Callable that records step completion metadata.
    """
    return worker_telemetry.step(label, timings=timings, trace=trace, say=say, log_debug=log_debug)


def report_timings(timings: list[tuple[str, float]], *, trace: bool) -> None:
    """Emit timing summary for worker steps.

    Args:
        timings: Collected step timings.
        trace: Whether trace output is enabled.

    Returns:
        None.
    """
    worker_telemetry.report_timings(timings, trace=trace, say=say)


def report_worker_summary(summary: WorkerRunSummary, *, dry_run: bool) -> None:
    """Emit final worker session summary.

    Args:
        summary: Worker run summary payload.
        dry_run: Whether the run executed in dry-run mode.

    Returns:
        None.
    """
    worker_telemetry.report_worker_summary(summary, dry_run=dry_run, say=say, log_debug=log_debug)


def with_codex_exec(cmd: list[str], opening_prompt: str) -> list[str]:
    """Return codex args rewritten to run non-interactively via ``exec``.

    Args:
        cmd: Original command argument list.
        opening_prompt: Prompt payload passed to the agent process.

    Returns:
        Rewritten codex argument list using the ``exec`` subcommand.
    """
    if not cmd:
        return cmd
    rewritten = list(cmd)
    if opening_prompt and rewritten[-1] == opening_prompt:
        return [*rewritten[:-1], "exec", opening_prompt]
    rewritten.append("exec")
    if opening_prompt:
        rewritten.append(opening_prompt)
    return rewritten


def strip_flag_with_value(args: list[str], flag: str) -> list[str]:
    """Remove all occurrences of a flag and its value from argument tokens.

    Args:
        args: Raw command argument list.
        flag: Flag name to remove, such as ``--model``.

    Returns:
        Argument list with the requested flag removed.
    """
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


def ensure_exec_subcommand_flag(args: list[str], flag: str) -> list[str]:
    """Ensure a flag is present on the codex ``exec`` subcommand.

    Args:
        args: Raw codex command argument list.
        flag: Flag to inject into the ``exec`` flag section.

    Returns:
        Argument list with the requested exec-level flag included.
    """
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


def normalize_mode(value: str | None) -> str:
    """Normalize worker selection mode.

    Args:
        value: Optional explicit mode value.

    Returns:
        Normalized mode string.
    """
    resolved = cli_defaults.resolve_work_mode_default(value)
    report_translated_cli_default(resolved)
    normalized = resolved.value
    if normalized not in _MODE_VALUES:
        die("mode must be one of: prompt, auto")
    return normalized


def normalize_run_mode(value: str | None) -> str:
    """Normalize worker run mode.

    Args:
        value: Optional explicit run mode value.

    Returns:
        Normalized run mode string.
    """
    resolved = cli_defaults.resolve_work_run_mode_default(value)
    report_translated_cli_default(resolved)
    normalized = resolved.value
    if normalized not in _RUN_MODE_VALUES:
        die("run mode must be one of: once, default, watch")
    return normalized


def watch_interval_seconds() -> int:
    """Return watch-loop sleep interval in seconds.

    Returns:
        Positive watch interval in seconds.
    """
    resolved = cli_defaults.resolve_work_watch_interval_default()
    report_translated_cli_default(resolved)
    value = resolved.value
    if value <= 0:
        die("ATELIER_WATCH_INTERVAL must be a positive number of seconds")
    return value


def issue_labels(issue: dict[str, object]) -> set[str]:
    """Return normalized label set for a bead issue.

    Args:
        issue: Bead issue payload.

    Returns:
        Set of label strings.
    """
    boundary = parse_issue_boundary(issue, source="issue_labels")
    return set(boundary.labels)


def filter_epics(
    issues: list[dict[str, object]],
    *,
    assignee: str | None = None,
    require_unassigned: bool = False,
) -> list[dict[str, object]]:
    """Filter epics according to assignment and draft status.

    Args:
        issues: Candidate issue payloads.
        assignee: Optional assignee filter.
        require_unassigned: Whether only unassigned epics are allowed.

    Returns:
        Filtered epic payload list.
    """
    return worker_selection.filter_epics(
        issues,
        assignee=assignee,
        require_unassigned=require_unassigned,
        allow_hooked=assignee is not None,
        skip_draft=True,
    )


def parse_issue_time(value: object) -> dt.datetime | None:
    """Parse issue timestamp values.

    Args:
        value: Raw timestamp object.

    Returns:
        Parsed UTC datetime when valid, else ``None``.
    """
    return worker_selection.parse_issue_time(value)


def is_closed_status(status: object) -> bool:
    """Return whether an issue status represents a closed state.

    Args:
        status: Raw status value.

    Returns:
        ``True`` when status is closed/done.
    """
    return lifecycle.is_closed_status(status)


def is_feedback_eligible_epic_status(status: object) -> bool:
    """Return whether an epic status can be considered for review feedback.

    Args:
        status: Raw status value.

    Returns:
        ``True`` when status is not closed.
    """
    return not is_closed_status(status)


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
    "report_translated_cli_default",
    "report_worker_summary",
    "step",
    "strip_flag_with_value",
    "trace_enabled",
    "watch_interval_seconds",
    "with_codex_exec",
]

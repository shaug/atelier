"""Worker session command implementation.

Starts worker sessions by selecting an epic and its next ready changeset.
``atelier work`` can loop or watch based on run mode.
"""

from __future__ import annotations

import datetime as dt
import os
import re
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .. import (
    agent_home,
    agents,
    beads,
    branching,
    changesets,
    codex,
    config,
    exec,
    git,
    hooks,
    messages,
    paths,
    policy,
    pr_strategy,
    prompting,
    prs,
    root_branch,
    skills,
    templates,
    workspace,
    worktrees,
)
from ..io import confirm, die, prompt, say, select
from .resolve import resolve_current_project_with_repo_root

_MODE_VALUES = {"prompt", "auto"}
_RUN_MODE_VALUES = {"once", "default", "watch"}
_WATCH_INTERVAL_SECONDS = 60
_WORKER_QUEUE_NAME = "worker"
_SQUASH_MESSAGE_MODES = {"deterministic", "agent"}
_VALID_CHANGESET_STATE_LABELS = {
    "cs:planned",
    "cs:ready",
    "cs:in_progress",
    "cs:blocked",
    "cs:merged",
    "cs:abandoned",
}
_INTEGRATED_SHA_NOTE_PATTERN = re.compile(
    r"`?changeset\.integrated_sha`?\s*[:=]\s*([0-9a-fA-F]{7,40})\b",
    re.MULTILINE,
)
_DEPENDENCY_ID_PATTERN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)\b")


@dataclass(frozen=True)
class StartupContractResult:
    epic_id: str | None
    changeset_id: str | None
    should_exit: bool
    reason: str
    reassign_from: str | None = None


@dataclass(frozen=True)
class WorkerRunSummary:
    started: bool
    reason: str
    epic_id: str | None = None
    changeset_id: str | None = None


@dataclass(frozen=True)
class FinalizeResult:
    continue_running: bool
    reason: str


@dataclass(frozen=True)
class ReconcileResult:
    scanned: int
    actionable: int
    reconciled: int
    failed: int


@dataclass(frozen=True)
class _ReconcileCandidate:
    issue_id: str
    issue: dict[str, object]
    status: str
    epic_id: str
    integrated_sha: str | None
    dependency_ids: tuple[str, ...]


@dataclass(frozen=True)
class _PublishSignalDiagnostics:
    local_branch_exists: bool
    remote_branch_exists: bool
    worktree_path: Path | None
    dirty_entries: tuple[str, ...]

    @property
    def has_recoverable_local_state(self) -> bool:
        return self.local_branch_exists or bool(self.dirty_entries)


@dataclass(frozen=True)
class _ReviewFeedbackSelection:
    epic_id: str
    changeset_id: str
    feedback_at: str


def _normalize_branch_value(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned or cleaned.lower() == "null":
        return None
    return cleaned


def _extract_changeset_root_branch(issue: dict[str, object]) -> str | None:
    description = issue.get("description")
    fields = beads.parse_description_fields(
        description if isinstance(description, str) else ""
    )
    return _normalize_branch_value(fields.get("changeset.root_branch"))


def _extract_workspace_parent_branch(issue: dict[str, object]) -> str | None:
    description = issue.get("description")
    fields = beads.parse_description_fields(
        description if isinstance(description, str) else ""
    )
    return _normalize_branch_value(fields.get("workspace.parent_branch"))


def _issue_parent_id(issue: dict[str, object]) -> str | None:
    parent = issue.get("parent")
    if isinstance(parent, str):
        cleaned = parent.strip()
        return cleaned or None
    if isinstance(parent, dict):
        parent_id = parent.get("id")
        if isinstance(parent_id, str):
            cleaned = parent_id.strip()
            return cleaned or None
    return None


def _parse_dependency_issue_id(value: object) -> str | None:
    if isinstance(value, dict):
        relation = value.get("relation")
        if isinstance(relation, str) and relation.strip().lower() == "parent-child":
            return None
        issue_id = value.get("id")
        if isinstance(issue_id, str):
            cleaned = issue_id.strip()
            return cleaned or None
        nested_issue = value.get("issue")
        if isinstance(nested_issue, dict):
            nested_id = nested_issue.get("id")
            if isinstance(nested_id, str):
                cleaned = nested_id.strip()
                return cleaned or None
        return None

    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if "parent-child" in text.lower():
        return None
    match = _DEPENDENCY_ID_PATTERN.match(text)
    if not match:
        return None
    return match.group(1).strip() or None


def _issue_dependency_ids(issue: dict[str, object]) -> tuple[str, ...]:
    dependencies = issue.get("dependencies")
    if not isinstance(dependencies, list):
        return ()
    ids: list[str] = []
    seen: set[str] = set()
    for dependency in dependencies:
        dependency_id = _parse_dependency_issue_id(dependency)
        if not dependency_id or dependency_id in seen:
            continue
        seen.add(dependency_id)
        ids.append(dependency_id)
    return tuple(ids)


def _dry_run_log(message: str) -> None:
    say(f"DRY-RUN: {message}")


def _trace_enabled() -> bool:
    return os.environ.get("ATELIER_WORK_TRACE", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _step(label: str, *, timings: list[tuple[str, float]], trace: bool) -> callable:
    say(f"-> {label}")
    start = time.perf_counter()

    def finish(extra: str | None = None) -> None:
        elapsed = time.perf_counter() - start
        timings.append((label, elapsed))
        suffix = f" ({elapsed:.2f}s)" if trace or elapsed >= 0.5 else ""
        if extra:
            say(f"ok {label}{suffix}: {extra}")
        else:
            say(f"ok {label}{suffix}")

    return finish


def _report_timings(timings: list[tuple[str, float]], *, trace: bool) -> None:
    if not timings:
        return
    slow = [(label, elapsed) for label, elapsed in timings if elapsed >= 0.5]
    if not trace and not slow:
        return
    say("Timing summary:")
    for label, elapsed in sorted(timings, key=lambda item: item[1], reverse=True):
        if not trace and elapsed < 0.5:
            continue
        say(f"- {label}: {elapsed:.2f}s")


def _report_worker_summary(summary: WorkerRunSummary, *, dry_run: bool) -> None:
    prefix = "DRY-RUN " if dry_run else ""
    status = "started worker session" if summary.started else "no worker started"
    say(f"{prefix}Summary: {status}")
    if summary.reason:
        say(f"- Reason: {summary.reason}")
    if summary.epic_id:
        say(f"- Epic: {summary.epic_id}")
    if summary.changeset_id:
        say(f"- Changeset: {summary.changeset_id}")


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
    labels = issue.get("labels")
    if not isinstance(labels, list):
        return set()
    return {str(label) for label in labels if label is not None}


def _is_eligible_status(status: str, *, allow_hooked: bool) -> bool:
    if not status:
        return True
    normalized = status.lower()
    if normalized in {"open", "ready", "in_progress"}:
        return True
    if allow_hooked and normalized == "hooked":
        return True
    return False


def _filter_epics(
    issues: list[dict[str, object]],
    *,
    assignee: str | None = None,
    require_unassigned: bool = False,
) -> list[dict[str, object]]:
    filtered: list[dict[str, object]] = []
    for issue in issues:
        status = str(issue.get("status") or "")
        if not _is_eligible_status(status, allow_hooked=assignee is not None):
            continue
        labels = _issue_labels(issue)
        if "at:draft" in labels:
            continue
        issue_assignee = issue.get("assignee")
        if assignee is not None:
            if issue_assignee != assignee:
                continue
        elif require_unassigned and issue_assignee:
            continue
        filtered.append(issue)
    return filtered


def _parse_issue_time(value: object) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


def _is_closed_status(status: object) -> bool:
    normalized = str(status or "").strip().lower()
    return normalized in {"closed", "done"}


def _is_feedback_eligible_epic_status(status: object) -> bool:
    return not _is_closed_status(status)


def _sort_by_created_at(
    issues: list[dict[str, object]], *, newest: bool = False
) -> list[dict[str, object]]:
    sentinel = dt.datetime.max.replace(tzinfo=dt.timezone.utc)
    return sorted(
        issues,
        key=lambda issue: _parse_issue_time(issue.get("created_at")) or sentinel,
        reverse=newest,
    )


def _sort_by_recency(issues: list[dict[str, object]]) -> list[dict[str, object]]:
    sentinel = dt.datetime.min.replace(tzinfo=dt.timezone.utc)

    def key(issue: dict[str, object]) -> dt.datetime:
        updated = _parse_issue_time(issue.get("updated_at"))
        if updated:
            return updated
        created = _parse_issue_time(issue.get("created_at"))
        if created:
            return created
        return sentinel

    return sorted(issues, key=key, reverse=True)


def _agent_family_id(agent_id: str) -> str:
    parts = [part for part in str(agent_id).split("/") if part]
    if len(parts) >= 3 and parts[0] == "atelier":
        return "/".join(parts[:3])
    return str(agent_id)


def _agent_session_pid(agent_id: str) -> int | None:
    parts = [part for part in str(agent_id).split("/") if part]
    if len(parts) < 4:
        return None
    token = parts[3]
    if not token.startswith("p"):
        return None
    pid_part = token[1:].split("-", 1)[0]
    if not pid_part.isdigit():
        return None
    return int(pid_part)


def _is_agent_session_active(agent_id: str) -> bool:
    pid = _agent_session_pid(agent_id)
    if pid is None:
        return False
    if pid == os.getpid():
        return True
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _stale_family_assigned_epics(
    issues: list[dict[str, object]], *, agent_id: str
) -> list[dict[str, object]]:
    family = _agent_family_id(agent_id)
    candidates: list[dict[str, object]] = []
    for issue in issues:
        status = str(issue.get("status") or "")
        if not _is_eligible_status(status, allow_hooked=True):
            continue
        labels = _issue_labels(issue)
        if "at:draft" in labels:
            continue
        assignee = issue.get("assignee")
        if not isinstance(assignee, str) or not assignee or assignee == agent_id:
            continue
        if _agent_family_id(assignee) != family:
            continue
        if _is_agent_session_active(assignee):
            continue
        candidates.append(issue)
    return _sort_by_created_at(candidates)


def _list_epics(*, beads_root: Path, repo_root: Path) -> list[dict[str, object]]:
    return beads.run_bd_json(
        ["list", "--label", "at:epic"], beads_root=beads_root, cwd=repo_root
    )


def _select_epic_prompt(
    issues: list[dict[str, object]],
    *,
    agent_id: str,
    is_actionable: Callable[[str], bool],
    assume_yes: bool = False,
) -> str | None:
    epics = _filter_epics(issues, require_unassigned=True)
    resume = _filter_epics(issues, assignee=agent_id)
    if not epics and not resume:
        return None
    choices: dict[str, str] = {}
    for issue in epics:
        issue_id = issue.get("id") or ""
        if not issue_id or not is_actionable(str(issue_id)):
            continue
        status = issue.get("status") or "unknown"
        title = issue.get("title") or ""
        root_branch_value = beads.extract_workspace_root_branch(issue) or "unset"
        label = f"available | {issue_id} [{status}] {root_branch_value} {title}"
        choices[label] = str(issue_id)
    resume = _sort_by_recency(resume)
    for issue in resume:
        issue_id = issue.get("id") or ""
        if not issue_id or not is_actionable(str(issue_id)):
            continue
        status = issue.get("status") or "unknown"
        title = issue.get("title") or ""
        root_branch_value = beads.extract_workspace_root_branch(issue) or "unset"
        label = f"resume | {issue_id} [{status}] {root_branch_value} {title}"
        choices[label] = str(issue_id)
    if not choices:
        return None
    labels = list(choices.keys())
    if assume_yes:
        return choices[labels[0]]
    selected = select("Epic to work on", labels)
    return choices[selected]


def _select_epic_auto(
    issues: list[dict[str, object]],
    *,
    agent_id: str,
    is_actionable: Callable[[str], bool],
) -> str | None:
    ready = _filter_epics(issues, require_unassigned=True)
    if ready:
        ready = _sort_by_created_at(ready)
        for issue in ready:
            issue_id = issue.get("id") or ""
            if issue_id and is_actionable(str(issue_id)):
                return str(issue_id)
    unfinished = _filter_epics(issues, assignee=agent_id)
    if unfinished:
        unfinished = _sort_by_created_at(unfinished)
        for issue in unfinished:
            issue_id = issue.get("id") or ""
            if issue_id and is_actionable(str(issue_id)):
                return str(issue_id)
    return None


def _select_epic_from_ready_changesets(
    *,
    issues: list[dict[str, object]],
    is_actionable: Callable[[str], bool],
    beads_root: Path,
    repo_root: Path,
) -> str | None:
    """Pick an actionable epic (or standalone changeset) from global ready work."""
    ready_changesets = beads.run_bd_json(
        ["ready", "--label", "at:changeset"], beads_root=beads_root, cwd=repo_root
    )
    if not ready_changesets:
        return None
    known_epics: dict[str, dict[str, object]] = {
        str(issue_id): issue
        for issue in issues
        if (issue_id := issue.get("id")) is not None
    }
    for changeset in _sort_by_created_at(ready_changesets):
        issue_id = changeset.get("id")
        if not isinstance(issue_id, str) or not issue_id:
            continue
        candidate = issue_id
        if "." in issue_id:
            maybe_epic = issue_id.split(".", 1)[0]
            if maybe_epic in known_epics:
                candidate = maybe_epic
        candidate_issue = known_epics.get(candidate)
        source_issue = candidate_issue if candidate_issue is not None else changeset
        source_labels = _issue_labels(source_issue)
        if "at:draft" in source_labels:
            continue
        assignee = source_issue.get("assignee")
        if isinstance(assignee, str) and assignee.strip():
            continue
        if is_actionable(candidate):
            return candidate
    return None


def _send_needs_decision(
    *,
    agent_id: str,
    mode: str,
    issues: list[dict[str, object]],
    beads_root: Path,
    repo_root: Path,
    dry_run: bool,
) -> None:
    ready = _filter_epics(issues, require_unassigned=True)
    assigned = _filter_epics(issues, assignee=agent_id)
    subject = "NEEDS-DECISION: No eligible epics"
    timestamp = dt.datetime.now(tz=dt.timezone.utc).isoformat()
    body = "\n".join(
        [
            f"Agent: {agent_id}",
            f"Mode: {mode}",
            f"Total epics: {len(issues)}",
            f"Ready epics: {len(ready)}",
            f"Assigned epics: {len(assigned)}",
            f"Timestamp: {timestamp}",
        ]
    )
    if dry_run:
        _dry_run_log(f"Would send message: {subject}")
        _dry_run_log(body)
        return
    beads.create_message_bead(
        subject=subject,
        body=body,
        metadata={"from": agent_id, "queue": "overseer", "msg_type": "notification"},
        beads_root=beads_root,
        cwd=repo_root,
    )


def _send_planner_notification(
    *,
    subject: str,
    body: str,
    agent_id: str,
    thread_id: str | None,
    beads_root: Path,
    repo_root: Path,
    dry_run: bool,
) -> None:
    if dry_run:
        _dry_run_log(f"Would send message: {subject}")
        _dry_run_log(body)
        return
    metadata: dict[str, object] = {
        "from": agent_id,
        "queue": "planner",
        "msg_type": "notification",
    }
    if thread_id:
        metadata["thread"] = thread_id
    beads.create_message_bead(
        subject=subject,
        body=body,
        metadata=metadata,
        beads_root=beads_root,
        cwd=repo_root,
    )


def _send_invalid_changeset_labels_notification(
    *,
    epic_id: str,
    invalid_changesets: list[str],
    agent_id: str,
    beads_root: Path,
    repo_root: Path,
    dry_run: bool,
) -> str:
    detail = ", ".join(invalid_changesets[:5])
    if len(invalid_changesets) > 5:
        detail = f"{detail}, ..."
    _send_planner_notification(
        subject=f"NEEDS-DECISION: Invalid changeset labels ({epic_id})",
        body=(
            "Found child work items with invalid labels: "
            f"{', '.join(invalid_changesets)}.\n"
            "All executable work items must be labeled at:changeset; "
            "do not use at:subtask."
        ),
        agent_id=agent_id,
        thread_id=epic_id,
        beads_root=beads_root,
        repo_root=repo_root,
        dry_run=dry_run,
    )
    return detail


def _send_no_ready_changesets(
    *,
    epic_id: str,
    agent_id: str,
    beads_root: Path,
    repo_root: Path,
    dry_run: bool,
) -> None:
    summary = beads.epic_changeset_summary(
        epic_id, beads_root=beads_root, cwd=repo_root
    )
    timestamp = dt.datetime.now(tz=dt.timezone.utc).isoformat()
    subject = f"NEEDS-DECISION: No ready changesets for {epic_id}"
    body = "\n".join(
        [
            f"Epic: {epic_id}",
            f"Agent: {agent_id}",
            f"Total changesets: {summary.total}",
            f"Ready changesets: {summary.ready}",
            f"Remaining changesets: {summary.remaining}",
            f"Timestamp: {timestamp}",
        ]
    )
    _send_planner_notification(
        subject=subject,
        body=body,
        agent_id=agent_id,
        thread_id=epic_id,
        beads_root=beads_root,
        repo_root=repo_root,
        dry_run=dry_run,
    )


def _release_epic_assignment(
    epic_id: str, *, beads_root: Path, repo_root: Path
) -> None:
    issues = beads.run_bd_json(["show", epic_id], beads_root=beads_root, cwd=repo_root)
    if not issues:
        return
    issue = issues[0]
    labels = _issue_labels(issue)
    status = str(issue.get("status") or "")
    args = ["update", epic_id, "--assignee", ""]
    if "at:hooked" in labels:
        args.extend(["--remove-label", "at:hooked"])
    if status and status not in {"closed", "done"}:
        args.extend(["--status", "open"])
    beads.run_bd_command(args, beads_root=beads_root, cwd=repo_root, allow_failure=True)


def _next_changeset(
    *,
    epic_id: str,
    beads_root: Path,
    repo_root: Path,
    repo_slug: str | None = None,
    branch_pr: bool = True,
    branch_pr_strategy: object = pr_strategy.PR_STRATEGY_DEFAULT,
    git_path: str | None = None,
) -> dict[str, object] | None:
    target = beads.run_bd_json(["show", epic_id], beads_root=beads_root, cwd=repo_root)
    if target:
        issue = target[0]
        issue_id = issue.get("id")
        labels = _issue_labels(issue)
        if "at:draft" in labels:
            return None
        if (
            isinstance(issue_id, str)
            and issue_id == epic_id
            and "at:changeset" in labels
            and "cs:merged" not in labels
            and "cs:abandoned" not in labels
            and _is_changeset_ready(issue)
            and not _changeset_waiting_on_review_or_signals(
                issue,
                repo_slug=repo_slug,
                repo_root=repo_root,
                branch_pr=branch_pr,
                branch_pr_strategy=branch_pr_strategy,
                git_path=git_path,
            )
        ):
            if not _has_open_descendant_changesets(
                epic_id, beads_root=beads_root, repo_root=repo_root
            ):
                return issue
        status = str(issue.get("status") or "").strip().lower()
        if (
            isinstance(issue_id, str)
            and issue_id == epic_id
            and "at:epic" in labels
            and "at:ready" in labels
            and status not in {"closed", "done"}
        ):
            descendants = beads.list_descendant_changesets(
                epic_id,
                beads_root=beads_root,
                cwd=repo_root,
                include_closed=True,
            )
            if not descendants:
                # Epics with no child changesets execute directly as a single changeset.
                return issue

    changesets = beads.run_bd_json(
        [
            "ready",
            "--parent",
            epic_id,
            "--label",
            "at:changeset",
        ],
        beads_root=beads_root,
        cwd=repo_root,
    )
    if not changesets:
        return None
    actionable = [
        issue
        for issue in changesets
        if _is_changeset_ready(issue)
        and not _changeset_waiting_on_review_or_signals(
            issue,
            repo_slug=repo_slug,
            repo_root=repo_root,
            branch_pr=branch_pr,
            branch_pr_strategy=branch_pr_strategy,
            git_path=git_path,
        )
    ]
    prioritized = sorted(
        actionable,
        key=lambda issue: (
            0 if _is_changeset_in_progress(issue) else 1,
            str(issue.get("id") or ""),
        ),
    )
    for issue in prioritized:
        issue_id = issue.get("id")
        if isinstance(issue_id, str) and issue_id:
            if not _has_open_descendant_changesets(
                issue_id, beads_root=beads_root, repo_root=repo_root
            ):
                return issue
    return None


def _has_open_descendant_changesets(
    changeset_id: str, *, beads_root: Path, repo_root: Path
) -> bool:
    descendants = beads.list_descendant_changesets(
        changeset_id,
        beads_root=beads_root,
        cwd=repo_root,
        include_closed=False,
    )
    return bool(descendants)


def _is_changeset_in_progress(issue: dict[str, object]) -> bool:
    status = str(issue.get("status") or "").strip().lower()
    if status == "in_progress":
        return True
    labels = _issue_labels(issue)
    return "cs:in_progress" in labels


def _is_changeset_ready(issue: dict[str, object]) -> bool:
    labels = _issue_labels(issue)
    if "cs:ready" in labels:
        return True
    if "at:changeset" not in labels and "cs:in_progress" not in labels:
        return False
    if "cs:planned" in labels or "cs:blocked" in labels:
        return False
    if "cs:merged" in labels or "cs:abandoned" in labels:
        return False
    status = str(issue.get("status") or "").strip().lower()
    if status in {"closed", "done", "blocked"}:
        return False
    if status in {"open", "in_progress", "hooked"}:
        return True
    return "cs:in_progress" in labels


def _changeset_review_state(issue: dict[str, object]) -> str | None:
    description = issue.get("description")
    fields = beads.parse_description_fields(
        description if isinstance(description, str) else ""
    )
    raw = fields.get("pr_state")
    if not isinstance(raw, str):
        return None
    normalized = raw.strip().lower()
    if not normalized or normalized == "null":
        return None
    return normalized


def _changeset_waiting_on_review(issue: dict[str, object]) -> bool:
    state = _changeset_review_state(issue)
    if state is None:
        return False
    return state in {"pushed", "draft-pr", "pr-open", "in-review", "approved"}


def _changeset_work_branch(issue: dict[str, object]) -> str | None:
    description = issue.get("description")
    fields = beads.parse_description_fields(
        description if isinstance(description, str) else ""
    )
    raw = fields.get("changeset.work_branch")
    if not isinstance(raw, str):
        return None
    normalized = raw.strip()
    if not normalized or normalized.lower() == "null":
        return None
    return normalized


def _changeset_root_branch(issue: dict[str, object]) -> str | None:
    description = issue.get("description")
    fields = beads.parse_description_fields(
        description if isinstance(description, str) else ""
    )
    raw = fields.get("changeset.root_branch")
    if not isinstance(raw, str):
        return None
    normalized = raw.strip()
    if not normalized or normalized.lower() == "null":
        return None
    return normalized


def _changeset_base_branch(
    issue: dict[str, object], *, repo_root: Path, git_path: str | None
) -> str | None:
    parent_branch = _changeset_parent_branch(
        issue, root_branch=_changeset_root_branch(issue) or ""
    )
    normalized_parent = parent_branch.strip() if isinstance(parent_branch, str) else ""
    if normalized_parent and normalized_parent.lower() != "null":
        return normalized_parent
    root_branch = _changeset_root_branch(issue)
    if root_branch:
        return root_branch
    return git.git_default_branch(repo_root, git_path=git_path)


def _attempt_create_draft_pr(
    *,
    repo_slug: str,
    issue: dict[str, object],
    work_branch: str,
    repo_root: Path,
    git_path: str | None,
) -> tuple[bool, str]:
    base_branch = _changeset_base_branch(issue, repo_root=repo_root, git_path=git_path)
    if not base_branch:
        return False, "missing PR base branch metadata"
    title = str(issue.get("title") or "").strip() or work_branch
    body = (
        f"Automated PR for changeset {issue.get('id') or work_branch}.\n\n"
        "Generated by Atelier worker finalize fallback."
    )
    result = exec.try_run_command(
        [
            "gh",
            "pr",
            "create",
            "--repo",
            repo_slug,
            "--base",
            base_branch,
            "--head",
            work_branch,
            "--title",
            title,
            "--body",
            body,
            "--draft",
        ]
    )
    if result is None:
        return False, "missing required command: gh"
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        return False, detail or "gh pr create failed"
    detail = (result.stdout or "").strip()
    return True, detail or "created draft PR"


def _update_changeset_review_from_pr(
    changeset_id: str,
    *,
    pr_payload: dict[str, object] | None,
    pushed: bool,
    beads_root: Path,
    repo_root: Path,
) -> None:
    if not pr_payload:
        return
    review_requested = prs.has_review_requests(pr_payload)
    lifecycle = prs.lifecycle_state(
        pr_payload, pushed=pushed, review_requested=review_requested
    )
    metadata = changesets.ReviewMetadata(
        pr_url=str(pr_payload.get("url") or "") or None,
        pr_number=str(pr_payload.get("number") or "") or None,
        pr_state=lifecycle,
    )
    beads.update_changeset_review(
        changeset_id,
        metadata,
        beads_root=beads_root,
        cwd=repo_root,
    )


def _handle_pushed_without_pr(
    *,
    issue: dict[str, object],
    changeset_id: str,
    agent_id: str,
    repo_slug: str | None,
    repo_root: Path,
    beads_root: Path,
    branch_pr_strategy: object,
    git_path: str | None,
    create_detail_prefix: str | None = None,
) -> FinalizeResult:
    decision = _changeset_pr_creation_decision(
        issue,
        repo_slug=repo_slug,
        repo_root=repo_root,
        git_path=git_path,
        branch_pr_strategy=branch_pr_strategy,
    )
    if not decision.allow_pr:
        beads.update_changeset_review(
            changeset_id,
            changesets.ReviewMetadata(pr_state="pushed"),
            beads_root=beads_root,
            cwd=repo_root,
        )
        return FinalizeResult(continue_running=True, reason="changeset_review_pending")

    failure_reason = "changeset_pr_create_failed"
    failure_subject = "NEEDS-DECISION: PR creation failed"
    create_detail = create_detail_prefix or ""
    if not repo_slug:
        failure_reason = "changeset_pr_missing_repo_slug"
        failure_subject = "NEEDS-DECISION: PR provider config missing"
        create_detail = "missing GitHub repo slug for PR creation"
    else:
        work_branch = _changeset_work_branch(issue)
        if not work_branch:
            create_detail = "missing changeset.work_branch metadata for PR creation"
        else:
            created, detail = _attempt_create_draft_pr(
                repo_slug=repo_slug,
                issue=issue,
                work_branch=work_branch,
                repo_root=repo_root,
                git_path=git_path,
            )
            create_detail = detail
            if created:
                pr_payload = prs.read_github_pr_status(repo_slug, work_branch)
                if pr_payload:
                    _update_changeset_review_from_pr(
                        changeset_id,
                        pr_payload=pr_payload,
                        pushed=True,
                        beads_root=beads_root,
                        repo_root=repo_root,
                    )
                else:
                    beads.update_changeset_review(
                        changeset_id,
                        changesets.ReviewMetadata(pr_state="draft-pr"),
                        beads_root=beads_root,
                        cwd=repo_root,
                    )
                return FinalizeResult(
                    continue_running=True, reason="changeset_review_pending"
                )
            # Recover from duplicate/race failures by checking live PR state.
            pr_payload = prs.read_github_pr_status(repo_slug, work_branch)
            if pr_payload:
                _update_changeset_review_from_pr(
                    changeset_id,
                    pr_payload=pr_payload,
                    pushed=True,
                    beads_root=beads_root,
                    repo_root=repo_root,
                )
                return FinalizeResult(
                    continue_running=True, reason="changeset_review_pending"
                )

    _mark_changeset_in_progress(
        changeset_id, beads_root=beads_root, repo_root=repo_root
    )
    note = (
        "publish_pending: branch pushed but PR missing where "
        f"strategy allows PR ({decision.reason})"
    )
    if create_detail:
        note = f"{note}; PR creation attempt failed: {create_detail}"
    beads.run_bd_command(
        [
            "update",
            changeset_id,
            "--append-notes",
            note,
        ],
        beads_root=beads_root,
        cwd=repo_root,
        allow_failure=True,
    )
    body = (
        "Changeset branch is pushed but no PR exists where policy allows PR "
        f"creation (strategy={decision.strategy}, reason={decision.reason})."
    )
    if create_detail:
        body = f"{body}\nPR creation attempt failed: {create_detail}"
        say(f"PR creation failed for {changeset_id}: {create_detail}")
    if failure_reason == "changeset_pr_missing_repo_slug":
        body = (
            f"{body}\nAction: configure GitHub provider metadata so finalize can "
            "create PRs automatically."
        )
    else:
        body = (
            f"{body}\nAction: resolve `gh pr create` failure and rerun worker finalize."
        )
    _send_planner_notification(
        subject=f"{failure_subject} ({changeset_id})",
        body=body,
        agent_id=agent_id,
        thread_id=changeset_id,
        beads_root=beads_root,
        repo_root=repo_root,
        dry_run=False,
    )
    return FinalizeResult(continue_running=False, reason=failure_reason)


def _changeset_parent_lifecycle_state(
    issue: dict[str, object],
    *,
    repo_slug: str | None,
    repo_root: Path,
    git_path: str | None,
) -> str | None:
    if not repo_slug:
        return None
    description = issue.get("description")
    fields = beads.parse_description_fields(
        description if isinstance(description, str) else ""
    )
    parent_branch = fields.get("changeset.parent_branch")
    root_branch = fields.get("changeset.root_branch")
    if not isinstance(parent_branch, str):
        return None
    normalized = parent_branch.strip()
    if not normalized or normalized.lower() == "null":
        return None
    if isinstance(root_branch, str):
        normalized_root = root_branch.strip()
        if normalized_root and normalized_root.lower() != "null":
            # Top-level changesets commonly use root==parent; treat as no-parent
            # for PR strategy gating to avoid self-deadlocking PR creation.
            if normalized_root == normalized:
                return None
    pushed = git.git_ref_exists(
        repo_root, f"refs/remotes/origin/{normalized}", git_path=git_path
    )
    payload = prs.read_github_pr_status(repo_slug, normalized)
    review_requested = prs.has_review_requests(payload)
    return prs.lifecycle_state(
        payload, pushed=pushed, review_requested=review_requested
    )


def _changeset_pr_creation_decision(
    issue: dict[str, object],
    *,
    repo_slug: str | None,
    repo_root: Path,
    git_path: str | None,
    branch_pr_strategy: object,
) -> pr_strategy.PrStrategyDecision:
    parent_state = _changeset_parent_lifecycle_state(
        issue, repo_slug=repo_slug, repo_root=repo_root, git_path=git_path
    )
    return pr_strategy.pr_strategy_decision(
        branch_pr_strategy, parent_state=parent_state
    )


def _changeset_waiting_on_review_or_signals(
    issue: dict[str, object],
    *,
    repo_slug: str | None,
    repo_root: Path,
    branch_pr: bool,
    branch_pr_strategy: object,
    git_path: str | None,
) -> bool:
    if not branch_pr:
        return False
    work_branch = _changeset_work_branch(issue)
    if work_branch:
        pushed = git.git_ref_exists(
            repo_root, f"refs/remotes/origin/{work_branch}", git_path=git_path
        )
        pr_payload = (
            prs.read_github_pr_status(repo_slug, work_branch) if repo_slug else None
        )
        review_requested = prs.has_review_requests(pr_payload)
        state = prs.lifecycle_state(
            pr_payload, pushed=pushed, review_requested=review_requested
        )
        if state in {"merged", "closed"}:
            return False
        if state in {"draft-pr", "pr-open", "in-review", "approved"}:
            return True
        if state == "pushed":
            decision = _changeset_pr_creation_decision(
                issue,
                repo_slug=repo_slug,
                repo_root=repo_root,
                git_path=git_path,
                branch_pr_strategy=branch_pr_strategy,
            )
            return not decision.allow_pr
    review_state = _changeset_review_state(issue)
    if review_state:
        if review_state in {"draft-pr", "pr-open", "in-review", "approved"}:
            return True
        if review_state == "pushed":
            decision = _changeset_pr_creation_decision(
                issue,
                repo_slug=repo_slug,
                repo_root=repo_root,
                git_path=git_path,
                branch_pr_strategy=branch_pr_strategy,
            )
            return not decision.allow_pr
    return False


def _changeset_feedback_cursor(issue: dict[str, object]) -> dt.datetime | None:
    description = issue.get("description")
    fields = beads.parse_description_fields(
        description if isinstance(description, str) else ""
    )
    return _parse_issue_time(fields.get("review.last_feedback_seen_at"))


def _changeset_in_review_candidate(issue: dict[str, object]) -> bool:
    labels = _issue_labels(issue)
    if "at:changeset" not in labels:
        return False
    if "cs:merged" in labels or "cs:abandoned" in labels:
        return False
    if _is_closed_status(issue.get("status")):
        return False
    state = _changeset_review_state(issue)
    return state in {"draft-pr", "pr-open", "in-review", "approved"}


def _select_review_feedback_changeset(
    *,
    epic_id: str,
    repo_slug: str | None,
    beads_root: Path,
    repo_root: Path,
) -> _ReviewFeedbackSelection | None:
    if not repo_slug:
        return None
    descendants = beads.list_descendant_changesets(
        epic_id,
        beads_root=beads_root,
        cwd=repo_root,
        include_closed=False,
    )
    candidates: list[_ReviewFeedbackSelection] = []
    for issue in descendants:
        changeset_id = issue.get("id")
        if not isinstance(changeset_id, str) or not changeset_id:
            continue
        if not _changeset_in_review_candidate(issue):
            continue
        work_branch = _changeset_work_branch(issue)
        if not work_branch:
            continue
        pr_payload = prs.read_github_pr_status(repo_slug, work_branch)
        feedback_at = prs.latest_feedback_timestamp(pr_payload)
        if not feedback_at:
            continue
        feedback_time = _parse_issue_time(feedback_at)
        if feedback_time is None:
            continue
        cursor = _changeset_feedback_cursor(issue)
        if cursor is not None and feedback_time <= cursor:
            continue
        candidates.append(
            _ReviewFeedbackSelection(
                epic_id=epic_id,
                changeset_id=changeset_id,
                feedback_at=feedback_at,
            )
        )
    if not candidates:
        return None
    candidates.sort(
        key=lambda item: _parse_issue_time(item.feedback_at) or dt.datetime.max
    )
    return candidates[0]


def _select_global_review_feedback_changeset(
    *,
    repo_slug: str | None,
    beads_root: Path,
    repo_root: Path,
) -> _ReviewFeedbackSelection | None:
    if not repo_slug:
        return None
    issues = beads.run_bd_json(
        ["list", "--label", "at:changeset"], beads_root=beads_root, cwd=repo_root
    )
    candidates: list[_ReviewFeedbackSelection] = []
    for issue in issues:
        changeset_id = issue.get("id")
        if not isinstance(changeset_id, str) or not changeset_id:
            continue
        if not _changeset_in_review_candidate(issue):
            continue
        work_branch = _changeset_work_branch(issue)
        if not work_branch:
            continue
        pr_payload = prs.read_github_pr_status(repo_slug, work_branch)
        feedback_at = prs.latest_feedback_timestamp(pr_payload)
        if not feedback_at:
            continue
        feedback_time = _parse_issue_time(feedback_at)
        if feedback_time is None:
            continue
        cursor = _changeset_feedback_cursor(issue)
        if cursor is not None and feedback_time <= cursor:
            continue
        epic_id = _resolve_epic_id_for_changeset(
            issue, beads_root=beads_root, repo_root=repo_root
        )
        if not epic_id:
            epic_id = changeset_id
        candidates.append(
            _ReviewFeedbackSelection(
                epic_id=epic_id,
                changeset_id=changeset_id,
                feedback_at=feedback_at,
            )
        )
    if not candidates:
        return None
    candidates.sort(
        key=lambda item: _parse_issue_time(item.feedback_at) or dt.datetime.max
    )
    return candidates[0]


def _list_child_issues(
    parent_id: str, *, beads_root: Path, repo_root: Path, include_closed: bool = False
) -> list[dict[str, object]]:
    args = ["list", "--parent", parent_id]
    if include_closed:
        args.append("--all")
    return beads.run_bd_json(args, beads_root=beads_root, cwd=repo_root)


def _find_invalid_changeset_labels(
    root_id: str, *, beads_root: Path, repo_root: Path
) -> list[str]:
    invalid: list[str] = []
    seen: set[str] = set()
    queue = [root_id]
    while queue:
        current = queue.pop(0)
        children = _list_child_issues(
            current, beads_root=beads_root, repo_root=repo_root, include_closed=True
        )
        for issue in children:
            issue_id = issue.get("id")
            if not isinstance(issue_id, str) or not issue_id or issue_id in seen:
                continue
            seen.add(issue_id)
            queue.append(issue_id)
            labels = _issue_labels(issue)
            has_cs_label = any(label.startswith("cs:") for label in labels)
            invalid_cs_labels = {
                label
                for label in labels
                if label.startswith("cs:")
                and label not in _VALID_CHANGESET_STATE_LABELS
            }
            if "at:subtask" in labels or (
                has_cs_label and "at:changeset" not in labels
            ):
                invalid.append(issue_id)
                continue
            if invalid_cs_labels:
                invalid.append(issue_id)
    return invalid


def _changeset_parent_branch(issue: dict[str, object], *, root_branch: str) -> str:
    description = issue.get("description")
    fields = beads.parse_description_fields(
        description if isinstance(description, str) else ""
    )
    parent_branch = fields.get("changeset.parent_branch")
    if not parent_branch:
        return root_branch
    normalized = parent_branch.strip()
    if not normalized or normalized.lower() == "null":
        return root_branch
    return normalized


def _resolve_hooked_epic(
    agent_bead_id: str,
    agent_id: str,
    *,
    beads_root: Path,
    repo_root: Path,
) -> str | None:
    hook_id = beads.get_agent_hook(agent_bead_id, beads_root=beads_root, cwd=repo_root)
    if not hook_id:
        return None
    issues = beads.run_bd_json(["show", hook_id], beads_root=beads_root, cwd=repo_root)
    if not issues:
        return None
    epic = issues[0]
    status = str(epic.get("status") or "").lower()
    if status in {"closed", "done"}:
        return None
    assignee = epic.get("assignee")
    if assignee and assignee != agent_id:
        return None
    if assignee != agent_id:
        return None
    return hook_id


def _mark_changeset_in_progress(
    changeset_id: str, *, beads_root: Path, repo_root: Path
) -> None:
    beads.run_bd_command(
        [
            "update",
            changeset_id,
            "--add-label",
            "at:changeset",
            "--remove-label",
            "cs:ready",
            "--remove-label",
            "cs:in_progress",
            "--remove-label",
            "cs:planned",
            "--remove-label",
            "cs:blocked",
            "--remove-label",
            "cs:merged",
            "--remove-label",
            "cs:abandoned",
            "--status",
            "in_progress",
        ],
        beads_root=beads_root,
        cwd=repo_root,
    )


def _mark_changeset_closed(
    changeset_id: str, *, beads_root: Path, repo_root: Path
) -> None:
    beads.run_bd_command(
        [
            "update",
            changeset_id,
            "--status",
            "closed",
            "--remove-label",
            "cs:ready",
            "--remove-label",
            "cs:planned",
            "--remove-label",
            "cs:in_progress",
            "--remove-label",
            "cs:blocked",
        ],
        beads_root=beads_root,
        cwd=repo_root,
    )


def _mark_changeset_merged(
    changeset_id: str, *, beads_root: Path, repo_root: Path
) -> None:
    beads.run_bd_command(
        [
            "update",
            changeset_id,
            "--add-label",
            "cs:merged",
            "--remove-label",
            "cs:abandoned",
            "--remove-label",
            "cs:ready",
            "--remove-label",
            "cs:planned",
            "--remove-label",
            "cs:in_progress",
            "--remove-label",
            "cs:blocked",
            "--status",
            "closed",
        ],
        beads_root=beads_root,
        cwd=repo_root,
    )


def _mark_changeset_abandoned(
    changeset_id: str, *, beads_root: Path, repo_root: Path
) -> None:
    beads.run_bd_command(
        [
            "update",
            changeset_id,
            "--add-label",
            "cs:abandoned",
            "--remove-label",
            "cs:merged",
            "--remove-label",
            "cs:ready",
            "--remove-label",
            "cs:planned",
            "--remove-label",
            "cs:in_progress",
            "--remove-label",
            "cs:blocked",
            "--status",
            "closed",
        ],
        beads_root=beads_root,
        cwd=repo_root,
    )


def _mark_changeset_blocked(
    changeset_id: str, *, beads_root: Path, repo_root: Path, reason: str
) -> None:
    timestamp = dt.datetime.now(tz=dt.timezone.utc).isoformat()
    note = f"blocked_at: {timestamp} reason: {reason}"
    beads.run_bd_command(
        [
            "update",
            changeset_id,
            "--remove-label",
            "cs:in_progress",
            "--remove-label",
            "cs:ready",
            "--remove-label",
            "cs:planned",
            "--remove-label",
            "cs:merged",
            "--remove-label",
            "cs:abandoned",
            "--add-label",
            "cs:blocked",
            "--status",
            "blocked",
            "--append-notes",
            note,
        ],
        beads_root=beads_root,
        cwd=repo_root,
    )


def _mark_changeset_children_in_progress(
    changeset_id: str, *, beads_root: Path, repo_root: Path
) -> None:
    beads.run_bd_command(
        [
            "update",
            changeset_id,
            "--status",
            "in_progress",
            "--remove-label",
            "cs:ready",
            "--remove-label",
            "cs:in_progress",
            "--remove-label",
            "cs:planned",
            "--remove-label",
            "cs:blocked",
            "--remove-label",
            "cs:merged",
            "--remove-label",
            "cs:abandoned",
        ],
        beads_root=beads_root,
        cwd=repo_root,
    )


def _close_completed_container_changesets(
    epic_id: str, *, beads_root: Path, repo_root: Path
) -> list[str]:
    closed: list[str] = []
    descendants = beads.list_descendant_changesets(
        epic_id,
        beads_root=beads_root,
        cwd=repo_root,
        include_closed=True,
    )
    for issue in descendants:
        issue_id = issue.get("id")
        if not isinstance(issue_id, str) or not issue_id:
            continue
        status = str(issue.get("status") or "").lower()
        if status in {"closed", "done"}:
            continue
        labels = _issue_labels(issue)
        if "cs:merged" not in labels and "cs:abandoned" not in labels:
            continue
        if _has_open_descendant_changesets(
            issue_id, beads_root=beads_root, repo_root=repo_root
        ):
            continue
        _mark_changeset_closed(issue_id, beads_root=beads_root, repo_root=repo_root)
        closed.append(issue_id)
    return closed


def _promote_planned_descendant_changesets(
    changeset_id: str, *, beads_root: Path, repo_root: Path
) -> list[str]:
    promoted: list[str] = []
    descendants = beads.list_descendant_changesets(
        changeset_id,
        beads_root=beads_root,
        cwd=repo_root,
        include_closed=False,
    )
    for issue in descendants:
        issue_id = issue.get("id")
        if not isinstance(issue_id, str) or not issue_id:
            continue
        labels = _issue_labels(issue)
        if "cs:planned" not in labels:
            continue
        beads.run_bd_command(
            [
                "update",
                issue_id,
                "--add-label",
                "cs:ready",
                "--remove-label",
                "cs:planned",
                "--status",
                "open",
            ],
            beads_root=beads_root,
            cwd=repo_root,
        )
        promoted.append(issue_id)
    return promoted


def _has_blocking_messages(
    *,
    thread_ids: set[str],
    started_at: dt.datetime,
    beads_root: Path,
    repo_root: Path,
) -> bool:
    issues = beads.run_bd_json(
        ["list", "--label", "at:message", "--label", "at:unread"],
        beads_root=beads_root,
        cwd=repo_root,
    )
    for issue in issues:
        created_at = _parse_issue_time(issue.get("created_at"))
        if created_at is not None and created_at < started_at:
            continue
        description = issue.get("description")
        payload = messages.parse_message(
            description if isinstance(description, str) else ""
        )
        thread = payload.metadata.get("thread")
        if isinstance(thread, str) and thread in thread_ids:
            return True
    return False


def _branch_ref_for_lookup(
    repo_root: Path, branch: str, *, git_path: str | None = None
) -> str | None:
    normalized = branch.strip()
    if not normalized:
        return None
    if git_path is None:
        local_exists = git.git_ref_exists(repo_root, f"refs/heads/{normalized}")
    else:
        local_exists = git.git_ref_exists(
            repo_root, f"refs/heads/{normalized}", git_path=git_path
        )
    if local_exists:
        return normalized
    if git_path is None:
        remote_exists = git.git_ref_exists(
            repo_root, f"refs/remotes/origin/{normalized}"
        )
    else:
        remote_exists = git.git_ref_exists(
            repo_root, f"refs/remotes/origin/{normalized}", git_path=git_path
        )
    if remote_exists:
        return f"origin/{normalized}"
    return None


def _epic_root_integrated_into_parent(
    epic_issue: dict[str, object],
    *,
    repo_root: Path,
    git_path: str | None = None,
) -> bool:
    root_branch = beads.extract_workspace_root_branch(epic_issue)
    if not root_branch:
        root_branch = _extract_changeset_root_branch(epic_issue)
    parent_branch = _extract_workspace_parent_branch(epic_issue)
    default_branch = git.git_default_branch(repo_root, git_path=git_path)
    if not parent_branch or (root_branch and parent_branch == root_branch):
        parent_branch = default_branch or parent_branch or root_branch
    if not root_branch or not parent_branch:
        return False
    parent_ref = _branch_ref_for_lookup(repo_root, parent_branch, git_path=git_path)
    if not parent_ref:
        return False
    root_ref = _branch_ref_for_lookup(repo_root, root_branch, git_path=git_path)
    if not root_ref:
        # Root already pruned; assume finalization path completed.
        return True
    is_ancestor = git.git_is_ancestor(
        repo_root, root_ref, parent_ref, git_path=git_path
    )
    if is_ancestor is True:
        return True
    fully_applied = git.git_branch_fully_applied(
        repo_root, parent_ref, root_ref, git_path=git_path
    )
    return fully_applied is True


def _changeset_integration_signal(
    issue: dict[str, object],
    *,
    repo_slug: str | None,
    repo_root: Path,
    git_path: str | None = None,
) -> tuple[bool, str | None]:
    description = issue.get("description")
    description_text = description if isinstance(description, str) else ""
    notes = issue.get("notes")
    notes_text = notes if isinstance(notes, str) else ""
    fields = beads.parse_description_fields(description_text)
    integrated_sha_candidates: list[str] = []
    integrated_sha = fields.get("changeset.integrated_sha")
    if integrated_sha and integrated_sha.strip().lower() != "null":
        integrated_sha_candidates.append(integrated_sha.strip())
    combined_text = "\n".join(part for part in (description_text, notes_text) if part)
    if combined_text:
        integrated_sha_candidates.extend(
            match.group(1)
            for match in _INTEGRATED_SHA_NOTE_PATTERN.finditer(combined_text)
        )
    if integrated_sha_candidates:
        return True, integrated_sha_candidates[-1]

    root_branch = fields.get("changeset.root_branch")
    work_branch = fields.get("changeset.work_branch")

    # PR merge signal (review flows).
    if repo_slug and work_branch and work_branch.strip().lower() != "null":
        pr_payload = prs.read_github_pr_status(repo_slug, work_branch.strip())
        if pr_payload and pr_payload.get("mergedAt"):
            return True, None

    # Local git graph signal (non-review fallback).
    if not root_branch or not work_branch:
        return False, None
    if root_branch.strip().lower() == "null" or work_branch.strip().lower() == "null":
        return False, None
    root_ref = _branch_ref_for_lookup(repo_root, root_branch, git_path=git_path)
    work_ref = _branch_ref_for_lookup(repo_root, work_branch, git_path=git_path)
    if not root_ref or not work_ref:
        return False, None

    is_ancestor = git.git_is_ancestor(repo_root, work_ref, root_ref, git_path=git_path)
    if is_ancestor is True:
        return True, git.git_rev_parse(repo_root, root_ref)

    fully_applied = git.git_branch_fully_applied(
        repo_root, root_ref, work_ref, git_path=git_path
    )
    if fully_applied is True:
        return True, git.git_rev_parse(repo_root, root_ref)

    return False, None


def _resolve_epic_id_for_changeset(
    issue: dict[str, object], *, beads_root: Path, repo_root: Path
) -> str | None:
    current = issue
    current_id = issue.get("id")
    if not isinstance(current_id, str) or not current_id.strip():
        return None
    visited: set[str] = set()
    while True:
        issue_id = current_id.strip()
        if not issue_id or issue_id in visited:
            return None
        visited.add(issue_id)
        labels = _issue_labels(current)
        if "at:epic" in labels:
            return issue_id
        parent_id = _issue_parent_id(current)
        if not parent_id:
            # `bd list` payloads can omit parent details; refresh full issue once.
            if current is issue:
                loaded = beads.run_bd_json(
                    ["show", issue_id], beads_root=beads_root, cwd=repo_root
                )
                if loaded:
                    refreshed = loaded[0]
                    refreshed_parent = _issue_parent_id(refreshed)
                    if refreshed_parent:
                        current = refreshed
                        parent_id = refreshed_parent
                        current_id = issue_id
            # Standalone top-level changeset can act as its own epic root.
            if not parent_id:
                return issue_id
        parent_issues = beads.run_bd_json(
            ["show", parent_id], beads_root=beads_root, cwd=repo_root
        )
        if not parent_issues:
            return parent_id
        current = parent_issues[0]
        current_id = parent_id


def list_reconcile_epic_candidates(
    *,
    project_config: config.ProjectConfig,
    beads_root: Path,
    repo_root: Path,
    git_path: str | None = None,
) -> dict[str, list[str]]:
    """Return merged changeset reconciliation candidates grouped by epic."""
    issues = beads.run_bd_json(
        ["list", "--label", "at:changeset", "--label", "cs:merged", "--all"],
        beads_root=beads_root,
        cwd=repo_root,
    )
    repo_slug = prs.github_repo_slug(
        project_config.project.origin or project_config.project.repo_url
    )
    epic_cache: dict[str, dict[str, object] | None] = {}

    def load_epic(epic_id: str) -> dict[str, object] | None:
        if epic_id in epic_cache:
            return epic_cache[epic_id]
        loaded = beads.run_bd_json(
            ["show", epic_id], beads_root=beads_root, cwd=repo_root
        )
        epic_cache[epic_id] = loaded[0] if loaded else None
        return epic_cache[epic_id]

    candidates: dict[str, list[str]] = {}
    for issue in issues:
        issue_id = issue.get("id")
        if not isinstance(issue_id, str) or not issue_id.strip():
            continue
        status = str(issue.get("status") or "").strip().lower()
        if status not in {"", "blocked", "closed"}:
            continue
        integration_proven, _integrated_sha = _changeset_integration_signal(
            issue, repo_slug=repo_slug, repo_root=repo_root, git_path=git_path
        )
        if not integration_proven:
            continue
        epic_id = _resolve_epic_id_for_changeset(
            issue, beads_root=beads_root, repo_root=repo_root
        )
        if not epic_id:
            continue
        issue_status = str(issue.get("status") or "").strip().lower()
        if issue_status == "closed":
            epic_issue = load_epic(epic_id)
            epic_closed = bool(epic_issue) and _is_closed_status(
                epic_issue.get("status")
            )
            if (
                epic_closed
                and _integrated_sha
                and epic_issue
                and _epic_root_integrated_into_parent(
                    epic_issue, repo_root=repo_root, git_path=git_path
                )
            ):
                continue
        candidates.setdefault(epic_id, []).append(issue_id.strip())
    ordered: dict[str, list[str]] = {}
    for epic_id in sorted(candidates):
        ordered[epic_id] = sorted(candidates[epic_id])
    return ordered


def _resolve_hook_agent_bead_for_epic(
    epic_id: str,
    *,
    fallback_agent_bead_id: str | None,
    beads_root: Path,
    repo_root: Path,
) -> str | None:
    issues = beads.run_bd_json(["show", epic_id], beads_root=beads_root, cwd=repo_root)
    if not issues:
        return fallback_agent_bead_id
    assignee = issues[0].get("assignee")
    if isinstance(assignee, str) and assignee.strip():
        assignee_bead = beads.find_agent_bead(
            assignee.strip(), beads_root=beads_root, cwd=repo_root
        )
        if assignee_bead:
            issue_id = assignee_bead.get("id")
            if isinstance(issue_id, str) and issue_id.strip():
                return issue_id.strip()
    return fallback_agent_bead_id


def reconcile_blocked_merged_changesets(
    *,
    agent_id: str,
    agent_bead_id: str | None,
    project_config: config.ProjectConfig,
    project_data_dir: Path | None,
    beads_root: Path,
    repo_root: Path,
    git_path: str | None = None,
    epic_filter: str | None = None,
    changeset_filter: set[str] | None = None,
    dry_run: bool = False,
    log: Callable[[str], None] | None = None,
) -> ReconcileResult:
    """Reconcile merged changesets, honoring dependency order."""
    issues = beads.run_bd_json(
        [
            "list",
            "--label",
            "at:changeset",
            "--label",
            "cs:merged",
            "--all",
        ],
        beads_root=beads_root,
        cwd=repo_root,
    )
    scanned = 0
    actionable = 0
    reconciled = 0
    failed = 0
    started_at = dt.datetime.now(tz=dt.timezone.utc)
    repo_slug = prs.github_repo_slug(
        project_config.project.origin or project_config.project.repo_url
    )
    candidates: dict[str, _ReconcileCandidate] = {}
    for issue in issues:
        changeset_id = issue.get("id")
        if not isinstance(changeset_id, str) or not changeset_id.strip():
            continue
        changeset_id = changeset_id.strip()
        if changeset_filter is not None and changeset_id not in changeset_filter:
            continue
        status = str(issue.get("status") or "").strip().lower()
        if status not in {"", "blocked", "closed"}:
            if log:
                log(f"reconcile scan: {changeset_id} status={status or 'unknown'}")
                log(f"reconcile skip: {changeset_id} (status={status})")
            continue
        epic_id = _resolve_epic_id_for_changeset(
            issue, beads_root=beads_root, repo_root=repo_root
        )
        if epic_filter and epic_id != epic_filter:
            continue
        if log:
            log(f"reconcile scan: {changeset_id} status={status or 'unknown'}")
        if not epic_id:
            failed += 1
            if log:
                log(f"reconcile error: {changeset_id} (unable to resolve epic)")
            continue
        scanned += 1
        integration_proven, integrated_sha = _changeset_integration_signal(
            issue, repo_slug=repo_slug, repo_root=repo_root, git_path=git_path
        )
        if not integration_proven:
            if log:
                log(f"reconcile skip: {changeset_id} (no integration signal)")
            continue
        candidates[changeset_id] = _ReconcileCandidate(
            issue_id=changeset_id,
            issue=issue,
            status=status,
            epic_id=epic_id,
            integrated_sha=integrated_sha.strip() if integrated_sha else None,
            dependency_ids=_issue_dependency_ids(issue),
        )
    actionable = len(candidates)
    if not candidates:
        return ReconcileResult(
            scanned=scanned,
            actionable=actionable,
            reconciled=reconciled,
            failed=failed,
        )

    issue_cache: dict[str, dict[str, object] | None] = {
        candidate.issue_id: candidate.issue for candidate in candidates.values()
    }

    def load_issue(issue_id: str) -> dict[str, object] | None:
        if issue_id in issue_cache:
            return issue_cache[issue_id]
        loaded = beads.run_bd_json(
            ["show", issue_id], beads_root=beads_root, cwd=repo_root
        )
        issue_cache[issue_id] = loaded[0] if loaded else None
        return issue_cache[issue_id]

    dependency_finalized_cache: dict[str, bool] = {}

    def dependency_finalized(issue_id: str) -> bool:
        if issue_id in dependency_finalized_cache:
            return dependency_finalized_cache[issue_id]
        issue = load_issue(issue_id)
        if not issue:
            dependency_finalized_cache[issue_id] = False
            return False
        labels = _issue_labels(issue)
        if "at:changeset" not in labels:
            dependency_finalized_cache[issue_id] = True
            return True
        if "cs:abandoned" in labels:
            status = str(issue.get("status") or "").strip().lower()
            finalized = status in {"", "closed", "done"}
            dependency_finalized_cache[issue_id] = finalized
            return finalized
        if "cs:merged" not in labels:
            dependency_finalized_cache[issue_id] = False
            return False
        integrated, _ = _changeset_integration_signal(
            issue, repo_slug=repo_slug, repo_root=repo_root, git_path=git_path
        )
        dependency_finalized_cache[issue_id] = integrated
        return integrated

    remaining = set(candidates)
    reconciled_ids: set[str] = set()
    failed_ids: set[str] = set()
    epics_ready_to_finalize: set[str] = set()

    while remaining:
        progressed = False
        for changeset_id in sorted(remaining):
            candidate = candidates[changeset_id]
            dependency_waiting = False
            dependency_errors: list[str] = []
            for dependency_id in candidate.dependency_ids:
                if dependency_id in reconciled_ids:
                    continue
                if dependency_id in failed_ids:
                    dependency_waiting = True
                    dependency_errors.append(f"{dependency_id}(failed)")
                    continue
                if dependency_id in candidates:
                    dependency_waiting = True
                    dependency_errors.append(dependency_id)
                    continue
                if not dependency_finalized(dependency_id):
                    dependency_waiting = True
                    dependency_errors.append(dependency_id)
            if dependency_waiting:
                if log:
                    log(
                        "reconcile defer: "
                        f"{changeset_id} (waiting on dependencies: "
                        f"{', '.join(dependency_errors)})"
                    )
                continue
            remaining.remove(changeset_id)
            progressed = True
            if dry_run:
                reconciled += 1
                reconciled_ids.add(changeset_id)
                if log:
                    log(
                        f"reconcile dry-run: {changeset_id} -> epic={candidate.epic_id}"
                        + (
                            f" integrated_sha={candidate.integrated_sha}"
                            if candidate.integrated_sha
                            else ""
                        )
                    )
                continue
            if candidate.status == "closed":
                if candidate.integrated_sha:
                    beads.update_changeset_integrated_sha(
                        changeset_id,
                        candidate.integrated_sha,
                        beads_root=beads_root,
                        cwd=repo_root,
                    )
                if log:
                    log(
                        f"reconcile ok: {changeset_id} -> epic={candidate.epic_id} "
                        "(already closed)"
                    )
                reconciled += 1
                reconciled_ids.add(changeset_id)
                epics_ready_to_finalize.add(candidate.epic_id)
                continue

            hook_agent_bead_id = _resolve_hook_agent_bead_for_epic(
                candidate.epic_id,
                fallback_agent_bead_id=agent_bead_id,
                beads_root=beads_root,
                repo_root=repo_root,
            )
            finalize_result = _finalize_changeset(
                changeset_id=candidate.issue_id,
                epic_id=candidate.epic_id,
                agent_id=agent_id,
                agent_bead_id=hook_agent_bead_id or "",
                started_at=started_at,
                repo_slug=repo_slug,
                beads_root=beads_root,
                repo_root=repo_root,
                branch_pr=project_config.branch.pr,
                branch_pr_strategy=project_config.branch.pr_strategy,
                branch_history=project_config.branch.history,
                branch_squash_message=project_config.branch.squash_message,
                project_data_dir=project_data_dir,
                git_path=git_path,
            )
            if "_blocked_" in finalize_result.reason:
                failed += 1
                failed_ids.add(changeset_id)
                if log:
                    log(
                        f"reconcile error: {changeset_id} "
                        f"(finalize reason={finalize_result.reason})"
                    )
                continue
            if candidate.integrated_sha:
                beads.update_changeset_integrated_sha(
                    changeset_id,
                    candidate.integrated_sha,
                    beads_root=beads_root,
                    cwd=repo_root,
                )
            if log:
                log(
                    f"reconcile ok: {changeset_id} -> epic={candidate.epic_id} "
                    f"(finalize reason={finalize_result.reason})"
                )
            reconciled += 1
            reconciled_ids.add(changeset_id)
        if not progressed:
            break

    for changeset_id in sorted(remaining):
        candidate = candidates[changeset_id]
        blockers: list[str] = []
        for dependency_id in candidate.dependency_ids:
            if dependency_id in reconciled_ids:
                continue
            if dependency_id in failed_ids:
                blockers.append(f"{dependency_id}(failed)")
                continue
            if dependency_id in candidates:
                blockers.append(dependency_id)
                continue
            if not dependency_finalized(dependency_id):
                blockers.append(dependency_id)
        failed += 1
        failed_ids.add(changeset_id)
        if log:
            if blockers:
                log(
                    f"reconcile error: {changeset_id} "
                    f"(blocked by dependencies: {', '.join(blockers)})"
                )
            else:
                log(f"reconcile error: {changeset_id} (dependency order unresolved)")

    if not dry_run:
        for epic_id in sorted(epics_ready_to_finalize):
            hook_agent_bead_id = _resolve_hook_agent_bead_for_epic(
                epic_id,
                fallback_agent_bead_id=agent_bead_id,
                beads_root=beads_root,
                repo_root=repo_root,
            )
            epic_result = _finalize_epic_if_complete(
                epic_id=epic_id,
                agent_id=agent_id,
                agent_bead_id=hook_agent_bead_id or "",
                branch_pr=project_config.branch.pr,
                branch_history=project_config.branch.history,
                branch_squash_message=project_config.branch.squash_message,
                beads_root=beads_root,
                repo_root=repo_root,
                project_data_dir=project_data_dir,
                git_path=git_path,
                log=log,
            )
            if "_blocked_" in epic_result.reason:
                failed += 1
                if log:
                    log(
                        f"reconcile error: epic {epic_id} "
                        f"(finalize reason={epic_result.reason})"
                    )
                continue
            if log:
                log(f"reconcile epic: {epic_id} (finalize reason={epic_result.reason})")

    return ReconcileResult(
        scanned=scanned,
        actionable=actionable,
        reconciled=reconciled,
        failed=failed,
    )


def _epic_ready_to_finalize(epic_id: str, *, beads_root: Path, repo_root: Path) -> bool:
    issues = beads.run_bd_json(["show", epic_id], beads_root=beads_root, cwd=repo_root)
    if not issues:
        return False
    issue = issues[0]
    labels = _issue_labels(issue)
    if "at:changeset" in labels and ("cs:merged" in labels or "cs:abandoned" in labels):
        return True
    summary = beads.epic_changeset_summary(
        epic_id, beads_root=beads_root, cwd=repo_root
    )
    return summary.ready_to_close


def _ensure_local_branch(
    branch: str, *, repo_root: Path, git_path: str | None = None
) -> bool:
    branch_name = branch.strip()
    if not branch_name:
        return False
    if git.git_ref_exists(repo_root, f"refs/heads/{branch_name}", git_path=git_path):
        return True
    if not git.git_ref_exists(
        repo_root, f"refs/remotes/origin/{branch_name}", git_path=git_path
    ):
        return False
    result = exec.try_run_command(
        git.git_command(
            [
                "-C",
                str(repo_root),
                "branch",
                branch_name,
                f"origin/{branch_name}",
            ],
            git_path=git_path,
        )
    )
    return bool(result and result.returncode == 0)


def _run_git_status(
    args: list[str],
    *,
    repo_root: Path,
    git_path: str | None = None,
    cwd: Path | None = None,
) -> tuple[bool, str]:
    target_cwd = cwd or repo_root
    result = exec.try_run_command(
        git.git_command(["-C", str(target_cwd), *args], git_path=git_path)
    )
    if result is None:
        return False, "missing required command: git"
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        return False, detail or f"command failed: git {' '.join(args)}"
    return True, (result.stdout or "").strip()


def _resolve_epic_integration_cwd(
    *,
    project_data_dir: Path | None,
    repo_root: Path,
    epic_id: str,
    root_branch: str,
    git_path: str | None = None,
) -> Path:
    """Prefer the epic worktree when it has the root branch checked out."""
    if project_data_dir is None or not epic_id:
        return repo_root
    mapping = worktrees.load_mapping(worktrees.mapping_path(project_data_dir, epic_id))
    if mapping is None or not mapping.worktree_path:
        return repo_root
    worktree_path = Path(mapping.worktree_path)
    if not worktree_path.is_absolute():
        worktree_path = project_data_dir / worktree_path
    if not worktree_path.exists() or not (worktree_path / ".git").exists():
        return repo_root
    current_branch = git.git_current_branch(worktree_path, git_path=git_path)
    if current_branch == root_branch:
        return worktree_path
    return repo_root


def _resolve_changeset_worktree_path(
    *,
    project_data_dir: Path | None,
    epic_id: str,
    changeset_id: str,
) -> Path | None:
    if project_data_dir is None or not epic_id or not changeset_id:
        return None
    mapping = worktrees.load_mapping(worktrees.mapping_path(project_data_dir, epic_id))
    if mapping is None:
        return None
    relpath = mapping.changeset_worktrees.get(changeset_id)
    if not relpath:
        return None
    worktree_path = Path(relpath)
    if not worktree_path.is_absolute():
        worktree_path = project_data_dir / worktree_path
    if not worktree_path.exists() or not (worktree_path / ".git").exists():
        return None
    return worktree_path


def _collect_publish_signal_diagnostics(
    *,
    work_branch: str,
    epic_id: str,
    changeset_id: str,
    project_data_dir: Path | None,
    repo_root: Path,
    git_path: str | None,
) -> _PublishSignalDiagnostics:
    local_branch_exists = git.git_ref_exists(
        repo_root, f"refs/heads/{work_branch}", git_path=git_path
    )
    remote_branch_exists = git.git_ref_exists(
        repo_root, f"refs/remotes/origin/{work_branch}", git_path=git_path
    )
    worktree_path = _resolve_changeset_worktree_path(
        project_data_dir=project_data_dir,
        epic_id=epic_id,
        changeset_id=changeset_id,
    )
    status_root = worktree_path or repo_root
    dirty_entries = tuple(git.git_status_porcelain(status_root, git_path=git_path))
    return _PublishSignalDiagnostics(
        local_branch_exists=local_branch_exists,
        remote_branch_exists=remote_branch_exists,
        worktree_path=worktree_path,
        dirty_entries=dirty_entries,
    )


def _attempt_push_work_branch(
    work_branch: str, *, repo_root: Path, git_path: str | None = None
) -> tuple[bool, str]:
    if not git.git_ref_exists(
        repo_root, f"refs/heads/{work_branch}", git_path=git_path
    ):
        return False, f"local branch missing: {work_branch}"
    ok, detail = _run_git_status(
        ["push", "-u", "origin", work_branch], repo_root=repo_root, git_path=git_path
    )
    if ok:
        return True, detail or f"pushed {work_branch} to origin"
    return False, detail


def _format_publish_diagnostics(
    diagnostics: _PublishSignalDiagnostics, *, push_detail: str | None = None
) -> str:
    lines = [
        f"- local branch exists: {'yes' if diagnostics.local_branch_exists else 'no'}",
        f"- remote branch exists: {'yes' if diagnostics.remote_branch_exists else 'no'}",
    ]
    if diagnostics.worktree_path is not None:
        lines.append(f"- changeset worktree: {diagnostics.worktree_path}")
    if diagnostics.dirty_entries:
        lines.append("- dirty files:")
        for entry in diagnostics.dirty_entries[:8]:
            lines.append(f"  - {entry}")
        if len(diagnostics.dirty_entries) > 8:
            lines.append(f"  - ... (+{len(diagnostics.dirty_entries) - 8} more)")
    if push_detail:
        lines.append(f"- push attempt: {push_detail}")
    return "\n".join(lines)


def _ensure_branch_not_checked_out(
    branch: str, *, repo_root: Path, git_path: str | None = None
) -> None:
    current = git.git_current_branch(repo_root, git_path=git_path)
    if current != branch:
        return
    _run_git_status(["checkout", "--detach"], repo_root=repo_root, git_path=git_path)


def _sync_local_branch_from_remote(
    branch: str, *, repo_root: Path, git_path: str | None = None
) -> bool:
    branch_name = branch.strip()
    if not branch_name:
        return False
    if not git.git_ref_exists(
        repo_root, f"refs/remotes/origin/{branch_name}", git_path=git_path
    ):
        return False
    _ensure_branch_not_checked_out(branch_name, repo_root=repo_root, git_path=git_path)
    ok, _ = _run_git_status(
        ["branch", "-f", branch_name, f"origin/{branch_name}"],
        repo_root=repo_root,
        git_path=git_path,
    )
    return ok


def _first_external_ticket_id(issue: dict[str, object]) -> str | None:
    description = issue.get("description")
    tickets = beads.parse_external_tickets(
        description if isinstance(description, str) else None
    )
    if not tickets:
        return None
    primary = [ticket for ticket in tickets if ticket.relation == "primary"]
    source = primary or tickets
    for ticket in source:
        ticket_id = (ticket.ticket_id or "").strip()
        if ticket_id:
            return ticket_id
    return None


def _squash_subject(issue: dict[str, object], *, epic_id: str) -> str:
    ticket_id = _first_external_ticket_id(issue)
    title = str(issue.get("title") or "").strip()
    if ticket_id and title:
        return f"{ticket_id}: {title}"
    if ticket_id:
        return ticket_id
    if title:
        return title
    return epic_id


def _normalize_squash_message_mode(value: object) -> str:
    if not isinstance(value, str):
        return "deterministic"
    normalized = value.strip().lower()
    if normalized in _SQUASH_MESSAGE_MODES:
        return normalized
    return "deterministic"


def _parse_squash_subject_output(output: str) -> str | None:
    cleaned = codex.strip_ansi(output).replace("\r", "\n")
    for raw_line in cleaned.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        lowered = line.lower()
        if lowered in {"thinking", "user", "assistant", "codex", "--------"}:
            continue
        if lowered.startswith(
            (
                "warning:",
                "deprecated:",
                "mcp:",
                "tokens used",
                "openai codex",
                "session id:",
            )
        ):
            continue
        line = line.strip("`\"'").strip()
        if line.startswith(("-", "*")):
            line = line[1:].strip()
        line = " ".join(line.split())
        if line:
            return line[:120]
    return None


def _agent_generated_squash_subject(
    *,
    epic_issue: dict[str, object],
    epic_id: str,
    root_branch: str,
    parent_branch: str,
    repo_root: Path,
    git_path: str | None,
    agent_spec: agents.AgentSpec | None,
    agent_options: list[str] | None,
    agent_home: Path | None,
    agent_env: dict[str, str] | None,
) -> str | None:
    if agent_spec is None or agent_home is None:
        return None
    if agent_spec.name != "codex":
        return None

    commit_messages = git.git_commit_messages(
        repo_root,
        parent_branch,
        root_branch,
        git_path=git_path,
    )
    files_changed = git.git_diff_name_status(
        repo_root,
        parent_branch,
        root_branch,
        git_path=git_path,
    )
    ticket_id = _first_external_ticket_id(epic_issue) or "none"
    title = str(epic_issue.get("title") or epic_id).strip() or epic_id
    commits_preview = (
        "\n".join(f"- {message}" for message in commit_messages[:12] if message)
        or "- (none)"
    )
    files_preview = "\n".join(
        f"- {entry}" for entry in files_changed[:30] if entry
    ) or ("- (none)")
    prompt_text = "\n".join(
        [
            "Draft a single git squash commit subject for integrating an epic branch.",
            "",
            "Constraints:",
            "- Output exactly one line (no markdown, no bullets, no quotes).",
            "- Imperative mood, no trailing period.",
            "- Maximum 72 characters.",
            "",
            f"Epic id: {epic_id}",
            f"Primary ticket: {ticket_id}",
            f"Epic title: {title}",
            f"Parent branch: {parent_branch}",
            f"Root branch: {root_branch}",
            "",
            "Commit messages being squashed:",
            commits_preview,
            "",
            "Changed files:",
            files_preview,
            "",
            "Return only the commit subject.",
        ]
    )

    start_cmd, start_cwd = agent_spec.build_start_command(
        agent_home,
        list(agent_options or []),
        prompt_text,
    )
    start_cmd = _with_codex_exec(start_cmd, prompt_text)
    start_cmd = _strip_flag_with_value(start_cmd, "--cd")
    start_cmd = _ensure_exec_subcommand_flag(start_cmd, "--skip-git-repo-check")
    start_cwd = agent_home
    result = exec.try_run_command(start_cmd, cwd=start_cwd, env=agent_env)
    if result is None or result.returncode != 0:
        return None
    parsed = _parse_squash_subject_output(result.stdout or "")
    if parsed:
        return parsed
    return _parse_squash_subject_output(result.stderr or "")


def _cleanup_epic_branches_and_worktrees(
    *,
    project_data_dir: Path | None,
    repo_root: Path,
    epic_id: str,
    keep_branches: set[str] | None = None,
    git_path: str | None = None,
    log: Callable[[str], None] | None = None,
) -> None:
    keep = {branch for branch in (keep_branches or set()) if branch}
    if project_data_dir is None:
        if log:
            log(f"cleanup skip: {epic_id} (project data dir unavailable)")
        return
    mapping_path = worktrees.mapping_path(project_data_dir, epic_id)
    mapping = worktrees.load_mapping(mapping_path)
    if mapping is None:
        if log:
            log(f"cleanup skip: {epic_id} (no worktree mapping)")
        return

    relpaths = sorted(
        {
            relpath
            for relpath in [
                mapping.worktree_path,
                *mapping.changeset_worktrees.values(),
            ]
            if relpath
        }
    )
    for relpath in relpaths:
        worktree_path = project_data_dir / relpath
        if not worktree_path.exists():
            if log:
                log(f"cleanup skip worktree: {worktree_path} (missing)")
            continue
        if not (worktree_path / ".git").exists():
            if log:
                log(f"cleanup skip worktree: {worktree_path} (not a git worktree)")
            continue
        if log:
            log(f"cleanup remove worktree: {worktree_path}")
        ok, detail = _run_git_status(
            ["worktree", "remove", "--force", str(worktree_path)],
            repo_root=repo_root,
            git_path=git_path,
        )
        if log:
            if ok:
                log(f"cleanup removed worktree: {worktree_path}")
            else:
                log(f"cleanup failed worktree: {worktree_path} ({detail})")

    branches = {mapping.root_branch, *mapping.changesets.values()}
    for branch in branches:
        if not branch or branch in keep:
            if log and branch:
                log(f"cleanup keep branch: {branch}")
            continue
        if log:
            log(f"cleanup delete remote branch: origin/{branch}")
        remote_ok, remote_detail = _run_git_status(
            ["push", "origin", "--delete", branch],
            repo_root=repo_root,
            git_path=git_path,
        )
        if log:
            if remote_ok:
                log(f"cleanup deleted remote branch: origin/{branch}")
            else:
                log(
                    f"cleanup remote branch skip/fail: origin/{branch} ({remote_detail})"
                )
        if log:
            log(f"cleanup delete local branch: {branch}")
        local_ok, local_detail = _run_git_status(
            ["branch", "-D", branch], repo_root=repo_root, git_path=git_path
        )
        if log:
            if local_ok:
                log(f"cleanup deleted local branch: {branch}")
            else:
                log(f"cleanup local branch skip/fail: {branch} ({local_detail})")

    mapping_path.unlink(missing_ok=True)
    if log:
        log(f"cleanup removed mapping: {mapping_path}")


def _integrate_epic_root_to_parent(
    *,
    epic_issue: dict[str, object],
    epic_id: str,
    root_branch: str,
    parent_branch: str,
    history: str,
    squash_message_mode: str = "deterministic",
    squash_message_agent_spec: agents.AgentSpec | None = None,
    squash_message_agent_options: list[str] | None = None,
    squash_message_agent_home: Path | None = None,
    squash_message_agent_env: dict[str, str] | None = None,
    integration_cwd: Path | None = None,
    repo_root: Path,
    git_path: str | None = None,
) -> tuple[bool, str | None, str | None]:
    root = root_branch.strip()
    parent = parent_branch.strip()
    if not root or not parent:
        return False, None, "missing root/parent branch metadata"
    if parent == root:
        return True, git.git_rev_parse(repo_root, root, git_path=git_path), None
    if not _ensure_local_branch(root, repo_root=repo_root, git_path=git_path):
        return False, None, f"root branch {root!r} not found"
    if not _ensure_local_branch(parent, repo_root=repo_root, git_path=git_path):
        return False, None, f"parent branch {parent!r} not found"

    operation_cwd = integration_cwd or repo_root
    clean = git.git_is_clean(operation_cwd, git_path=git_path)
    if clean is False:
        return False, None, "repository must be clean before epic finalization"

    for attempt in range(2):
        parent_head = git.git_rev_parse(repo_root, parent, git_path=git_path)
        if not parent_head:
            return False, None, f"failed to resolve parent branch head for {parent!r}"

        is_ancestor = git.git_is_ancestor(repo_root, root, parent, git_path=git_path)
        if is_ancestor is True:
            return True, parent_head, None
        fully_applied = git.git_branch_fully_applied(
            repo_root, parent, root, git_path=git_path
        )
        if fully_applied is True:
            return True, parent_head, None

        can_ff = git.git_is_ancestor(repo_root, parent, root, git_path=git_path) is True

        if history == "rebase":
            rebase_args = ["rebase", parent, root]
            if operation_cwd != repo_root:
                current_branch = git.git_current_branch(
                    operation_cwd, git_path=git_path
                )
                if current_branch == root:
                    rebase_args = ["rebase", parent]
            ok, detail = _run_git_status(
                rebase_args,
                repo_root=repo_root,
                git_path=git_path,
                cwd=operation_cwd,
            )
            if not ok:
                _run_git_status(
                    ["rebase", "--abort"],
                    repo_root=repo_root,
                    git_path=git_path,
                    cwd=operation_cwd,
                )
                return False, None, detail or f"failed to rebase {root} onto {parent}"
            new_head = git.git_rev_parse(repo_root, root, git_path=git_path)
            if not new_head:
                return False, None, f"failed to resolve rebased head for {root!r}"
            ok, detail = _run_git_status(
                ["update-ref", f"refs/heads/{parent}", new_head, parent_head],
                repo_root=repo_root,
                git_path=git_path,
            )
            if not ok:
                if attempt == 0 and _sync_local_branch_from_remote(
                    parent, repo_root=repo_root, git_path=git_path
                ):
                    continue
                return False, None, detail or "parent branch moved during finalization"
            ok, detail = _run_git_status(
                ["push", "origin", parent], repo_root=repo_root, git_path=git_path
            )
            if ok:
                return True, new_head, None
            if attempt == 0 and _sync_local_branch_from_remote(
                parent, repo_root=repo_root, git_path=git_path
            ):
                continue
            return False, None, detail or f"failed to push {parent} to origin"

        if history == "merge":
            if can_ff:
                new_head = git.git_rev_parse(repo_root, root, git_path=git_path)
                if not new_head:
                    return False, None, f"failed to resolve head for {root!r}"
                ok, detail = _run_git_status(
                    ["update-ref", f"refs/heads/{parent}", new_head, parent_head],
                    repo_root=repo_root,
                    git_path=git_path,
                )
                if not ok:
                    if attempt == 0 and _sync_local_branch_from_remote(
                        parent, repo_root=repo_root, git_path=git_path
                    ):
                        continue
                    return (
                        False,
                        None,
                        detail or "parent branch moved during finalization",
                    )
            else:
                current = git.git_current_branch(repo_root, git_path=git_path)
                ok, detail = _run_git_status(
                    ["checkout", parent], repo_root=repo_root, git_path=git_path
                )
                if not ok:
                    return False, None, detail
                ok, detail = _run_git_status(
                    ["merge", "--no-edit", root], repo_root=repo_root, git_path=git_path
                )
                if current and current != parent:
                    _run_git_status(
                        ["checkout", current], repo_root=repo_root, git_path=git_path
                    )
                if not ok:
                    _run_git_status(
                        ["merge", "--abort"], repo_root=repo_root, git_path=git_path
                    )
                    return (
                        False,
                        None,
                        detail or f"failed to merge {root} into {parent}",
                    )
            ok, detail = _run_git_status(
                ["push", "origin", parent], repo_root=repo_root, git_path=git_path
            )
            if ok:
                return (
                    True,
                    git.git_rev_parse(repo_root, parent, git_path=git_path),
                    None,
                )
            if attempt == 0 and _sync_local_branch_from_remote(
                parent, repo_root=repo_root, git_path=git_path
            ):
                continue
            return False, None, detail or f"failed to push {parent} to origin"

        if history == "squash":
            current = git.git_current_branch(repo_root, git_path=git_path)
            ok, detail = _run_git_status(
                ["checkout", parent], repo_root=repo_root, git_path=git_path
            )
            if not ok:
                return False, None, detail
            ok, detail = _run_git_status(
                ["merge", "--squash", root], repo_root=repo_root, git_path=git_path
            )
            if not ok:
                _run_git_status(
                    ["merge", "--abort"], repo_root=repo_root, git_path=git_path
                )
                if current and current != parent:
                    _run_git_status(
                        ["checkout", current], repo_root=repo_root, git_path=git_path
                    )
                return (
                    False,
                    None,
                    detail or f"failed to squash-merge {root} into {parent}",
                )
            message = _squash_subject(epic_issue, epic_id=epic_id)
            if _normalize_squash_message_mode(squash_message_mode) == "agent":
                drafted = _agent_generated_squash_subject(
                    epic_issue=epic_issue,
                    epic_id=epic_id,
                    root_branch=root,
                    parent_branch=parent,
                    repo_root=repo_root,
                    git_path=git_path,
                    agent_spec=squash_message_agent_spec,
                    agent_options=squash_message_agent_options,
                    agent_home=squash_message_agent_home,
                    agent_env=squash_message_agent_env,
                )
                if drafted:
                    message = drafted
            ok, detail = _run_git_status(
                ["commit", "-m", message], repo_root=repo_root, git_path=git_path
            )
            if current and current != parent:
                _run_git_status(
                    ["checkout", current], repo_root=repo_root, git_path=git_path
                )
            if not ok:
                _run_git_status(
                    ["merge", "--abort"], repo_root=repo_root, git_path=git_path
                )
                return (
                    False,
                    None,
                    detail or f"failed to create squash commit on {parent}",
                )
            ok, detail = _run_git_status(
                ["push", "origin", parent], repo_root=repo_root, git_path=git_path
            )
            if ok:
                return (
                    True,
                    git.git_rev_parse(repo_root, parent, git_path=git_path),
                    None,
                )
            if attempt == 0 and _sync_local_branch_from_remote(
                parent, repo_root=repo_root, git_path=git_path
            ):
                continue
            return False, None, detail or f"failed to push {parent} to origin"

        return False, None, f"unsupported branch.history value: {history!r}"

    return False, None, "epic finalization failed after retry"


def _finalize_epic_if_complete(
    *,
    epic_id: str,
    agent_id: str,
    agent_bead_id: str,
    branch_pr: bool,
    branch_history: str,
    branch_squash_message: str = "deterministic",
    beads_root: Path,
    repo_root: Path,
    project_data_dir: Path | None = None,
    squash_message_agent_spec: agents.AgentSpec | None = None,
    squash_message_agent_options: list[str] | None = None,
    squash_message_agent_home: Path | None = None,
    squash_message_agent_env: dict[str, str] | None = None,
    git_path: str | None = None,
    log: Callable[[str], None] | None = None,
) -> FinalizeResult:
    if not _epic_ready_to_finalize(epic_id, beads_root=beads_root, repo_root=repo_root):
        return FinalizeResult(continue_running=True, reason="changeset_complete")

    if not branch_pr:
        issues = beads.run_bd_json(
            ["show", epic_id], beads_root=beads_root, cwd=repo_root
        )
        if not issues:
            return FinalizeResult(
                continue_running=False, reason="epic_blocked_missing_metadata"
            )
        issue = issues[0]
        fields = beads.parse_description_fields(
            issue.get("description")
            if isinstance(issue.get("description"), str)
            else ""
        )
        root_branch = _normalize_branch_value(fields.get("workspace.root_branch"))
        if not root_branch:
            root_branch = _normalize_branch_value(fields.get("changeset.root_branch"))
        parent_branch = _normalize_branch_value(fields.get("workspace.parent_branch"))
        default_branch = git.git_default_branch(repo_root, git_path=git_path)
        if not parent_branch or (root_branch and parent_branch == root_branch):
            parent_branch = default_branch or parent_branch or root_branch

        if not root_branch or not parent_branch:
            _send_planner_notification(
                subject=f"NEEDS-DECISION: Missing epic branch metadata ({epic_id})",
                body="Epic is complete but root/parent branch metadata is missing.",
                agent_id=agent_id,
                thread_id=epic_id,
                beads_root=beads_root,
                repo_root=repo_root,
                dry_run=False,
            )
            return FinalizeResult(
                continue_running=False, reason="epic_blocked_missing_metadata"
            )

        # Keep workspace.parent_branch aligned with final integration target.
        beads.update_workspace_parent_branch(
            epic_id,
            parent_branch,
            beads_root=beads_root,
            cwd=repo_root,
            allow_override=True,
        )
        integration_cwd = _resolve_epic_integration_cwd(
            project_data_dir=project_data_dir,
            repo_root=repo_root,
            epic_id=epic_id,
            root_branch=root_branch,
            git_path=git_path,
        )

        integrated_ok, _integrated_sha, error = _integrate_epic_root_to_parent(
            epic_issue=issue,
            epic_id=epic_id,
            root_branch=root_branch,
            parent_branch=parent_branch,
            history=branch_history,
            squash_message_mode=branch_squash_message,
            squash_message_agent_spec=squash_message_agent_spec,
            squash_message_agent_options=squash_message_agent_options,
            squash_message_agent_home=squash_message_agent_home,
            squash_message_agent_env=squash_message_agent_env,
            integration_cwd=integration_cwd,
            repo_root=repo_root,
            git_path=git_path,
        )
        if not integrated_ok:
            _send_planner_notification(
                subject=f"NEEDS-DECISION: Epic finalization failed ({epic_id})",
                body=(
                    "Epic changesets are complete, but final integration of "
                    f"{root_branch} -> {parent_branch} failed.\n"
                    f"Reason: {error or 'unknown error'}"
                ),
                agent_id=agent_id,
                thread_id=epic_id,
                beads_root=beads_root,
                repo_root=repo_root,
                dry_run=False,
            )
            return FinalizeResult(
                continue_running=False, reason="epic_blocked_finalization"
            )

    closed = beads.close_epic_if_complete(
        epic_id, agent_bead_id, beads_root=beads_root, cwd=repo_root
    )
    if closed:
        if log:
            log(f"finalize epic: {epic_id} closed; pruning mapped artifacts")
        _cleanup_epic_branches_and_worktrees(
            project_data_dir=project_data_dir,
            repo_root=repo_root,
            epic_id=epic_id,
            keep_branches={parent_branch} if "parent_branch" in locals() else set(),
            git_path=git_path,
            log=log,
        )
    return FinalizeResult(continue_running=True, reason="changeset_complete")


def _finalize_terminal_changeset(
    *,
    changeset_id: str,
    epic_id: str,
    agent_id: str,
    agent_bead_id: str,
    terminal_state: str,
    integrated_sha: str | None,
    branch_pr: bool,
    branch_history: str,
    branch_squash_message: str,
    beads_root: Path,
    repo_root: Path,
    project_data_dir: Path | None,
    squash_message_agent_spec: agents.AgentSpec | None,
    squash_message_agent_options: list[str] | None,
    squash_message_agent_home: Path | None,
    squash_message_agent_env: dict[str, str] | None,
    git_path: str | None,
) -> FinalizeResult:
    if terminal_state == "merged":
        _mark_changeset_merged(changeset_id, beads_root=beads_root, repo_root=repo_root)
        if integrated_sha and integrated_sha.strip():
            beads.update_changeset_integrated_sha(
                changeset_id,
                integrated_sha.strip(),
                beads_root=beads_root,
                cwd=repo_root,
                allow_override=True,
            )
    elif terminal_state == "abandoned":
        _mark_changeset_abandoned(
            changeset_id, beads_root=beads_root, repo_root=repo_root
        )
    else:
        die(f"unsupported terminal changeset state: {terminal_state!r}")
    _close_completed_container_changesets(
        epic_id, beads_root=beads_root, repo_root=repo_root
    )
    return _finalize_epic_if_complete(
        epic_id=epic_id,
        agent_id=agent_id,
        agent_bead_id=agent_bead_id,
        branch_pr=branch_pr,
        branch_history=branch_history,
        branch_squash_message=branch_squash_message,
        beads_root=beads_root,
        repo_root=repo_root,
        project_data_dir=project_data_dir,
        squash_message_agent_spec=squash_message_agent_spec,
        squash_message_agent_options=squash_message_agent_options,
        squash_message_agent_home=squash_message_agent_home,
        squash_message_agent_env=squash_message_agent_env,
        git_path=git_path,
        log=say,
    )


def _finalize_changeset(
    *,
    changeset_id: str,
    epic_id: str,
    agent_id: str,
    agent_bead_id: str,
    started_at: dt.datetime,
    repo_slug: str | None,
    beads_root: Path,
    repo_root: Path,
    branch_pr: bool = True,
    branch_pr_strategy: object = pr_strategy.PR_STRATEGY_DEFAULT,
    branch_history: str = "manual",
    branch_squash_message: str = "deterministic",
    project_data_dir: Path | None = None,
    squash_message_agent_spec: agents.AgentSpec | None = None,
    squash_message_agent_options: list[str] | None = None,
    squash_message_agent_home: Path | None = None,
    squash_message_agent_env: dict[str, str] | None = None,
    git_path: str | None = None,
) -> FinalizeResult:
    if not changeset_id:
        return FinalizeResult(continue_running=False, reason="changeset_missing")
    issues = beads.run_bd_json(
        ["show", changeset_id], beads_root=beads_root, cwd=repo_root
    )
    if not issues:
        return FinalizeResult(continue_running=False, reason="changeset_not_found")
    issue = issues[0]
    labels = _issue_labels(issue)
    invalid_changesets = _find_invalid_changeset_labels(
        epic_id, beads_root=beads_root, repo_root=repo_root
    )
    if invalid_changesets:
        _send_invalid_changeset_labels_notification(
            epic_id=epic_id,
            invalid_changesets=invalid_changesets,
            agent_id=agent_id,
            beads_root=beads_root,
            repo_root=repo_root,
            dry_run=False,
        )
        return FinalizeResult(
            continue_running=False, reason="changeset_label_violation"
        )
    if "cs:merged" in labels or "cs:abandoned" in labels:
        if _has_open_descendant_changesets(
            changeset_id, beads_root=beads_root, repo_root=repo_root
        ):
            descendants = beads.list_descendant_changesets(
                changeset_id,
                beads_root=beads_root,
                cwd=repo_root,
                include_closed=False,
            )
            planned_ids = {
                issue_id
                for issue in descendants
                if isinstance((issue_id := issue.get("id")), str)
                and issue_id
                and "cs:planned" in _issue_labels(issue)
            }
            if planned_ids and _has_blocking_messages(
                thread_ids={changeset_id, epic_id, *planned_ids},
                started_at=started_at,
                beads_root=beads_root,
                repo_root=repo_root,
            ):
                _mark_changeset_children_in_progress(
                    changeset_id, beads_root=beads_root, repo_root=repo_root
                )
                _close_completed_container_changesets(
                    epic_id, beads_root=beads_root, repo_root=repo_root
                )
                return FinalizeResult(
                    continue_running=False, reason="changeset_children_planning_blocked"
                )
            _promote_planned_descendant_changesets(
                changeset_id, beads_root=beads_root, repo_root=repo_root
            )
            _mark_changeset_children_in_progress(
                changeset_id, beads_root=beads_root, repo_root=repo_root
            )
            _close_completed_container_changesets(
                epic_id, beads_root=beads_root, repo_root=repo_root
            )
            return FinalizeResult(
                continue_running=True, reason="changeset_children_pending"
            )
        if "cs:merged" in labels:
            integration_proven, integrated_sha = _changeset_integration_signal(
                issue, repo_slug=repo_slug, repo_root=repo_root, git_path=git_path
            )
            if not integration_proven:
                _mark_changeset_blocked(
                    changeset_id,
                    beads_root=beads_root,
                    repo_root=repo_root,
                    reason="missing integration signal for cs:merged",
                )
                _send_planner_notification(
                    subject=f"NEEDS-DECISION: Missing integration signal ({changeset_id})",
                    body="Changeset is labeled cs:merged but no integration signal "
                    "(changeset.integrated_sha or merged PR) was found.",
                    agent_id=agent_id,
                    thread_id=changeset_id,
                    beads_root=beads_root,
                    repo_root=repo_root,
                    dry_run=False,
                )
                return FinalizeResult(
                    continue_running=False,
                    reason="changeset_blocked_missing_integration",
                )
            if integrated_sha and integrated_sha.strip():
                beads.update_changeset_integrated_sha(
                    changeset_id,
                    integrated_sha.strip(),
                    beads_root=beads_root,
                    cwd=repo_root,
                )
        _mark_changeset_closed(changeset_id, beads_root=beads_root, repo_root=repo_root)
        _close_completed_container_changesets(
            epic_id, beads_root=beads_root, repo_root=repo_root
        )
        return _finalize_epic_if_complete(
            epic_id=epic_id,
            agent_id=agent_id,
            agent_bead_id=agent_bead_id,
            branch_pr=branch_pr,
            branch_history=branch_history,
            branch_squash_message=branch_squash_message,
            beads_root=beads_root,
            repo_root=repo_root,
            project_data_dir=project_data_dir,
            squash_message_agent_spec=squash_message_agent_spec,
            squash_message_agent_options=squash_message_agent_options,
            squash_message_agent_home=squash_message_agent_home,
            squash_message_agent_env=squash_message_agent_env,
            git_path=git_path,
            log=say,
        )
    if _has_blocking_messages(
        thread_ids={changeset_id, epic_id},
        started_at=started_at,
        beads_root=beads_root,
        repo_root=repo_root,
    ):
        _mark_changeset_blocked(
            changeset_id,
            beads_root=beads_root,
            repo_root=repo_root,
            reason="message requires planner decision",
        )
        return FinalizeResult(
            continue_running=False, reason="changeset_blocked_message"
        )
    if "cs:in_progress" in labels:
        if _changeset_waiting_on_review_or_signals(
            issue,
            repo_slug=repo_slug,
            repo_root=repo_root,
            branch_pr=branch_pr,
            branch_pr_strategy=branch_pr_strategy,
            git_path=git_path,
        ):
            return FinalizeResult(
                continue_running=True, reason="changeset_review_pending"
            )
        # Keep evaluating publish signals and PR lifecycle below.
    description = issue.get("description")
    fields = beads.parse_description_fields(
        description if isinstance(description, str) else ""
    )
    work_branch = fields.get("changeset.work_branch")
    if not work_branch or work_branch.strip().lower() == "null":
        _mark_changeset_blocked(
            changeset_id,
            beads_root=beads_root,
            repo_root=repo_root,
            reason="missing changeset.work_branch metadata",
        )
        _send_planner_notification(
            subject=f"NEEDS-DECISION: Missing changeset metadata ({changeset_id})",
            body="Missing changeset.work_branch metadata needed to validate publish.",
            agent_id=agent_id,
            thread_id=changeset_id,
            beads_root=beads_root,
            repo_root=repo_root,
            dry_run=False,
        )
        return FinalizeResult(
            continue_running=False, reason="changeset_blocked_missing_metadata"
        )
    work_branch = work_branch.strip()
    pushed = git.git_ref_exists(
        repo_root, f"refs/remotes/origin/{work_branch}", git_path=git_path
    )
    pr_payload = None
    if repo_slug:
        pr_payload = prs.read_github_pr_status(repo_slug, work_branch)
    lifecycle: str | None = None
    if branch_pr:
        review_requested = prs.has_review_requests(pr_payload)
        lifecycle = prs.lifecycle_state(
            pr_payload, pushed=pushed, review_requested=review_requested
        )
    if lifecycle == "merged":
        _update_changeset_review_from_pr(
            changeset_id,
            pr_payload=pr_payload,
            pushed=pushed,
            beads_root=beads_root,
            repo_root=repo_root,
        )
        _integration_ok, integrated_sha = _changeset_integration_signal(
            issue, repo_slug=None, repo_root=repo_root, git_path=git_path
        )
        return _finalize_terminal_changeset(
            changeset_id=changeset_id,
            epic_id=epic_id,
            agent_id=agent_id,
            agent_bead_id=agent_bead_id,
            terminal_state="merged",
            integrated_sha=integrated_sha,
            branch_pr=branch_pr,
            branch_history=branch_history,
            branch_squash_message=branch_squash_message,
            beads_root=beads_root,
            repo_root=repo_root,
            project_data_dir=project_data_dir,
            squash_message_agent_spec=squash_message_agent_spec,
            squash_message_agent_options=squash_message_agent_options,
            squash_message_agent_home=squash_message_agent_home,
            squash_message_agent_env=squash_message_agent_env,
            git_path=git_path,
        )
    if lifecycle == "closed":
        _update_changeset_review_from_pr(
            changeset_id,
            pr_payload=pr_payload,
            pushed=pushed,
            beads_root=beads_root,
            repo_root=repo_root,
        )
        integration_ok, integrated_sha = _changeset_integration_signal(
            issue, repo_slug=repo_slug, repo_root=repo_root, git_path=git_path
        )
        return _finalize_terminal_changeset(
            changeset_id=changeset_id,
            epic_id=epic_id,
            agent_id=agent_id,
            agent_bead_id=agent_bead_id,
            terminal_state="merged" if integration_ok else "abandoned",
            integrated_sha=integrated_sha if integration_ok else None,
            branch_pr=branch_pr,
            branch_history=branch_history,
            branch_squash_message=branch_squash_message,
            beads_root=beads_root,
            repo_root=repo_root,
            project_data_dir=project_data_dir,
            squash_message_agent_spec=squash_message_agent_spec,
            squash_message_agent_options=squash_message_agent_options,
            squash_message_agent_home=squash_message_agent_home,
            squash_message_agent_env=squash_message_agent_env,
            git_path=git_path,
        )
    if branch_pr and pushed and not pr_payload:
        integration_ok, integrated_sha = _changeset_integration_signal(
            issue, repo_slug=repo_slug, repo_root=repo_root, git_path=git_path
        )
        if integration_ok:
            return _finalize_terminal_changeset(
                changeset_id=changeset_id,
                epic_id=epic_id,
                agent_id=agent_id,
                agent_bead_id=agent_bead_id,
                terminal_state="merged",
                integrated_sha=integrated_sha,
                branch_pr=branch_pr,
                branch_history=branch_history,
                branch_squash_message=branch_squash_message,
                beads_root=beads_root,
                repo_root=repo_root,
                project_data_dir=project_data_dir,
                squash_message_agent_spec=squash_message_agent_spec,
                squash_message_agent_options=squash_message_agent_options,
                squash_message_agent_home=squash_message_agent_home,
                squash_message_agent_env=squash_message_agent_env,
                git_path=git_path,
            )
    if branch_pr and pushed and not pr_payload:
        return _handle_pushed_without_pr(
            issue=issue,
            changeset_id=changeset_id,
            agent_id=agent_id,
            repo_slug=repo_slug,
            repo_root=repo_root,
            beads_root=beads_root,
            branch_pr_strategy=branch_pr_strategy,
            git_path=git_path,
        )
    if not pushed and not pr_payload:
        push_detail: str | None = None
        if branch_pr:
            pushed, push_detail = _attempt_push_work_branch(
                work_branch, repo_root=repo_root, git_path=git_path
            )
            if pushed:
                if repo_slug:
                    pr_payload = prs.read_github_pr_status(repo_slug, work_branch)
                if branch_pr and not pr_payload:
                    return _handle_pushed_without_pr(
                        issue=issue,
                        changeset_id=changeset_id,
                        agent_id=agent_id,
                        repo_slug=repo_slug,
                        repo_root=repo_root,
                        beads_root=beads_root,
                        branch_pr_strategy=branch_pr_strategy,
                        git_path=git_path,
                        create_detail_prefix=push_detail,
                    )
                _update_changeset_review_from_pr(
                    changeset_id,
                    pr_payload=pr_payload,
                    pushed=True,
                    beads_root=beads_root,
                    repo_root=repo_root,
                )
                return FinalizeResult(
                    continue_running=True, reason="changeset_review_pending"
                )

        diagnostics = _collect_publish_signal_diagnostics(
            work_branch=work_branch,
            epic_id=epic_id,
            changeset_id=changeset_id,
            project_data_dir=project_data_dir,
            repo_root=repo_root,
            git_path=git_path,
        )
        diagnostics_text = _format_publish_diagnostics(
            diagnostics, push_detail=push_detail
        )
        if diagnostics.has_recoverable_local_state:
            _mark_changeset_in_progress(
                changeset_id, beads_root=beads_root, repo_root=repo_root
            )
            beads.run_bd_command(
                [
                    "update",
                    changeset_id,
                    "--append-notes",
                    "publish_pending: no push/PR signal after worker completion; "
                    "kept changeset in-progress for retry.",
                ],
                beads_root=beads_root,
                cwd=repo_root,
                allow_failure=True,
            )
            _send_planner_notification(
                subject=f"NEEDS-DECISION: Publish incomplete ({changeset_id})",
                body=(
                    "No push or PR detected after worker completion. "
                    "Recovered to in_progress for retry.\n"
                    f"{diagnostics_text}"
                ),
                agent_id=agent_id,
                thread_id=changeset_id,
                beads_root=beads_root,
                repo_root=repo_root,
                dry_run=False,
            )
            return FinalizeResult(
                continue_running=False, reason="changeset_publish_pending"
            )

        _mark_changeset_blocked(
            changeset_id,
            beads_root=beads_root,
            repo_root=repo_root,
            reason="publish/checks signals missing",
        )
        _send_planner_notification(
            subject=f"NEEDS-DECISION: Publish/checks missing ({changeset_id})",
            body=(
                "No push or PR detected after worker completion and no local "
                "recoverable state found.\n"
                f"{diagnostics_text}"
            ),
            agent_id=agent_id,
            thread_id=changeset_id,
            beads_root=beads_root,
            repo_root=repo_root,
            dry_run=False,
        )
        return FinalizeResult(
            continue_running=False, reason="changeset_blocked_publish_missing"
        )
    if branch_pr and pr_payload:
        _update_changeset_review_from_pr(
            changeset_id,
            pr_payload=pr_payload,
            pushed=pushed,
            beads_root=beads_root,
            repo_root=repo_root,
        )
        return FinalizeResult(continue_running=True, reason="changeset_review_pending")
    return FinalizeResult(continue_running=True, reason="changeset_published")


def _worker_opening_prompt(
    *,
    project_enlistment: str,
    workspace_branch: str,
    epic_id: str,
    changeset_id: str,
    changeset_title: str,
) -> str:
    session = workspace.workspace_session_identifier(
        project_enlistment, workspace_branch, changeset_id or None
    )
    title = changeset_title.strip() if changeset_title else ""
    summary = f"{changeset_id}: {title}" if title else changeset_id
    lines = [
        session,
        ("Execute only this assigned changeset and do not ask for task clarification."),
        f"Epic: {epic_id}",
        f"Changeset: {summary}",
        (
            "When done, update beads state/labels for this changeset. If blocked,"
            " send NEEDS-DECISION with details and exit."
        ),
    ]
    return "\n".join(lines)


def _check_inbox_before_claim(
    agent_id: str, *, beads_root: Path, repo_root: Path
) -> bool:
    inbox = beads.list_inbox_messages(
        agent_id, beads_root=beads_root, cwd=repo_root, unread_only=True
    )
    if inbox:
        say(f"Inbox has {len(inbox)} unread message(s); review before claiming work.")
        return True
    return False


def _prompt_queue_claim(
    queued: list[dict[str, object]],
    *,
    agent_id: str,
    beads_root: Path,
    repo_root: Path,
    assume_yes: bool = False,
) -> bool:
    say("Queued messages:")
    for issue in queued:
        issue_id = issue.get("id") or ""
        queue_name = issue.get("queue") or "queue"
        title = issue.get("title") or ""
        say(f"- {issue_id} [{queue_name}] {title}")
    selection = ""
    if assume_yes:
        first = queued[0].get("id")
        selection = str(first).strip() if first is not None else ""
    else:
        selection = prompt("Queue message id (blank to skip)").strip()
    if not selection:
        return False
    valid_ids = {str(issue.get("id")) for issue in queued if issue.get("id")}
    if selection not in valid_ids:
        die(f"unknown queue message id: {selection}")
    beads.claim_queue_message(selection, agent_id, beads_root=beads_root, cwd=repo_root)
    say(f"Claimed queue message: {selection}")
    return True


def _handle_queue_before_claim(
    agent_id: str,
    *,
    beads_root: Path,
    repo_root: Path,
    queue_name: str | None = _WORKER_QUEUE_NAME,
    force_prompt: bool = False,
    dry_run: bool = False,
    assume_yes: bool = False,
) -> bool:
    queued = beads.list_queue_messages(
        beads_root=beads_root,
        cwd=repo_root,
        queue=queue_name,
        unread_only=True,
    )
    if not queued:
        if force_prompt:
            if dry_run:
                _dry_run_log("No queued messages available.")
            else:
                say("No queued messages available.")
            return True
        return False
    if dry_run:
        say("Queued messages:")
        for issue in queued:
            issue_id = issue.get("id") or ""
            queue_name = issue.get("queue") or "queue"
            title = issue.get("title") or ""
            say(f"- {issue_id} [{queue_name}] {title}")
        _dry_run_log("Would prompt to claim a queue message.")
        return True
    claimed = _prompt_queue_claim(
        queued,
        agent_id=agent_id,
        beads_root=beads_root,
        repo_root=repo_root,
        assume_yes=assume_yes,
    )
    if not claimed:
        say("Skipped queue; continuing to epic selection.")
        return False
    return True


def _run_startup_contract(
    *,
    agent_id: str,
    agent_bead_id: str | None,
    beads_root: Path,
    repo_root: Path,
    mode: str,
    explicit_epic_id: str | None,
    queue_only: bool,
    dry_run: bool,
    assume_yes: bool,
    repo_slug: str | None = None,
    branch_pr: bool = True,
    branch_pr_strategy: object = pr_strategy.PR_STRATEGY_DEFAULT,
    git_path: str | None = None,
) -> StartupContractResult:
    """Apply startup_contract skill ordering to select the next epic."""
    if explicit_epic_id is not None:
        selected_epic = str(explicit_epic_id).strip()
        if not selected_epic:
            die("epic id must not be empty")
        return StartupContractResult(
            epic_id=selected_epic,
            changeset_id=None,
            should_exit=False,
            reason="explicit_epic",
        )

    if queue_only:
        _handle_queue_before_claim(
            agent_id,
            beads_root=beads_root,
            repo_root=repo_root,
            queue_name=_WORKER_QUEUE_NAME,
            force_prompt=True,
            dry_run=dry_run,
            assume_yes=assume_yes,
        )
        if dry_run:
            _dry_run_log("Queue-only run would exit after handling queue.")
        return StartupContractResult(
            epic_id=None, changeset_id=None, should_exit=True, reason="queue_only"
        )

    issues = _list_epics(beads_root=beads_root, repo_root=repo_root)
    actionable_cache: dict[str, bool] = {}

    def epic_has_actionable_changeset(epic_id: str) -> bool:
        cached = actionable_cache.get(epic_id)
        if cached is not None:
            return cached
        actionable = (
            _next_changeset(
                epic_id=epic_id,
                beads_root=beads_root,
                repo_root=repo_root,
                repo_slug=repo_slug,
                branch_pr=branch_pr,
                branch_pr_strategy=branch_pr_strategy,
                git_path=git_path,
            )
            is not None
        )
        actionable_cache[epic_id] = actionable
        return actionable

    hooked_epic = None
    if agent_bead_id:
        hooked_epic = _resolve_hooked_epic(
            agent_bead_id, agent_id, beads_root=beads_root, repo_root=repo_root
        )
    elif dry_run:
        _dry_run_log("Would create agent bead before checking for hooks.")
    assigned = _filter_epics(issues, assignee=agent_id)
    assigned = _sort_by_created_at(assigned)

    stale_assigned = _stale_family_assigned_epics(issues, agent_id=agent_id)
    stale_assignee_by_epic = {
        str(issue.get("id")): str(issue.get("assignee"))
        for issue in stale_assigned
        if isinstance(issue.get("id"), str)
        and issue.get("id")
        and isinstance(issue.get("assignee"), str)
        and issue.get("assignee")
    }

    def stale_reassign_for_epic(epic_id: str) -> str | None:
        assignee = stale_assignee_by_epic.get(epic_id)
        if assignee:
            return assignee
        loaded = beads.run_bd_json(
            ["show", epic_id], beads_root=beads_root, cwd=repo_root
        )
        if not loaded:
            return None
        issue = loaded[0]
        existing_assignee = issue.get("assignee")
        if not isinstance(existing_assignee, str) or not existing_assignee:
            return None
        if existing_assignee == agent_id:
            return None
        if _agent_family_id(existing_assignee) != _agent_family_id(agent_id):
            return None
        if _is_agent_session_active(existing_assignee):
            return None
        return existing_assignee

    def select_feedback_candidate(
        epic_ids: list[str],
    ) -> _ReviewFeedbackSelection | None:
        feedback_candidates: list[_ReviewFeedbackSelection] = []
        seen_epics: set[str] = set()
        for epic_id in epic_ids:
            if epic_id in seen_epics:
                continue
            seen_epics.add(epic_id)
            feedback_selection = _select_review_feedback_changeset(
                epic_id=epic_id,
                repo_slug=repo_slug,
                beads_root=beads_root,
                repo_root=repo_root,
            )
            if feedback_selection is not None:
                feedback_candidates.append(feedback_selection)
        if not feedback_candidates:
            return None
        feedback_candidates.sort(
            key=lambda item: (
                _parse_issue_time(item.feedback_at)
                or dt.datetime.max.replace(tzinfo=dt.timezone.utc)
            )
        )
        return feedback_candidates[0]

    def resume_feedback(selection: _ReviewFeedbackSelection) -> StartupContractResult:
        say(
            "Prioritizing review feedback: "
            f"{selection.changeset_id} ({selection.epic_id})"
        )
        if dry_run:
            _dry_run_log(
                "Would update review feedback cursor "
                f"for {selection.changeset_id} "
                f"to {selection.feedback_at}."
            )
        else:
            beads.update_changeset_review_feedback_cursor(
                selection.changeset_id,
                selection.feedback_at,
                beads_root=beads_root,
                cwd=repo_root,
            )
        return StartupContractResult(
            epic_id=selection.epic_id,
            changeset_id=selection.changeset_id,
            should_exit=False,
            reason="review_feedback",
            reassign_from=stale_reassign_for_epic(selection.epic_id),
        )

    if branch_pr and repo_slug and hooked_epic:
        hooked_feedback = select_feedback_candidate([hooked_epic])
        if hooked_feedback is not None:
            return resume_feedback(hooked_feedback)

    if hooked_epic and epic_has_actionable_changeset(hooked_epic):
        say(f"Resuming hooked epic: {hooked_epic}")
        return StartupContractResult(
            epic_id=hooked_epic,
            changeset_id=None,
            should_exit=False,
            reason="hooked_epic",
        )
    if hooked_epic:
        say(f"Hooked epic has no ready changesets: {hooked_epic}")

    if branch_pr and repo_slug:
        unhooked_epics: list[str] = []
        for issue in _sort_by_created_at(issues):
            issue_id = issue.get("id")
            if not isinstance(issue_id, str) or not issue_id:
                continue
            if issue_id == hooked_epic:
                continue
            status = str(issue.get("status") or "")
            if not _is_feedback_eligible_epic_status(status):
                continue
            labels = _issue_labels(issue)
            if "at:draft" in labels:
                continue
            unhooked_epics.append(issue_id)
        feedback = select_feedback_candidate(unhooked_epics)
        if feedback is not None:
            return resume_feedback(feedback)
        global_feedback = _select_global_review_feedback_changeset(
            repo_slug=repo_slug,
            beads_root=beads_root,
            repo_root=repo_root,
        )
        if global_feedback is not None:
            return resume_feedback(global_feedback)

    for issue in assigned:
        candidate = issue.get("id")
        if candidate and epic_has_actionable_changeset(str(candidate)):
            selected_epic = str(candidate)
            say(f"Resuming assigned epic: {selected_epic}")
            return StartupContractResult(
                epic_id=selected_epic,
                changeset_id=None,
                should_exit=False,
                reason="assigned_epic",
            )

    for issue in stale_assigned:
        candidate = issue.get("id")
        previous_assignee = issue.get("assignee")
        if (
            candidate
            and isinstance(previous_assignee, str)
            and previous_assignee
            and epic_has_actionable_changeset(str(candidate))
        ):
            selected_epic = str(candidate)
            say(
                "Reclaiming stale epic assignment: "
                f"{selected_epic} (from {previous_assignee})"
            )
            return StartupContractResult(
                epic_id=selected_epic,
                changeset_id=None,
                should_exit=False,
                reason="stale_assignee_epic",
                reassign_from=previous_assignee,
            )

    if _check_inbox_before_claim(agent_id, beads_root=beads_root, repo_root=repo_root):
        if dry_run:
            _dry_run_log("Inbox has unread messages; would exit before claiming work.")
        return StartupContractResult(
            epic_id=None, changeset_id=None, should_exit=True, reason="inbox_blocked"
        )
    if _handle_queue_before_claim(
        agent_id,
        beads_root=beads_root,
        repo_root=repo_root,
        queue_name=_WORKER_QUEUE_NAME,
        dry_run=dry_run,
        assume_yes=assume_yes,
    ):
        if dry_run:
            _dry_run_log("Queue messages available; would exit before claiming work.")
        return StartupContractResult(
            epic_id=None, changeset_id=None, should_exit=True, reason="queue_blocked"
        )

    if mode == "auto":
        selected_epic = _select_epic_auto(
            issues, agent_id=agent_id, is_actionable=epic_has_actionable_changeset
        )
    else:
        selected_epic = _select_epic_prompt(
            issues,
            agent_id=agent_id,
            is_actionable=epic_has_actionable_changeset,
            assume_yes=assume_yes,
        )
    if selected_epic is None:
        selected_epic = _select_epic_from_ready_changesets(
            issues=issues,
            is_actionable=epic_has_actionable_changeset,
            beads_root=beads_root,
            repo_root=repo_root,
        )
        if selected_epic:
            return StartupContractResult(
                epic_id=selected_epic,
                changeset_id=None,
                should_exit=False,
                reason="selected_ready_changeset",
            )

    if selected_epic is None:
        _send_needs_decision(
            agent_id=agent_id,
            mode=mode,
            issues=issues,
            beads_root=beads_root,
            repo_root=repo_root,
            dry_run=dry_run,
        )
        return StartupContractResult(
            epic_id=None,
            changeset_id=None,
            should_exit=True,
            reason="no_eligible_epics",
        )

    return StartupContractResult(
        epic_id=selected_epic,
        changeset_id=None,
        should_exit=False,
        reason="selected_auto" if mode == "auto" else "selected_prompt",
    )


def _run_worker_once(
    args: object, *, mode: str, dry_run: bool, session_key: str
) -> WorkerRunSummary:
    """Start a single worker session by selecting an epic and changeset."""
    timings: list[tuple[str, float]] = []
    trace = _trace_enabled()

    def finish(summary: WorkerRunSummary) -> WorkerRunSummary:
        _report_timings(timings, trace=trace)
        return summary

    project_root, project_config, _enlistment, repo_root = (
        resolve_current_project_with_repo_root()
    )
    project_data_dir = config.resolve_project_data_dir(project_root, project_config)
    beads_root = config.resolve_beads_root(project_data_dir, repo_root)
    git_path = config.resolve_git_path(project_config)
    if dry_run:
        agent = agent_home.preview_agent_home(
            project_data_dir, project_config, role="worker", session_key=session_key
        )
    else:
        agent = agent_home.resolve_agent_home(
            project_data_dir, project_config, role="worker", session_key=session_key
        )

    with agents.scoped_agent_env(agent.agent_id):
        say("Worker session")
        agent_bead_id: str | None = None
        finish_step = _step("Prime beads", timings=timings, trace=trace)
        if dry_run:
            _dry_run_log("Would run: bd prime")
        else:
            beads.run_bd_command(["prime"], beads_root=beads_root, cwd=repo_root)
        finish_step()
        finish_step = _step("Ensure worker agent bead", timings=timings, trace=trace)
        if dry_run:
            agent_bead = beads.find_agent_bead(
                agent.agent_id, beads_root=beads_root, cwd=repo_root
            )
            if agent_bead:
                agent_bead_id = (
                    str(agent_bead.get("id")) if agent_bead.get("id") else None
                )
            if not agent_bead_id:
                _dry_run_log(
                    f"Would create agent bead for {agent.agent_id!r} (worker)."
                )
            _dry_run_log("Would sync agent home policy.")
        else:
            agent_bead = beads.ensure_agent_bead(
                agent.agent_id, beads_root=beads_root, cwd=repo_root, role="worker"
            )
            agent_bead_id = agent_bead.get("id")
        finish_step()

        epic_id = getattr(args, "epic_id", None)
        queue_only = bool(getattr(args, "queue", False))
        assume_yes = bool(getattr(args, "yes", False))
        should_reconcile = bool(getattr(args, "reconcile", False))

        if not dry_run:
            if not isinstance(agent_bead_id, str) or not agent_bead_id:
                die("failed to resolve agent bead id")

        if should_reconcile:
            finish_step = _step(
                "Reconcile blocked changesets", timings=timings, trace=trace
            )
            reconcile_result = reconcile_blocked_merged_changesets(
                agent_id=agent.agent_id,
                agent_bead_id=agent_bead_id,
                project_config=project_config,
                project_data_dir=project_data_dir,
                beads_root=beads_root,
                repo_root=repo_root,
                git_path=git_path,
                dry_run=dry_run,
                log=say,
            )
            finish_step(
                extra=(
                    f"scanned={reconcile_result.scanned}, "
                    f"actionable={reconcile_result.actionable}, "
                    f"reconciled={reconcile_result.reconciled}, "
                    f"failed={reconcile_result.failed}"
                )
            )

        repo_slug = prs.github_repo_slug(
            project_config.project.origin or project_config.project.repo_url
        )
        finish_step = _step("Select epic", timings=timings, trace=trace)
        startup_result = _run_startup_contract(
            agent_id=agent.agent_id,
            agent_bead_id=agent_bead_id,
            beads_root=beads_root,
            repo_root=repo_root,
            mode=mode,
            explicit_epic_id=epic_id,
            queue_only=queue_only,
            dry_run=dry_run,
            assume_yes=assume_yes,
            repo_slug=repo_slug,
            branch_pr=project_config.branch.pr,
            branch_pr_strategy=project_config.branch.pr_strategy,
            git_path=git_path,
        )
        summary_note = startup_result.reason
        if startup_result.epic_id:
            summary_note = f"{summary_note} ({startup_result.epic_id})"
        finish_step(extra=summary_note)
        if startup_result.should_exit:
            if dry_run:
                _dry_run_log("Startup contract would exit without starting a worker.")
            return finish(
                WorkerRunSummary(
                    started=False,
                    reason=startup_result.reason,
                    epic_id=startup_result.epic_id,
                )
            )
        if not startup_result.epic_id:
            if dry_run:
                _dry_run_log("Startup contract did not select an epic.")
                return finish(
                    WorkerRunSummary(
                        started=False, reason="no_epic_selected", epic_id=None
                    )
                )
            die("startup contract did not select an epic")
        selected_epic = startup_result.epic_id

        finish_step = _step("Claim epic", timings=timings, trace=trace)
        if dry_run:
            _dry_run_log(f"Selected epic: {selected_epic}")
            issues = beads.run_bd_json(
                ["show", selected_epic], beads_root=beads_root, cwd=repo_root
            )
            if not issues:
                _dry_run_log(f"Epic {selected_epic!r} not found.")
                finish_step(extra="epic not found")
                return finish(
                    WorkerRunSummary(
                        started=False, reason="epic_not_found", epic_id=selected_epic
                    )
                )
            epic_issue = issues[0]
            _dry_run_log(
                f"Would claim epic {selected_epic!r} for agent {agent.agent_id!r}."
            )
            if startup_result.reassign_from:
                _dry_run_log(
                    "Would reclaim stale epic assignment from "
                    f"{startup_result.reassign_from!r}."
                )
        else:
            say(f"Selected epic: {selected_epic}")
            epic_issue = beads.claim_epic(
                selected_epic,
                agent.agent_id,
                beads_root=beads_root,
                cwd=repo_root,
                allow_takeover_from=startup_result.reassign_from,
            )
            if startup_result.reassign_from:
                previous_agent = beads.find_agent_bead(
                    startup_result.reassign_from,
                    beads_root=beads_root,
                    cwd=repo_root,
                )
                previous_agent_id = (
                    str(previous_agent.get("id"))
                    if previous_agent and previous_agent.get("id")
                    else ""
                )
                if previous_agent_id:
                    beads.clear_agent_hook(
                        previous_agent_id, beads_root=beads_root, cwd=repo_root
                    )
        finish_step()
        finish_step = _step("Resolve root branch", timings=timings, trace=trace)
        root_branch_value = beads.extract_workspace_root_branch(epic_issue)
        if not root_branch_value:
            root_branch_value = _extract_changeset_root_branch(epic_issue)
        suggested_root_branch = None
        if not root_branch_value:
            suggested_root_branch = branching.suggest_root_branch(
                str(epic_issue.get("title") or selected_epic),
                project_config.branch.prefix,
            )
            if dry_run:
                _dry_run_log(
                    "Root branch missing; would prompt for root branch selection."
                )
                if suggested_root_branch:
                    _dry_run_log(f"Suggested root branch: {suggested_root_branch!r}.")
                root_branch_value = suggested_root_branch
            else:
                root_branch_value = root_branch.prompt_root_branch(
                    title=str(epic_issue.get("title") or selected_epic),
                    branch_prefix=project_config.branch.prefix,
                    beads_root=beads_root,
                    repo_root=repo_root,
                    assume_yes=assume_yes,
                )
                beads.update_workspace_root_branch(
                    selected_epic,
                    root_branch_value,
                    beads_root=beads_root,
                    cwd=repo_root,
                )
        finish_step(extra=root_branch_value or "unset")
        finish_step = _step("Set parent branch + hook", timings=timings, trace=trace)
        parent_branch_value = _extract_workspace_parent_branch(epic_issue)
        default_branch = git.git_default_branch(repo_root, git_path=git_path)
        if not parent_branch_value:
            parent_branch_value = default_branch or root_branch_value
        allow_parent_override = False
        if (
            parent_branch_value
            and root_branch_value
            and parent_branch_value == root_branch_value
            and not project_config.branch.pr
            and default_branch
            and default_branch != root_branch_value
        ):
            parent_branch_value = default_branch
            allow_parent_override = True
        if dry_run:
            _dry_run_log(
                f"Would set workspace parent branch to {parent_branch_value!r}."
            )
            _dry_run_log("Would set agent hook to selected epic.")
        else:
            beads.update_workspace_parent_branch(
                selected_epic,
                parent_branch_value,
                beads_root=beads_root,
                cwd=repo_root,
                allow_override=allow_parent_override,
            )
            beads.set_agent_hook(
                agent_bead_id, selected_epic, beads_root=beads_root, cwd=repo_root
            )
        finish_step()
        finish_step = _step("Validate changeset labels", timings=timings, trace=trace)
        invalid_changesets = _find_invalid_changeset_labels(
            selected_epic, beads_root=beads_root, repo_root=repo_root
        )
        if invalid_changesets:
            detail = _send_invalid_changeset_labels_notification(
                epic_id=selected_epic,
                invalid_changesets=invalid_changesets,
                agent_id=agent.agent_id,
                beads_root=beads_root,
                repo_root=repo_root,
                dry_run=dry_run,
            )
            finish_step(extra=f"invalid labels: {detail}")
            if dry_run:
                _dry_run_log("Would release epic assignment and clear agent hook.")
            else:
                _release_epic_assignment(
                    selected_epic, beads_root=beads_root, repo_root=repo_root
                )
                beads.clear_agent_hook(
                    agent_bead_id, beads_root=beads_root, cwd=repo_root
                )
            return finish(
                WorkerRunSummary(
                    started=False,
                    reason="changeset_label_violation",
                    epic_id=selected_epic,
                )
            )
        finish_step()
        finish_step = _step("Select changeset", timings=timings, trace=trace)
        changeset: dict[str, object] | None = None
        selected_changeset_override = (
            str(startup_result.changeset_id).strip()
            if startup_result.changeset_id
            else ""
        )
        if selected_changeset_override:
            override_issue = beads.run_bd_json(
                ["show", selected_changeset_override],
                beads_root=beads_root,
                cwd=repo_root,
            )
            if override_issue:
                resolved_epic = _resolve_epic_id_for_changeset(
                    override_issue[0], beads_root=beads_root, repo_root=repo_root
                )
                if resolved_epic == selected_epic:
                    changeset = override_issue[0]
        if changeset is None:
            changeset = _next_changeset(
                epic_id=selected_epic,
                beads_root=beads_root,
                repo_root=repo_root,
                repo_slug=repo_slug,
                branch_pr=project_config.branch.pr,
                branch_pr_strategy=project_config.branch.pr_strategy,
                git_path=git_path,
            )
        if changeset is None:
            _send_no_ready_changesets(
                epic_id=selected_epic,
                agent_id=agent.agent_id,
                beads_root=beads_root,
                repo_root=repo_root,
                dry_run=dry_run,
            )
            finish_step(extra="no ready changesets")
            if dry_run:
                _dry_run_log("Would release epic assignment and clear agent hook.")
                return finish(
                    WorkerRunSummary(
                        started=False,
                        reason="no_ready_changesets",
                        epic_id=selected_epic,
                    )
                )
            _release_epic_assignment(
                selected_epic, beads_root=beads_root, repo_root=repo_root
            )
            beads.clear_agent_hook(agent_bead_id, beads_root=beads_root, cwd=repo_root)
            return finish(
                WorkerRunSummary(
                    started=False, reason="no_ready_changesets", epic_id=selected_epic
                )
            )
        changeset_extra = str(changeset.get("id") or "unknown")
        if (
            selected_changeset_override
            and changeset_extra == selected_changeset_override
        ):
            changeset_extra = f"{changeset_extra} (review_feedback)"
        finish_step(extra=changeset_extra)
        changeset_id = changeset.get("id") or ""
        changeset_title = changeset.get("title") or ""
        changeset_parent_branch = root_branch_value
        if changeset_parent_branch and changeset_id:
            if dry_run:
                changeset_parent_branch = _changeset_parent_branch(
                    changeset, root_branch=changeset_parent_branch
                )
            else:
                selected_changeset = beads.run_bd_json(
                    ["show", str(changeset_id)], beads_root=beads_root, cwd=repo_root
                )
                if selected_changeset:
                    changeset_parent_branch = _changeset_parent_branch(
                        selected_changeset[0], root_branch=changeset_parent_branch
                    )
        if dry_run:
            _dry_run_log(f"Next changeset: {changeset_id} {changeset_title}")
        else:
            say(f"Next changeset: {changeset_id} {changeset_title}")
        finish_step = _step("Prepare worktrees", timings=timings, trace=trace)
        epic_worktree_path: Path | None = None
        changeset_worktree_path: Path | None = None
        branch: str | None = None
        if dry_run:
            mapping = None
            mapping_path = worktrees.mapping_path(project_data_dir, selected_epic)
            if mapping_path.exists():
                mapping = worktrees.load_mapping(mapping_path)
            epic_worktree_path = (
                project_data_dir / mapping.worktree_path
                if mapping and mapping.worktree_path
                else worktrees.worktree_dir(project_data_dir, selected_epic)
            )
            if mapping and changeset_id in mapping.changesets:
                branch = mapping.changesets[changeset_id]
            elif root_branch_value:
                branch = worktrees.derive_changeset_branch(
                    root_branch_value, changeset_id
                )
            changeset_relpath = None
            if mapping and changeset_id in mapping.changeset_worktrees:
                changeset_relpath = mapping.changeset_worktrees[changeset_id]
            elif changeset_id:
                changeset_relpath = worktrees.changeset_worktree_relpath(changeset_id)
            if changeset_relpath:
                changeset_worktree_path = project_data_dir / changeset_relpath
            _dry_run_log(f"Epic worktree: {epic_worktree_path}")
            if changeset_worktree_path is not None:
                _dry_run_log(f"Changeset worktree: {changeset_worktree_path}")
            else:
                _dry_run_log("Changeset worktree: <unknown>")
            _dry_run_log(f"Changeset branch: {branch or '<unknown>'}")
            if changeset_id:
                _dry_run_log(
                    "Would update changeset branch metadata "
                    f"(root={root_branch_value!r}, "
                    f"parent={changeset_parent_branch!r}, "
                    f"work={branch!r})."
                )
            _dry_run_log("Would ensure git worktrees and checkout.")
        else:
            epic_worktree_path = worktrees.ensure_git_worktree(
                project_data_dir,
                repo_root,
                selected_epic,
                root_branch=root_branch_value,
                git_path=git_path,
            )
            branch, mapping = worktrees.ensure_changeset_branch(
                project_data_dir,
                selected_epic,
                changeset_id,
                root_branch=root_branch_value,
            )
            beads.update_worktree_path(
                selected_epic,
                mapping.worktree_path,
                beads_root=beads_root,
                cwd=repo_root,
            )
            changeset_worktree_path = worktrees.ensure_changeset_worktree(
                project_data_dir,
                repo_root,
                selected_epic,
                changeset_id,
                branch=branch,
                root_branch=root_branch_value,
                parent_branch=changeset_parent_branch,
                git_path=git_path,
            )
            worktrees.ensure_changeset_checkout(
                changeset_worktree_path,
                branch,
                root_branch=root_branch_value,
                parent_branch=changeset_parent_branch,
                git_path=git_path,
            )
            if changeset_id:
                root_base = git.git_rev_parse(
                    changeset_worktree_path, root_branch_value, git_path=git_path
                )
                parent_base = git.git_rev_parse(
                    changeset_worktree_path,
                    changeset_parent_branch,
                    git_path=git_path,
                )
                beads.update_changeset_branch_metadata(
                    changeset_id,
                    root_branch=root_branch_value,
                    parent_branch=changeset_parent_branch,
                    work_branch=branch,
                    root_base=root_base,
                    parent_base=parent_base,
                    beads_root=beads_root,
                    cwd=repo_root,
                )
            say(f"Epic worktree: {epic_worktree_path}")
            say(f"Changeset worktree: {changeset_worktree_path}")
            say(f"Changeset branch: {branch}")
        finish_step()
        finish_step = _step("Mark changeset in progress", timings=timings, trace=trace)
        if changeset_id:
            if dry_run:
                _dry_run_log(f"Would mark changeset {changeset_id} in progress.")
            else:
                _mark_changeset_in_progress(
                    changeset_id, beads_root=beads_root, repo_root=repo_root
                )
        finish_step()

        finish_step = _step("Prepare agent session", timings=timings, trace=trace)
        agent_spec = agents.get_agent(project_config.agent.default)
        if agent_spec is None:
            die(f"unsupported agent {project_config.agent.default!r}")
        agent_options = list(project_config.agent.options.get(agent_spec.name, []))
        if agent_spec.name == "codex":
            # Worker sessions are anchored in agent home; ignore user --cd overrides.
            agent_options = _strip_flag_with_value(agent_options, "--cd")
        project_enlistment = project_config.project.enlistment or _enlistment
        workspace_branch = root_branch_value or ""
        if dry_run:
            worker_agents_path = (
                agent.path / "AGENTS.md"
                if changeset_worktree_path is not None
                else None
            )
            if worker_agents_path is not None:
                _dry_run_log(f"Would write worker AGENTS.md to {worker_agents_path}")
                _dry_run_log("Would sync Beads addendum into worker AGENTS.md.")
            if project_data_dir.exists():
                try:
                    sync_result = skills.sync_project_skills(
                        project_data_dir,
                        upgrade_policy=config.resolve_upgrade_policy(
                            project_config.atelier.upgrade
                        ),
                        yes=bool(getattr(args, "yes", False)),
                        interactive=False,
                        dry_run=True,
                    )
                    _dry_run_log(
                        f"Managed skills: {sync_result.action}"
                        + (f" ({sync_result.detail})" if sync_result.detail else "")
                    )
                except OSError:
                    pass
            _dry_run_log("Would prepare workspace environment variables.")
        else:
            skills_dir: Path | None = None
            if project_data_dir.exists():
                try:
                    sync_result = skills.sync_project_skills(
                        project_data_dir,
                        upgrade_policy=config.resolve_upgrade_policy(
                            project_config.atelier.upgrade
                        ),
                        yes=bool(getattr(args, "yes", False)),
                        interactive=(
                            sys.stdin.isatty()
                            and sys.stdout.isatty()
                            and not bool(getattr(args, "yes", False))
                        ),
                        prompt_update=lambda message: confirm(message, default=False),
                    )
                    skills_dir = sync_result.skills_dir
                    if sync_result.action in {"installed", "updated", "up_to_date"}:
                        say(f"Managed skills: {sync_result.action}")
                except OSError:
                    skills_dir = None
            if skills_dir is not None:
                project_lookup_paths, _global_lookup_paths = agents.skill_lookup_paths(
                    agent_spec.name
                )
                agent_home.ensure_agent_links(
                    agent,
                    worktree_path=changeset_worktree_path,
                    beads_root=beads_root,
                    skills_dir=skills_dir,
                    project_skill_lookup_paths=project_lookup_paths,
                )
            worker_agents_path = agent.path / "AGENTS.md"
            worker_template = templates.worker_template(
                prefer_installed_if_modified=True
            )
            worker_content = prompting.render_template(
                worker_template,
                {
                    "agent_id": agent.agent_id,
                    "project_root": str(project_enlistment),
                    "project_data_dir": str(project_data_dir),
                    "beads_dir": str(beads_root),
                    "beads_prefix": "at",
                    "worker_worktree": str(changeset_worktree_path),
                },
            )
            if agent.path.exists():
                paths.ensure_dir(worker_agents_path.parent)
                worker_agents_path.write_text(worker_content, encoding="utf-8")
                policy.sync_agent_home_policy(
                    agent,
                    role=policy.ROLE_WORKER,
                    beads_root=beads_root,
                    cwd=repo_root,
                )
                prime_addendum = beads.prime_addendum(
                    beads_root=beads_root, cwd=project_data_dir
                )
                updated_content = worker_agents_path.read_text(encoding="utf-8")
                next_content = agent_home.apply_beads_prime_addendum(
                    updated_content, prime_addendum
                )
                if next_content != updated_content:
                    worker_agents_path.write_text(next_content, encoding="utf-8")
                updated_content = worker_agents_path.read_text(encoding="utf-8")
                agent_home.ensure_claude_compat(agent.path, updated_content)
            env = workspace.workspace_environment(
                project_enlistment,
                workspace_branch,
                changeset_worktree_path,
                base_env=agents.agent_environment(agent.agent_id),
            )
            env["ATELIER_EPIC_ID"] = selected_epic
            if changeset_id:
                env["ATELIER_CHANGESET_ID"] = str(changeset_id)
            env["BEADS_DIR"] = str(beads_root)
        finish_step()
        opening_prompt = ""
        if agent_spec.name == "codex":
            opening_prompt = _worker_opening_prompt(
                project_enlistment=project_enlistment,
                workspace_branch=workspace_branch,
                epic_id=selected_epic,
                changeset_id=str(changeset_id),
                changeset_title=str(changeset_title),
            )
        finish_step = _step("Install agent hooks", timings=timings, trace=trace)
        if dry_run:
            _dry_run_log("Would ensure agent hooks are installed.")
        else:
            hook_path = hooks.ensure_agent_hooks(agent, agent_spec)
            hooks.ensure_hooks_path(env, hook_path)
        finish_step()
        finish_step = _step("Start agent session", timings=timings, trace=trace)
        if dry_run:
            _dry_run_log(f"Would start {agent_spec.display_name} session.")
        else:
            say(f"Starting {agent_spec.display_name} session")
        start_cmd, start_cwd = agent_spec.build_start_command(
            agent.path,
            agent_options,
            opening_prompt,
        )
        if agent_spec.name == "codex":
            start_cmd = _with_codex_exec(start_cmd, opening_prompt)
            start_cmd = _strip_flag_with_value(start_cmd, "--cd")
            start_cmd = _ensure_exec_subcommand_flag(start_cmd, "--skip-git-repo-check")
            start_cwd = agent.path
        if dry_run:
            _dry_run_log(f"Agent command: {' '.join(start_cmd)}")
            _dry_run_log(f"Agent cwd: {start_cwd}")
            finish_step(extra="dry run")
            return finish(
                WorkerRunSummary(
                    started=False,
                    reason="dry_run",
                    epic_id=selected_epic,
                    changeset_id=str(changeset_id) if changeset_id else None,
                )
            )
        started_at = dt.datetime.now(tz=dt.timezone.utc)
        returncode = 0
        if agent_spec.name == "codex":
            result = codex.run_codex_command(start_cmd, cwd=start_cwd, env=env)
            if result is None:
                _mark_changeset_blocked(
                    changeset_id,
                    beads_root=beads_root,
                    repo_root=repo_root,
                    reason=f"missing required command: {start_cmd[0]}",
                )
                die(f"missing required command: {start_cmd[0]}")
            if result.returncode != 0:
                returncode = result.returncode
                _mark_changeset_blocked(
                    changeset_id,
                    beads_root=beads_root,
                    repo_root=repo_root,
                    reason=f"command failed: {' '.join(start_cmd)}",
                )
                die(f"command failed: {' '.join(start_cmd)}")
        else:
            result = exec.run_command_status(start_cmd, cwd=start_cwd, env=env)
            if result is None:
                _mark_changeset_blocked(
                    changeset_id,
                    beads_root=beads_root,
                    repo_root=repo_root,
                    reason=f"missing required command: {start_cmd[0]}",
                )
                die(f"missing required command: {start_cmd[0]}")
            if result.returncode != 0:
                returncode = result.returncode
                _mark_changeset_blocked(
                    changeset_id,
                    beads_root=beads_root,
                    repo_root=repo_root,
                    reason=f"command failed: {' '.join(start_cmd)}",
                )
                die(f"command failed: {' '.join(start_cmd)}")
        finish_step(extra=f"exit={returncode}")
        finish_step = _step("Finalize changeset", timings=timings, trace=trace)
        finalize_result = _finalize_changeset(
            changeset_id=changeset_id,
            epic_id=selected_epic,
            agent_id=agent.agent_id,
            agent_bead_id=agent_bead_id,
            started_at=started_at,
            repo_slug=repo_slug,
            beads_root=beads_root,
            repo_root=repo_root,
            branch_pr=project_config.branch.pr,
            branch_pr_strategy=project_config.branch.pr_strategy,
            branch_history=project_config.branch.history,
            branch_squash_message=project_config.branch.squash_message,
            project_data_dir=project_data_dir,
            squash_message_agent_spec=agent_spec,
            squash_message_agent_options=agent_options,
            squash_message_agent_home=agent.path,
            squash_message_agent_env=env,
            git_path=git_path,
        )
        finish_step(extra=finalize_result.reason)
        if not finalize_result.continue_running:
            return finish(
                WorkerRunSummary(
                    started=False,
                    reason=finalize_result.reason,
                    epic_id=selected_epic,
                    changeset_id=str(changeset_id) if changeset_id else None,
                )
            )
        return finish(
            WorkerRunSummary(
                started=True,
                reason="agent_session_complete",
                epic_id=selected_epic,
                changeset_id=str(changeset_id) if changeset_id else None,
            )
        )


def start_worker(args: object) -> None:
    """Start worker sessions based on the configured run mode."""
    mode = _normalize_mode(getattr(args, "mode", None))
    run_mode = _normalize_run_mode(getattr(args, "run_mode", None))
    dry_run = bool(getattr(args, "dry_run", False))
    session_key = agent_home.generate_session_key()
    cleanup_agent: agent_home.AgentHome | None = None
    cleanup_project_dir: Path | None = None
    if not dry_run:
        (
            cleanup_project_root,
            cleanup_project_config,
            _cleanup_enlistment,
            _cleanup_repo_root,
        ) = resolve_current_project_with_repo_root()
        cleanup_project_dir = config.resolve_project_data_dir(
            cleanup_project_root, cleanup_project_config
        )
        cleanup_agent = agent_home.preview_agent_home(
            cleanup_project_dir,
            cleanup_project_config,
            role="worker",
            session_key=session_key,
        )
    try:
        if bool(getattr(args, "queue", False)):
            summary = _run_worker_once(
                args, mode=mode, dry_run=dry_run, session_key=session_key
            )
            _report_worker_summary(summary, dry_run=dry_run)
            return
        if dry_run:
            while True:
                summary = _run_worker_once(
                    args, mode=mode, dry_run=True, session_key=session_key
                )
                _report_worker_summary(summary, dry_run=True)
                if summary.started:
                    if run_mode == "once":
                        return
                    continue
                if summary.reason == "no_ready_changesets":
                    if run_mode == "watch":
                        interval = _watch_interval_seconds()
                        _dry_run_log(
                            "Watching for updates "
                            f"(sleeping {interval}s before next check)."
                        )
                        time.sleep(interval)
                    continue
                if run_mode != "watch":
                    return
                interval = _watch_interval_seconds()
                _dry_run_log(
                    f"Watching for updates (sleeping {interval}s before next check)."
                )
                time.sleep(interval)

        while True:
            summary = _run_worker_once(
                args, mode=mode, dry_run=False, session_key=session_key
            )
            _report_worker_summary(summary, dry_run=False)
            if summary.started:
                if run_mode == "once":
                    return
                continue
            if summary.reason == "no_ready_changesets":
                if run_mode == "watch":
                    interval = _watch_interval_seconds()
                    say(f"No ready work; watching for updates (sleeping {interval}s).")
                    time.sleep(interval)
                continue
            if run_mode == "watch":
                interval = _watch_interval_seconds()
                say(f"No ready work; watching for updates (sleeping {interval}s).")
                time.sleep(interval)
                continue
            return
    finally:
        if cleanup_agent is not None and cleanup_project_dir is not None:
            agent_home.cleanup_agent_home(
                cleanup_agent, project_dir=cleanup_project_dir
            )

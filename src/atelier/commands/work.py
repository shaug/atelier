"""Worker session command implementation.

Starts worker sessions by selecting an epic and its next ready changeset.
``atelier work`` can loop or watch based on run mode.
"""

from __future__ import annotations

import datetime as dt
import os
import time
from dataclasses import dataclass
from pathlib import Path

from .. import (
    agent_home,
    agents,
    beads,
    branching,
    codex,
    config,
    exec,
    git,
    hooks,
    messages,
    paths,
    policy,
    prompting,
    prs,
    root_branch,
    skills,
    templates,
    workspace,
    worktrees,
)
from ..io import die, prompt, say
from .resolve import resolve_current_project_with_repo_root

_MODE_VALUES = {"prompt", "auto"}
_RUN_MODE_VALUES = {"once", "default", "watch"}
_WATCH_INTERVAL_SECONDS = 60


@dataclass(frozen=True)
class StartupContractResult:
    epic_id: str | None
    should_exit: bool


def _dry_run_log(message: str) -> None:
    say(f"DRY-RUN: {message}")


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


def _list_epics(*, beads_root: Path, repo_root: Path) -> list[dict[str, object]]:
    return beads.run_bd_json(
        ["list", "--label", "at:epic"], beads_root=beads_root, cwd=repo_root
    )


def _select_epic_prompt(
    issues: list[dict[str, object]], *, agent_id: str
) -> str | None:
    epics = _filter_epics(issues, require_unassigned=True)
    resume = _filter_epics(issues, assignee=agent_id)
    if not epics and not resume:
        return None
    if epics:
        say("Available epics:")
    for issue in epics:
        issue_id = issue.get("id") or ""
        status = issue.get("status") or "unknown"
        title = issue.get("title") or ""
        root_branch_value = beads.extract_workspace_root_branch(issue) or "unset"
        say(f"- {issue_id} [{status}] {root_branch_value} {title}")
    resume = _sort_by_recency(resume)
    if resume:
        say("Resume epics:")
    for issue in resume:
        issue_id = issue.get("id") or ""
        status = issue.get("status") or "unknown"
        title = issue.get("title") or ""
        root_branch_value = beads.extract_workspace_root_branch(issue) or "unset"
        say(f"- {issue_id} [{status}] {root_branch_value} {title}")
    selection = prompt("Epic id")
    selection = selection.strip()
    if not selection:
        die("epic id is required")
    valid_ids = {str(issue.get("id")) for issue in epics + resume if issue.get("id")}
    if selection not in valid_ids:
        die(f"unknown epic id: {selection}")
    return selection


def _select_epic_auto(issues: list[dict[str, object]], *, agent_id: str) -> str | None:
    ready = _filter_epics(issues, require_unassigned=True)
    if ready:
        ready = _sort_by_created_at(ready)
        return str(ready[0].get("id"))
    unfinished = _filter_epics(issues, assignee=agent_id)
    if unfinished:
        unfinished = _sort_by_created_at(unfinished)
        return str(unfinished[0].get("id"))
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
    *, epic_id: str, beads_root: Path, repo_root: Path
) -> dict[str, object] | None:
    changesets = beads.run_bd_json(
        [
            "ready",
            "--parent",
            epic_id,
            "--label",
            "at:changeset",
            "--label",
            "cs:ready",
        ],
        beads_root=beads_root,
        cwd=repo_root,
    )
    if not changesets:
        return None
    return changesets[0]


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
            "cs:in_progress",
            "--remove-label",
            "cs:ready",
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
            "--status",
            "open",
            "--append-notes",
            note,
        ],
        beads_root=beads_root,
        cwd=repo_root,
    )


def _has_blocking_messages(
    *,
    thread_ids: set[str],
    started_at: dt.datetime,
    beads_root: Path,
    repo_root: Path,
) -> bool:
    issues = beads.run_bd_json(
        ["list", "--label", "at:message"], beads_root=beads_root, cwd=repo_root
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
) -> None:
    if not changeset_id:
        return
    issues = beads.run_bd_json(
        ["show", changeset_id], beads_root=beads_root, cwd=repo_root
    )
    if not issues:
        return
    issue = issues[0]
    labels = _issue_labels(issue)
    if "cs:merged" in labels or "cs:abandoned" in labels:
        _mark_changeset_closed(changeset_id, beads_root=beads_root, repo_root=repo_root)
        beads.close_epic_if_complete(
            epic_id, agent_bead_id, beads_root=beads_root, cwd=repo_root
        )
        return
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
        return
    if "cs:in_progress" in labels:
        _mark_changeset_blocked(
            changeset_id,
            beads_root=beads_root,
            repo_root=repo_root,
            reason="changeset state not updated after worker session",
        )
        _send_planner_notification(
            subject=f"NEEDS-DECISION: Changeset not updated ({changeset_id})",
            body="Changeset still marked cs:in_progress after worker completion. "
            "Confirm desired next state or update the bead.",
            agent_id=agent_id,
            thread_id=changeset_id,
            beads_root=beads_root,
            repo_root=repo_root,
            dry_run=False,
        )
        return
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
        return
    work_branch = work_branch.strip()
    pushed = git.git_ref_exists(repo_root, f"refs/remotes/origin/{work_branch}")
    pr_payload = None
    if repo_slug:
        pr_payload = prs.read_github_pr_status(repo_slug, work_branch)
    if not pushed and not pr_payload:
        _mark_changeset_blocked(
            changeset_id,
            beads_root=beads_root,
            repo_root=repo_root,
            reason="publish/checks signals missing",
        )
        _send_planner_notification(
            subject=f"NEEDS-DECISION: Publish/checks missing ({changeset_id})",
            body="No push or PR detected after worker completion. "
            "Publish/persist may not have run.",
            agent_id=agent_id,
            thread_id=changeset_id,
            beads_root=beads_root,
            repo_root=repo_root,
            dry_run=False,
        )


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
) -> None:
    say("Queued messages:")
    for issue in queued:
        issue_id = issue.get("id") or ""
        queue_name = issue.get("queue") or "queue"
        title = issue.get("title") or ""
        say(f"- {issue_id} [{queue_name}] {title}")
    selection = prompt("Queue message id (blank to skip)")
    selection = selection.strip()
    if not selection:
        return
    valid_ids = {str(issue.get("id")) for issue in queued if issue.get("id")}
    if selection not in valid_ids:
        die(f"unknown queue message id: {selection}")
    beads.claim_queue_message(selection, agent_id, beads_root=beads_root, cwd=repo_root)
    say(f"Claimed queue message: {selection}")


def _handle_queue_before_claim(
    agent_id: str,
    *,
    beads_root: Path,
    repo_root: Path,
    force_prompt: bool = False,
    dry_run: bool = False,
) -> bool:
    queued = beads.list_queue_messages(beads_root=beads_root, cwd=repo_root)
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
    _prompt_queue_claim(
        queued, agent_id=agent_id, beads_root=beads_root, repo_root=repo_root
    )
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
) -> StartupContractResult:
    """Apply startup_contract skill ordering to select the next epic."""
    if explicit_epic_id is not None:
        selected_epic = str(explicit_epic_id).strip()
        if not selected_epic:
            die("epic id must not be empty")
        return StartupContractResult(epic_id=selected_epic, should_exit=False)

    if queue_only:
        _handle_queue_before_claim(
            agent_id,
            beads_root=beads_root,
            repo_root=repo_root,
            force_prompt=True,
            dry_run=dry_run,
        )
        if dry_run:
            _dry_run_log("Queue-only run would exit after handling queue.")
        return StartupContractResult(epic_id=None, should_exit=True)

    hooked_epic = None
    if agent_bead_id:
        hooked_epic = _resolve_hooked_epic(
            agent_bead_id, agent_id, beads_root=beads_root, repo_root=repo_root
        )
    elif dry_run:
        _dry_run_log("Would create agent bead before checking for hooks.")
    if hooked_epic:
        say(f"Resuming hooked epic: {hooked_epic}")
        return StartupContractResult(epic_id=hooked_epic, should_exit=False)

    issues = _list_epics(beads_root=beads_root, repo_root=repo_root)
    assigned = _filter_epics(issues, assignee=agent_id)
    assigned = _sort_by_created_at(assigned)
    if assigned:
        candidate = assigned[0].get("id")
        if candidate:
            selected_epic = str(candidate)
            say(f"Resuming assigned epic: {selected_epic}")
            return StartupContractResult(epic_id=selected_epic, should_exit=False)

    if _check_inbox_before_claim(agent_id, beads_root=beads_root, repo_root=repo_root):
        if dry_run:
            _dry_run_log("Inbox has unread messages; would exit before claiming work.")
        return StartupContractResult(epic_id=None, should_exit=True)
    if _handle_queue_before_claim(
        agent_id, beads_root=beads_root, repo_root=repo_root, dry_run=dry_run
    ):
        if dry_run:
            _dry_run_log("Queue messages available; would exit before claiming work.")
        return StartupContractResult(epic_id=None, should_exit=True)

    if mode == "auto":
        selected_epic = _select_epic_auto(issues, agent_id=agent_id)
    else:
        selected_epic = _select_epic_prompt(issues, agent_id=agent_id)

    if selected_epic is None:
        _send_needs_decision(
            agent_id=agent_id,
            mode=mode,
            issues=issues,
            beads_root=beads_root,
            repo_root=repo_root,
            dry_run=dry_run,
        )
        return StartupContractResult(epic_id=None, should_exit=True)

    return StartupContractResult(epic_id=selected_epic, should_exit=False)


def _run_worker_once(args: object, *, mode: str, dry_run: bool) -> bool:
    """Start a single worker session by selecting an epic and changeset."""
    project_root, project_config, _enlistment, repo_root = (
        resolve_current_project_with_repo_root()
    )
    project_data_dir = config.resolve_project_data_dir(project_root, project_config)
    beads_root = config.resolve_beads_root(project_data_dir, repo_root)
    if dry_run:
        agent = agent_home.preview_agent_home(
            project_data_dir, project_config, role="worker"
        )
    else:
        agent = agent_home.resolve_agent_home(
            project_data_dir, project_config, role="worker"
        )

    with agents.scoped_agent_env(agent.agent_id):
        agent_bead_id: str | None = None
        if dry_run:
            _dry_run_log("Would run: bd prime")
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
            beads.run_bd_command(["prime"], beads_root=beads_root, cwd=repo_root)
            agent_bead = beads.ensure_agent_bead(
                agent.agent_id, beads_root=beads_root, cwd=repo_root, role="worker"
            )
            agent_bead_id = agent_bead.get("id")

        epic_id = getattr(args, "epic_id", None)
        queue_only = bool(getattr(args, "queue", False))

        if not dry_run:
            if not isinstance(agent_bead_id, str) or not agent_bead_id:
                die("failed to resolve agent bead id")

        startup_result = _run_startup_contract(
            agent_id=agent.agent_id,
            agent_bead_id=agent_bead_id,
            beads_root=beads_root,
            repo_root=repo_root,
            mode=mode,
            explicit_epic_id=epic_id,
            queue_only=queue_only,
            dry_run=dry_run,
        )
        if startup_result.should_exit:
            if dry_run:
                _dry_run_log("Startup contract would exit without starting a worker.")
            return False
        if not startup_result.epic_id:
            if dry_run:
                _dry_run_log("Startup contract did not select an epic.")
                return False
            die("startup contract did not select an epic")
        selected_epic = startup_result.epic_id

        if dry_run:
            _dry_run_log(f"Selected epic: {selected_epic}")
            issues = beads.run_bd_json(
                ["show", selected_epic], beads_root=beads_root, cwd=repo_root
            )
            if not issues:
                _dry_run_log(f"Epic {selected_epic!r} not found.")
                return False
            epic_issue = issues[0]
            _dry_run_log(
                f"Would claim epic {selected_epic!r} for agent {agent.agent_id!r}."
            )
        else:
            say(f"Selected epic: {selected_epic}")
            epic_issue = beads.claim_epic(
                selected_epic, agent.agent_id, beads_root=beads_root, cwd=repo_root
            )
        root_branch_value = beads.extract_workspace_root_branch(epic_issue)
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
                )
                beads.update_workspace_root_branch(
                    selected_epic,
                    root_branch_value,
                    beads_root=beads_root,
                    cwd=repo_root,
                )
        parent_branch_value = root_branch_value
        if dry_run:
            _dry_run_log(
                f"Would set workspace parent branch to {parent_branch_value!r}."
            )
            _dry_run_log("Would set agent hook to selected epic.")
        else:
            beads.update_workspace_parent_branch(
                selected_epic, parent_branch_value, beads_root=beads_root, cwd=repo_root
            )
            beads.set_agent_hook(
                agent_bead_id, selected_epic, beads_root=beads_root, cwd=repo_root
            )
        changeset = _next_changeset(
            epic_id=selected_epic, beads_root=beads_root, repo_root=repo_root
        )
        if changeset is None:
            _send_no_ready_changesets(
                epic_id=selected_epic,
                agent_id=agent.agent_id,
                beads_root=beads_root,
                repo_root=repo_root,
                dry_run=dry_run,
            )
            if dry_run:
                _dry_run_log("Would release epic assignment and clear agent hook.")
                return False
            _release_epic_assignment(
                selected_epic, beads_root=beads_root, repo_root=repo_root
            )
            beads.clear_agent_hook(agent_bead_id, beads_root=beads_root, cwd=repo_root)
            return False
        changeset_id = changeset.get("id") or ""
        changeset_title = changeset.get("title") or ""
        if dry_run:
            _dry_run_log(f"Next changeset: {changeset_id} {changeset_title}")
        else:
            say(f"Next changeset: {changeset_id} {changeset_title}")
        if changeset_id:
            if dry_run:
                _dry_run_log(f"Would mark changeset {changeset_id} in progress.")
            else:
                _mark_changeset_in_progress(
                    changeset_id, beads_root=beads_root, repo_root=repo_root
                )
        git_path = config.resolve_git_path(project_config)
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
                    f"(root={root_branch_value!r}, parent={parent_branch_value!r}, "
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
                git_path=git_path,
            )
            worktrees.ensure_changeset_checkout(
                changeset_worktree_path,
                branch,
                root_branch=root_branch_value,
                git_path=git_path,
            )
            if changeset_id:
                root_base = git.git_rev_parse(
                    changeset_worktree_path, root_branch_value, git_path=git_path
                )
                parent_base = git.git_rev_parse(
                    changeset_worktree_path, parent_branch_value, git_path=git_path
                )
                beads.update_changeset_branch_metadata(
                    changeset_id,
                    root_branch=root_branch_value,
                    parent_branch=parent_branch_value,
                    work_branch=branch,
                    root_base=root_base,
                    parent_base=parent_base,
                    beads_root=beads_root,
                    cwd=repo_root,
                )
            say(f"Epic worktree: {epic_worktree_path}")
            say(f"Changeset worktree: {changeset_worktree_path}")
            say(f"Changeset branch: {branch}")

        agent_spec = agents.get_agent(project_config.agent.default)
        if agent_spec is None:
            die(f"unsupported agent {project_config.agent.default!r}")
        agent_options = list(project_config.agent.options.get(agent_spec.name, []))
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
            _dry_run_log("Would prepare workspace environment variables.")
        else:
            skills_dir: Path | None = None
            if project_data_dir.exists():
                try:
                    skills_dir = skills.ensure_project_skills(project_data_dir)
                except OSError:
                    skills_dir = None
            if skills_dir is not None:
                agent_home.ensure_agent_links(
                    agent,
                    worktree_path=changeset_worktree_path,
                    beads_root=beads_root,
                    skills_dir=skills_dir,
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
        opening_prompt = ""
        if agent_spec.name == "codex":
            opening_prompt = workspace.workspace_session_identifier(
                project_enlistment, workspace_branch, changeset_id or None
            )
        if dry_run:
            _dry_run_log("Would ensure agent hooks are installed.")
        else:
            hook_path = hooks.ensure_agent_hooks(agent, agent_spec)
            hooks.ensure_hooks_path(env, hook_path)
        if dry_run:
            _dry_run_log(f"Would start {agent_spec.display_name} session.")
        else:
            say(f"Starting {agent_spec.display_name} session")
        start_cmd, start_cwd = agent_spec.build_start_command(
            agent.path,
            agent_options,
            opening_prompt,
        )
        if dry_run:
            _dry_run_log(f"Agent command: {' '.join(start_cmd)}")
            _dry_run_log(f"Agent cwd: {start_cwd}")
            return False
        started_at = dt.datetime.now(tz=dt.timezone.utc)
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
                _mark_changeset_blocked(
                    changeset_id,
                    beads_root=beads_root,
                    repo_root=repo_root,
                    reason=f"command failed: {' '.join(start_cmd)}",
                )
                die(f"command failed: {' '.join(start_cmd)}")
        _finalize_changeset(
            changeset_id=changeset_id,
            epic_id=selected_epic,
            agent_id=agent.agent_id,
            agent_bead_id=agent_bead_id,
            started_at=started_at,
            repo_slug=prs.github_repo_slug(
                project_config.project.origin or project_config.project.repo_url
            ),
            beads_root=beads_root,
            repo_root=repo_root,
        )
        return True


def start_worker(args: object) -> None:
    """Start worker sessions based on the configured run mode."""
    mode = _normalize_mode(getattr(args, "mode", None))
    run_mode = _normalize_run_mode(getattr(args, "run_mode", None))
    dry_run = bool(getattr(args, "dry_run", False))
    if bool(getattr(args, "queue", False)):
        _run_worker_once(args, mode=mode, dry_run=dry_run)
        return
    if dry_run:
        while True:
            _run_worker_once(args, mode=mode, dry_run=True)
            if run_mode != "watch":
                return
            interval = _watch_interval_seconds()
            _dry_run_log(
                f"Watching for updates (sleeping {interval}s before next check)."
            )
            time.sleep(interval)

    while True:
        started = _run_worker_once(args, mode=mode, dry_run=False)
        if run_mode == "once":
            return
        if started:
            continue
        if run_mode == "watch":
            interval = _watch_interval_seconds()
            say(f"No ready work; watching for updates (sleeping {interval}s).")
            time.sleep(interval)
            continue
        return

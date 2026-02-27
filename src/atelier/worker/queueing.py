"""Worker queueing and notification helpers."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from pathlib import Path

from .. import beads

EmitFn = Callable[[str], None]
PromptFn = Callable[[str], str]
DieFn = Callable[[str], None]


def send_needs_decision(
    *,
    agent_id: str,
    mode: str,
    issues: list[dict[str, object]],
    beads_root: Path,
    repo_root: Path,
    dry_run: bool,
    filter_epics: Callable[..., list[dict[str, object]]],
    dry_run_log: EmitFn,
) -> None:
    ready = filter_epics(issues, require_unassigned=True)
    assigned = filter_epics(issues, assignee=agent_id)
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
        dry_run_log(f"Would send message: {subject}")
        dry_run_log(body)
        return
    beads.create_message_bead(
        subject=subject,
        body=body,
        metadata={"from": agent_id, "queue": "overseer", "msg_type": "notification"},
        beads_root=beads_root,
        cwd=repo_root,
    )


def send_planner_notification(
    *,
    subject: str,
    body: str,
    agent_id: str,
    thread_id: str | None,
    beads_root: Path,
    repo_root: Path,
    dry_run: bool,
    dry_run_log: EmitFn,
) -> None:
    if dry_run:
        dry_run_log(f"Would send message: {subject}")
        dry_run_log(body)
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


def send_invalid_changeset_labels_notification(
    *,
    epic_id: str,
    invalid_changesets: list[str],
    agent_id: str,
    beads_root: Path,
    repo_root: Path,
    dry_run: bool,
    dry_run_log: EmitFn,
) -> str:
    detail = ", ".join(invalid_changesets[:5])
    if len(invalid_changesets) > 5:
        detail = f"{detail}, ..."
    send_planner_notification(
        subject=f"NEEDS-DECISION: Invalid changeset labels ({epic_id})",
        body=(
            "Found child work items with invalid labels: "
            f"{', '.join(invalid_changesets)}.\n"
            "Do not use at:subtask; changesets are inferred from graph (leaf work beads)."
        ),
        agent_id=agent_id,
        thread_id=epic_id,
        beads_root=beads_root,
        repo_root=repo_root,
        dry_run=dry_run,
        dry_run_log=dry_run_log,
    )
    return detail


def send_no_ready_changesets(
    *,
    epic_id: str,
    agent_id: str,
    beads_root: Path,
    repo_root: Path,
    dry_run: bool,
    dry_run_log: EmitFn,
) -> None:
    summary = beads.epic_changeset_summary(epic_id, beads_root=beads_root, cwd=repo_root)
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
    send_planner_notification(
        subject=subject,
        body=body,
        agent_id=agent_id,
        thread_id=epic_id,
        beads_root=beads_root,
        repo_root=repo_root,
        dry_run=dry_run,
        dry_run_log=dry_run_log,
    )


def check_inbox_before_claim(
    agent_id: str,
    *,
    beads_root: Path,
    repo_root: Path,
    emit: EmitFn,
) -> bool:
    inbox = beads.list_inbox_messages(
        agent_id, beads_root=beads_root, cwd=repo_root, unread_only=True
    )
    if inbox:
        emit(f"Inbox has {len(inbox)} unread message(s); review before claiming work.")
        return True
    return False


def prompt_queue_claim(
    queued: list[dict[str, object]],
    *,
    agent_id: str,
    beads_root: Path,
    repo_root: Path,
    assume_yes: bool,
    emit: EmitFn,
    prompt_fn: PromptFn,
    die_fn: DieFn,
) -> bool:
    emit("Queued messages:")
    for issue in queued:
        issue_id = issue.get("id") or ""
        queue_name = issue.get("queue") or "queue"
        title = issue.get("title") or ""
        emit(f"- {issue_id} [{queue_name}] {title}")
    selection = ""
    if assume_yes:
        first = queued[0].get("id")
        selection = str(first).strip() if first is not None else ""
    else:
        selection = prompt_fn("Queue message id (blank to skip)").strip()
    if not selection:
        return False
    valid_ids = {str(issue.get("id")) for issue in queued if issue.get("id")}
    if selection not in valid_ids:
        die_fn(f"unknown queue message id: {selection}")
        return False
    beads.claim_queue_message(selection, agent_id, beads_root=beads_root, cwd=repo_root)
    emit(f"Claimed queue message: {selection}")
    return True


def handle_queue_before_claim(
    agent_id: str,
    *,
    beads_root: Path,
    repo_root: Path,
    queue_name: str | None,
    force_prompt: bool,
    dry_run: bool,
    assume_yes: bool,
    emit: EmitFn,
    prompt_fn: PromptFn,
    die_fn: DieFn,
    dry_run_log: EmitFn,
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
                dry_run_log("No queued messages available.")
            else:
                emit("No queued messages available.")
            return True
        return False
    if dry_run:
        emit("Queued messages:")
        for issue in queued:
            issue_id = issue.get("id") or ""
            item_queue_name = issue.get("queue") or "queue"
            title = issue.get("title") or ""
            emit(f"- {issue_id} [{item_queue_name}] {title}")
        dry_run_log("Would prompt to claim a queue message.")
        return True
    claimed = prompt_queue_claim(
        queued,
        agent_id=agent_id,
        beads_root=beads_root,
        repo_root=repo_root,
        assume_yes=assume_yes,
        emit=emit,
        prompt_fn=prompt_fn,
        die_fn=die_fn,
    )
    if not claimed:
        emit("Skipped queue; continuing to epic selection.")
        return False
    return True

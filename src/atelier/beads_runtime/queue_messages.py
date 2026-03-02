"""Queue/message operations extracted from the beads compatibility facade."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path

RunBdJson = Callable[..., list[dict[str, object]]]
RunBdCommand = Callable[..., object]
IssueWriteLock = Callable[[str, Path], AbstractContextManager[None]]


def create_message_bead(
    *,
    subject: str,
    body: str,
    metadata: dict[str, object],
    assignee: str | None,
    beads_root: Path,
    cwd: Path,
    render_message: Callable[[dict[str, object], str], str],
    create_issue_with_body: Callable[..., str],
    run_bd_json: RunBdJson,
    issue_label: Callable[[str], str],
    label_message: str = "message",
    label_unread: str = "unread",
) -> dict[str, object]:
    """Create a message bead and return its payload.

    Args:
        subject: Message subject/title.
        body: Markdown message body.
        metadata: Frontmatter metadata values.
        assignee: Optional direct assignee.
        beads_root: Beads store root.
        cwd: Working directory for ``bd`` commands.
        render_message: Message frontmatter renderer.
        create_issue_with_body: Bead creation helper.
        run_bd_json: ``bd --json`` command helper.

    Returns:
        Created issue payload when available, otherwise minimal id/title data.
    """
    description = render_message(metadata, body)
    args = [
        "create",
        "--type",
        "task",
        "--labels",
        ",".join([issue_label(label_message), issue_label(label_unread)]),
        "--title",
        subject,
    ]
    if assignee:
        args.extend(["--assignee", assignee])
    issue_id = create_issue_with_body(args, description, beads_root=beads_root, cwd=cwd)
    issues = run_bd_json(["show", issue_id], beads_root=beads_root, cwd=cwd)
    return issues[0] if issues else {"id": issue_id, "title": subject}


def list_inbox_messages(
    agent_id: str,
    *,
    beads_root: Path,
    cwd: Path,
    unread_only: bool,
    run_bd_json: RunBdJson,
    issue_label: Callable[[str], str],
    label_message: str = "message",
    label_unread: str = "unread",
) -> list[dict[str, object]]:
    """List direct inbox messages for an agent.

    Args:
        agent_id: Agent identifier used as assignee filter.
        beads_root: Beads store root.
        cwd: Working directory for ``bd`` commands.
        unread_only: Whether to include only unread messages.
        run_bd_json: ``bd --json`` command helper.

    Returns:
        Matching message issues.
    """
    args = ["list", "--label", issue_label(label_message), "--assignee", agent_id]
    if unread_only:
        args.extend(["--label", issue_label(label_unread)])
    return run_bd_json(args, beads_root=beads_root, cwd=cwd)


def list_queue_messages(
    *,
    beads_root: Path,
    cwd: Path,
    queue: str | None,
    unclaimed_only: bool,
    unread_only: bool,
    run_bd_json: RunBdJson,
    parse_message: Callable[[str], object],
    issue_label: Callable[[str], str],
    label_message: str = "message",
    label_unread: str = "unread",
) -> list[dict[str, object]]:
    """List queued message beads with optional queue filtering."""
    args = ["list", "--label", issue_label(label_message)]
    if unread_only:
        args.extend(["--label", issue_label(label_unread)])
    issues = run_bd_json(args, beads_root=beads_root, cwd=cwd)
    matches: list[dict[str, object]] = []
    for issue in issues:
        description = issue.get("description")
        if not isinstance(description, str):
            continue
        payload = parse_message(description)
        payload_metadata = getattr(payload, "metadata", {})
        queue_name = payload_metadata.get("queue") if isinstance(payload_metadata, dict) else None
        if not isinstance(queue_name, str) or not queue_name.strip():
            continue
        if queue is not None and queue_name != queue:
            continue
        claimed_by = (
            payload_metadata.get("claimed_by") if isinstance(payload_metadata, dict) else None
        )
        assignee = issue.get("assignee")
        assignee_claim = (
            assignee.strip() if isinstance(assignee, str) and assignee.strip() else None
        )
        if unclaimed_only and (
            (isinstance(claimed_by, str) and claimed_by.strip()) or assignee_claim
        ):
            continue
        enriched = dict(issue)
        enriched["queue"] = queue_name
        enriched["claimed_by"] = (
            claimed_by if isinstance(claimed_by, str) and claimed_by.strip() else assignee_claim
        )
        matches.append(enriched)
    return matches


def claim_queue_message(
    message_id: str,
    agent_id: str,
    *,
    beads_root: Path,
    cwd: Path,
    queue: str | None,
    issue_write_lock: IssueWriteLock,
    run_bd_command: RunBdCommand,
    run_bd_json: RunBdJson,
    parse_message: Callable[[str], object],
    render_message: Callable[[dict[str, object], str], str],
    issue_description: Callable[[dict[str, object]], str],
    update_issue_description: Callable[..., None],
    description_update_max_attempts: int,
    die: Callable[[str], None],
) -> dict[str, object]:
    """Claim a queued message bead by setting claim metadata."""
    with issue_write_lock(message_id, beads_root):
        claim_result = run_bd_command(
            ["update", message_id, "--claim", "--status", "open"],
            beads_root=beads_root,
            cwd=cwd,
            allow_failure=True,
        )
        if getattr(claim_result, "returncode", 1) != 0:
            refreshed = run_bd_json(["show", message_id], beads_root=beads_root, cwd=cwd)
            assignee = None
            if refreshed:
                value = refreshed[0].get("assignee")
                if isinstance(value, str) and value.strip():
                    assignee = value.strip()
            if assignee != agent_id:
                die(f"message {message_id} already claimed by {assignee or 'another agent'}")
        for _attempt in range(description_update_max_attempts):
            issues = run_bd_json(["show", message_id], beads_root=beads_root, cwd=cwd)
            if not issues:
                die(f"message not found: {message_id}")
            issue = issues[0]
            assignee = issue.get("assignee")
            if not isinstance(assignee, str) or assignee.strip() != agent_id:
                die(f"message {message_id} already claimed by another agent")
            description = issue.get("description")
            payload = parse_message(description if isinstance(description, str) else "")
            payload_metadata = getattr(payload, "metadata", {})
            payload_body = getattr(payload, "body", "")
            queue_name = (
                payload_metadata.get("queue") if isinstance(payload_metadata, dict) else None
            )
            if not isinstance(queue_name, str) or not queue_name.strip():
                die(f"message {message_id} is not in a queue")
            if queue is not None and queue_name != queue:
                die(f"message {message_id} is not in queue {queue!r}")
            claimed_by = (
                payload_metadata.get("claimed_by") if isinstance(payload_metadata, dict) else None
            )
            if (
                isinstance(claimed_by, str)
                and claimed_by.strip()
                and claimed_by.strip() != agent_id
            ):
                die(f"message {message_id} already claimed by {claimed_by}")
            payload_metadata["claimed_by"] = agent_id
            payload_metadata["claimed_at"] = dt.datetime.now(tz=dt.timezone.utc).isoformat()
            updated = render_message(payload_metadata, payload_body)
            update_issue_description(message_id, updated, beads_root=beads_root, cwd=cwd)
            refreshed = run_bd_json(["show", message_id], beads_root=beads_root, cwd=cwd)
            if not refreshed:
                continue
            candidate = refreshed[0]
            refreshed_payload = parse_message(issue_description(candidate))
            refreshed_metadata = getattr(refreshed_payload, "metadata", {})
            refreshed_claimed_by = (
                refreshed_metadata.get("claimed_by")
                if isinstance(refreshed_metadata, dict)
                else None
            )
            refreshed_claimed_at = (
                refreshed_metadata.get("claimed_at")
                if isinstance(refreshed_metadata, dict)
                else None
            )
            if (
                isinstance(refreshed_claimed_by, str)
                and refreshed_claimed_by.strip() == agent_id
                and isinstance(refreshed_claimed_at, str)
                and refreshed_claimed_at.strip()
            ):
                return candidate
    die(f"concurrent queue claim metadata conflict for {message_id}")
    raise RuntimeError("unreachable")


def mark_message_read(
    message_id: str,
    *,
    beads_root: Path,
    cwd: Path,
    run_bd_command: RunBdCommand,
    issue_label: Callable[[str], str],
    label_unread: str = "unread",
) -> None:
    """Mark a message bead as read by removing the unread label."""
    run_bd_command(
        ["update", message_id, "--remove-label", issue_label(label_unread)],
        beads_root=beads_root,
        cwd=cwd,
    )

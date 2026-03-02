"""Queue/message operations extracted from the Beads compatibility facade."""

from __future__ import annotations

import datetime as dt

from .. import messages
from .client import (
    FailureHandler,
    RuntimeBeadsClient,
    create_issue_with_body,
    issue_label,
    run_command,
    run_json,
    update_issue_description,
)


def create_message_bead(
    *,
    subject: str,
    body: str,
    metadata: dict[str, object],
    assignee: str | None,
    client: RuntimeBeadsClient,
    label_message: str = "message",
    label_unread: str = "unread",
) -> dict[str, object]:
    """Create a message bead and return its payload.

    Args:
        subject: Message subject/title.
        body: Markdown message body.
        metadata: Frontmatter metadata values.
        assignee: Optional direct assignee.
        client: Queue/message runtime client.

    Returns:
        Created issue payload when available, otherwise minimal id/title data.
    """
    description = messages.render_message(metadata, body)
    args = [
        "create",
        "--type",
        "task",
        "--labels",
        ",".join([issue_label(client, label_message), issue_label(client, label_unread)]),
        "--title",
        subject,
    ]
    if assignee:
        args.extend(["--assignee", assignee])
    issue_id = create_issue_with_body(client, args, description)
    issues = run_json(client, ["show", issue_id])
    return issues[0] if issues else {"id": issue_id, "title": subject}


def list_inbox_messages(
    agent_id: str,
    *,
    unread_only: bool,
    client: RuntimeBeadsClient,
    label_message: str = "message",
    label_unread: str = "unread",
) -> list[dict[str, object]]:
    """List direct inbox messages for an agent.

    Args:
        agent_id: Agent identifier used as assignee filter.
        unread_only: Whether to include only unread messages.
        client: Queue/message runtime client.

    Returns:
        Matching message issues.
    """
    args = ["list", "--label", issue_label(client, label_message), "--assignee", agent_id]
    if unread_only:
        args.extend(["--label", issue_label(client, label_unread)])
    return run_json(client, args)


def list_queue_messages(
    *,
    queue: str | None,
    unclaimed_only: bool,
    unread_only: bool,
    client: RuntimeBeadsClient,
    label_message: str = "message",
    label_unread: str = "unread",
) -> list[dict[str, object]]:
    """List queued message beads with optional queue filtering."""
    args = ["list", "--label", issue_label(client, label_message)]
    if unread_only:
        args.extend(["--label", issue_label(client, label_unread)])
    issues = run_json(client, args)
    matches: list[dict[str, object]] = []
    for issue in issues:
        description = issue.get("description")
        if not isinstance(description, str):
            continue
        payload = messages.parse_message(description)
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
    queue: str | None,
    client: RuntimeBeadsClient,
    fail: FailureHandler,
    description_update_max_attempts: int,
) -> dict[str, object]:
    """Claim a queued message bead by setting claim metadata."""
    with client.issue_write_lock(message_id):
        claim_result = run_command(
            client,
            ["update", message_id, "--claim", "--status", "open"],
            allow_failure=True,
        )
        if claim_result.returncode != 0:
            refreshed = run_json(client, ["show", message_id])
            assignee = None
            if refreshed:
                value = refreshed[0].get("assignee")
                if isinstance(value, str) and value.strip():
                    assignee = value.strip()
            if assignee != agent_id:
                fail(f"message {message_id} already claimed by {assignee or 'another agent'}")
        for _attempt in range(description_update_max_attempts):
            issues = run_json(client, ["show", message_id])
            if not issues:
                fail(f"message not found: {message_id}")
            issue = issues[0]
            assignee = issue.get("assignee")
            if not isinstance(assignee, str) or assignee.strip() != agent_id:
                fail(f"message {message_id} already claimed by another agent")
            payload = messages.parse_message(_issue_description(issue))
            payload_metadata = getattr(payload, "metadata", {})
            payload_body = getattr(payload, "body", "")
            queue_name = (
                payload_metadata.get("queue") if isinstance(payload_metadata, dict) else None
            )
            if not isinstance(queue_name, str) or not queue_name.strip():
                fail(f"message {message_id} is not in a queue")
            if queue is not None and queue_name != queue:
                fail(f"message {message_id} is not in queue {queue!r}")
            claimed_by = (
                payload_metadata.get("claimed_by") if isinstance(payload_metadata, dict) else None
            )
            if (
                isinstance(claimed_by, str)
                and claimed_by.strip()
                and claimed_by.strip() != agent_id
            ):
                fail(f"message {message_id} already claimed by {claimed_by}")
            payload_metadata["claimed_by"] = agent_id
            payload_metadata["claimed_at"] = dt.datetime.now(tz=dt.timezone.utc).isoformat()
            updated = messages.render_message(payload_metadata, payload_body)
            update_issue_description(client, message_id, updated)
            refreshed = run_json(client, ["show", message_id])
            if not refreshed:
                continue
            candidate = refreshed[0]
            refreshed_payload = messages.parse_message(_issue_description(candidate))
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
    fail(f"concurrent queue claim metadata conflict for {message_id}")
    raise RuntimeError("unreachable")


def mark_message_read(
    message_id: str,
    *,
    client: RuntimeBeadsClient,
    label_unread: str = "unread",
) -> None:
    """Mark a message bead as read by removing the unread label."""
    run_command(
        client,
        ["update", message_id, "--remove-label", issue_label(client, label_unread)],
    )


def _issue_description(issue: dict[str, object]) -> str:
    description = issue.get("description")
    return description if isinstance(description, str) else ""

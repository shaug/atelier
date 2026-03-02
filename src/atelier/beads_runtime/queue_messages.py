"""Queue/message operations extracted from the Beads compatibility facade."""

from __future__ import annotations

import datetime as dt
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Protocol

from .. import messages


class QueueMessagesClient(Protocol):
    """External-system client boundary for queue/message operations."""

    def issue_write_lock(self, issue_id: str, beads_root: Path) -> AbstractContextManager[None]:
        """Acquire a scoped write lock for an issue."""
        ...

    def run_bd_json(
        self,
        args: list[str],
        *,
        beads_root: Path,
        cwd: Path,
    ) -> list[dict[str, object]]:
        """Run a ``bd`` JSON command."""
        ...

    def run_bd_command(
        self,
        args: list[str],
        *,
        beads_root: Path,
        cwd: Path,
        allow_failure: bool = False,
    ) -> object:
        """Run a ``bd`` command."""
        ...

    def create_issue_with_body(
        self,
        args: list[str],
        description: str,
        *,
        beads_root: Path,
        cwd: Path,
    ) -> str:
        """Create an issue and return its id."""
        ...

    def update_issue_description(
        self,
        issue_id: str,
        description: str,
        *,
        beads_root: Path,
        cwd: Path,
    ) -> None:
        """Persist issue description content."""
        ...

    def issue_label(self, name: str) -> str:
        """Render a namespaced issue label."""
        ...

    def die(self, message: str) -> None:
        """Abort execution with a deterministic user-facing message."""
        ...


def create_message_bead(
    *,
    subject: str,
    body: str,
    metadata: dict[str, object],
    assignee: str | None,
    beads_root: Path,
    cwd: Path,
    client: QueueMessagesClient,
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
        ",".join([client.issue_label(label_message), client.issue_label(label_unread)]),
        "--title",
        subject,
    ]
    if assignee:
        args.extend(["--assignee", assignee])
    issue_id = client.create_issue_with_body(args, description, beads_root=beads_root, cwd=cwd)
    issues = client.run_bd_json(["show", issue_id], beads_root=beads_root, cwd=cwd)
    return issues[0] if issues else {"id": issue_id, "title": subject}


def list_inbox_messages(
    agent_id: str,
    *,
    beads_root: Path,
    cwd: Path,
    unread_only: bool,
    client: QueueMessagesClient,
    label_message: str = "message",
    label_unread: str = "unread",
) -> list[dict[str, object]]:
    """List direct inbox messages for an agent.

    Args:
        agent_id: Agent identifier used as assignee filter.
        beads_root: Beads store root.
        cwd: Working directory for ``bd`` commands.
        unread_only: Whether to include only unread messages.
        client: Queue/message runtime client.

    Returns:
        Matching message issues.
    """
    args = ["list", "--label", client.issue_label(label_message), "--assignee", agent_id]
    if unread_only:
        args.extend(["--label", client.issue_label(label_unread)])
    return client.run_bd_json(args, beads_root=beads_root, cwd=cwd)


def list_queue_messages(
    *,
    beads_root: Path,
    cwd: Path,
    queue: str | None,
    unclaimed_only: bool,
    unread_only: bool,
    client: QueueMessagesClient,
    label_message: str = "message",
    label_unread: str = "unread",
) -> list[dict[str, object]]:
    """List queued message beads with optional queue filtering."""
    args = ["list", "--label", client.issue_label(label_message)]
    if unread_only:
        args.extend(["--label", client.issue_label(label_unread)])
    issues = client.run_bd_json(args, beads_root=beads_root, cwd=cwd)
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
    beads_root: Path,
    cwd: Path,
    queue: str | None,
    client: QueueMessagesClient,
    description_update_max_attempts: int,
) -> dict[str, object]:
    """Claim a queued message bead by setting claim metadata."""
    with client.issue_write_lock(message_id, beads_root):
        claim_result = client.run_bd_command(
            ["update", message_id, "--claim", "--status", "open"],
            beads_root=beads_root,
            cwd=cwd,
            allow_failure=True,
        )
        if getattr(claim_result, "returncode", 1) != 0:
            refreshed = client.run_bd_json(["show", message_id], beads_root=beads_root, cwd=cwd)
            assignee = None
            if refreshed:
                value = refreshed[0].get("assignee")
                if isinstance(value, str) and value.strip():
                    assignee = value.strip()
            if assignee != agent_id:
                client.die(f"message {message_id} already claimed by {assignee or 'another agent'}")
        for _attempt in range(description_update_max_attempts):
            issues = client.run_bd_json(["show", message_id], beads_root=beads_root, cwd=cwd)
            if not issues:
                client.die(f"message not found: {message_id}")
            issue = issues[0]
            assignee = issue.get("assignee")
            if not isinstance(assignee, str) or assignee.strip() != agent_id:
                client.die(f"message {message_id} already claimed by another agent")
            payload = messages.parse_message(_issue_description(issue))
            payload_metadata = getattr(payload, "metadata", {})
            payload_body = getattr(payload, "body", "")
            queue_name = (
                payload_metadata.get("queue") if isinstance(payload_metadata, dict) else None
            )
            if not isinstance(queue_name, str) or not queue_name.strip():
                client.die(f"message {message_id} is not in a queue")
            if queue is not None and queue_name != queue:
                client.die(f"message {message_id} is not in queue {queue!r}")
            claimed_by = (
                payload_metadata.get("claimed_by") if isinstance(payload_metadata, dict) else None
            )
            if (
                isinstance(claimed_by, str)
                and claimed_by.strip()
                and claimed_by.strip() != agent_id
            ):
                client.die(f"message {message_id} already claimed by {claimed_by}")
            payload_metadata["claimed_by"] = agent_id
            payload_metadata["claimed_at"] = dt.datetime.now(tz=dt.timezone.utc).isoformat()
            updated = messages.render_message(payload_metadata, payload_body)
            client.update_issue_description(message_id, updated, beads_root=beads_root, cwd=cwd)
            refreshed = client.run_bd_json(["show", message_id], beads_root=beads_root, cwd=cwd)
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
    client.die(f"concurrent queue claim metadata conflict for {message_id}")
    raise RuntimeError("unreachable")


def mark_message_read(
    message_id: str,
    *,
    beads_root: Path,
    cwd: Path,
    client: QueueMessagesClient,
    label_unread: str = "unread",
) -> None:
    """Mark a message bead as read by removing the unread label."""
    client.run_bd_command(
        ["update", message_id, "--remove-label", client.issue_label(label_unread)],
        beads_root=beads_root,
        cwd=cwd,
    )


def _issue_description(issue: dict[str, object]) -> str:
    description = issue.get("description")
    return description if isinstance(description, str) else ""

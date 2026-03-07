"""Queue/message operations extracted from the Beads compatibility facade."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable

from .. import messages
from .client import (
    FailureHandler,
    RuntimeBeadsClient,
    issue_label,
    run_command,
    run_json,
)

ClosedActivePrStillBlockingFn = Callable[[dict[str, object]], bool]
MarkMessagesReadFn = Callable[[set[str]], None]


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
        ",".join([issue_label(label_message), issue_label(label_unread)]),
        "--title",
        subject,
    ]
    if assignee:
        args.extend(["--assignee", assignee])
    issue_id = client.create_issue_with_body(args, description)
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
    args = ["list", "--label", issue_label(label_message), "--assignee", agent_id]
    if unread_only:
        args.extend(["--label", issue_label(label_unread)])
    return run_json(client, args)


def list_queue_messages(
    *,
    queue: str | None,
    unclaimed_only: bool,
    unread_only: bool,
    client: RuntimeBeadsClient,
    is_closed_active_pr_still_blocking: ClosedActivePrStillBlockingFn | None = None,
    mark_messages_read_best_effort: MarkMessagesReadFn | None = None,
    needs_decision_subject_prefix: str = "NEEDS-DECISION:",
    closed_active_pr_reason: str = "needs-decision: closed changeset has active pr lifecycle",
    label_message: str = "message",
    label_unread: str = "unread",
) -> list[dict[str, object]]:
    """List queued message beads with optional queue filtering."""
    args = ["list", "--label", issue_label(label_message)]
    if unread_only:
        args.extend(["--label", issue_label(label_unread)])
    issues = run_json(client, args)
    matches: list[dict[str, object]] = []
    duplicate_groups: dict[tuple[str, str], dict[str, object]] = {}
    duplicate_replaced_ids: set[str] = set()
    stale_ids: set[str] = set()
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
        issue_id = str(issue.get("id") or "").strip()
        enriched = dict(issue)
        enriched["queue"] = queue_name
        enriched["claimed_by"] = (
            claimed_by if isinstance(claimed_by, str) and claimed_by.strip() else assignee_claim
        )
        thread_id = payload_metadata.get("thread") if isinstance(payload_metadata, dict) else None
        normalized_thread = (
            thread_id.strip() if isinstance(thread_id, str) and thread_id.strip() else None
        )
        reason_key = _needs_decision_reason_key(
            enriched.get("title"),
            thread_id=normalized_thread,
            subject_prefix=needs_decision_subject_prefix,
        )
        if normalized_thread and reason_key is not None:
            dedupe_key = (normalized_thread, reason_key)
            current = duplicate_groups.get(dedupe_key)
            if current is None:
                duplicate_groups[dedupe_key] = enriched
            else:
                if _issue_sorts_after(enriched, current):
                    replaced_id = str(current.get("id") or "").strip()
                    if replaced_id:
                        duplicate_replaced_ids.add(replaced_id)
                    duplicate_groups[dedupe_key] = enriched
                elif issue_id:
                    duplicate_replaced_ids.add(issue_id)
            continue
        matches.append(enriched)

    for dedupe_key, selected in duplicate_groups.items():
        _thread_id, reason_key = dedupe_key
        issue_id = str(selected.get("id") or "").strip()
        if (
            reason_key == closed_active_pr_reason
            and is_closed_active_pr_still_blocking is not None
            and not is_closed_active_pr_still_blocking(selected)
        ):
            if issue_id:
                stale_ids.add(issue_id)
            continue
        matches.append(selected)

    if unread_only:
        resolved_ids = duplicate_replaced_ids | stale_ids
        if resolved_ids:
            if mark_messages_read_best_effort is not None:
                mark_messages_read_best_effort(resolved_ids)
            else:
                unread_label = issue_label(label_unread)
                for message_id in sorted(resolved_ids):
                    cleaned_id = message_id.strip()
                    if not cleaned_id:
                        continue
                    run_command(
                        client,
                        ["update", cleaned_id, "--remove-label", unread_label],
                        allow_failure=True,
                    )

    if duplicate_replaced_ids or stale_ids:
        hidden_ids = duplicate_replaced_ids | stale_ids
        matches = [
            issue for issue in matches if str(issue.get("id") or "").strip() not in hidden_ids
        ]
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
            client.update_issue_description(message_id, updated)
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
        ["update", message_id, "--remove-label", issue_label(label_unread)],
    )


def _issue_sorts_after(candidate: dict[str, object], current: dict[str, object]) -> bool:
    candidate_timestamp = _parse_issue_timestamp(candidate.get("created_at"))
    current_timestamp = _parse_issue_timestamp(current.get("created_at"))
    if candidate_timestamp is not None and current_timestamp is not None:
        if candidate_timestamp != current_timestamp:
            return candidate_timestamp > current_timestamp
    elif candidate_timestamp is not None:
        return True
    elif current_timestamp is not None:
        return False
    candidate_id = str(candidate.get("id") or "").strip()
    current_id = str(current.get("id") or "").strip()
    return candidate_id > current_id


def _parse_issue_timestamp(value: object) -> dt.datetime | None:
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = f"{raw[:-1]}+00:00"
    try:
        parsed = dt.datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def _needs_decision_reason_key(
    subject: object,
    *,
    thread_id: str | None,
    subject_prefix: str,
) -> str | None:
    if not isinstance(subject, str):
        return None
    normalized_subject = " ".join(subject.split())
    if not normalized_subject.startswith(subject_prefix):
        return None
    if thread_id:
        suffix = f"({thread_id})"
        if normalized_subject.endswith(suffix):
            normalized_subject = normalized_subject[: -len(suffix)].rstrip()
    return normalized_subject.lower()


def _issue_description(issue: dict[str, object]) -> str:
    description = issue.get("description")
    return description if isinstance(description, str) else ""

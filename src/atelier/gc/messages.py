"""GC operations for stale message claims and retention."""

from __future__ import annotations

from pathlib import Path

from .. import beads, messages
from ..lib.beads import (
    CloseIssueRequest,
    ListIssuesRequest,
    UpdateIssueRequest,
    build_sync_beads_client,
)
from .common import (
    coerce_float,
    parse_rfc3339,
    try_show_issue,
)
from .models import GcAction


def _clean_optional_string(value: object) -> str | None:
    if isinstance(value, str):
        cleaned = value.strip()
        if cleaned:
            return cleaned
    return None


def collect_message_claims(
    *,
    beads_root: Path,
    repo_root: Path,
    stale_hours: float,
) -> list[GcAction]:
    import datetime as dt

    now = dt.datetime.now(tz=dt.timezone.utc)
    stale_delta = dt.timedelta(hours=stale_hours)
    actions: list[GcAction] = []
    client = build_sync_beads_client(beads_root=beads_root, cwd=repo_root)
    issues = client.list(
        ListIssuesRequest(labels=(beads.issue_label("message", beads_root=beads_root),))
    )
    for issue in issues:
        issue_id = issue.id
        if not isinstance(issue_id, str) or not issue_id:
            continue
        description = issue.description
        if not isinstance(description, str):
            continue
        payload = messages.parse_message(description)
        queue = payload.metadata.get("queue")
        claimed_at = payload.metadata.get("claimed_at")
        if not queue or not isinstance(claimed_at, str):
            continue
        claimed_time = parse_rfc3339(claimed_at)
        if claimed_time is None or now - claimed_time <= stale_delta:
            continue
        description_text = f"Release stale queue claim for message {issue_id}"
        expected_assignee = _clean_optional_string(issue.assignee)
        expected_claimed_by = _clean_optional_string(payload.metadata.get("claimed_by"))
        expected_claimed_at = _clean_optional_string(payload.metadata.get("claimed_at"))

        def _apply_release(
            message_id: str = issue_id,
            stale_assignee: str | None = expected_assignee,
            stale_claimed_by: str | None = expected_claimed_by,
            stale_claimed_at: str | None = expected_claimed_at,
        ) -> None:
            current_issue = try_show_issue(message_id, client=client)
            if current_issue is None:
                return
            current_assignee = _clean_optional_string(current_issue.assignee)
            if current_assignee != stale_assignee:
                return
            description = current_issue.description
            if not isinstance(description, str):
                return
            current_payload = messages.parse_message(description)
            current_claimed_by = _clean_optional_string(current_payload.metadata.get("claimed_by"))
            current_claimed_at = _clean_optional_string(current_payload.metadata.get("claimed_at"))
            if current_claimed_by != stale_claimed_by or current_claimed_at != stale_claimed_at:
                return
            metadata = dict(current_payload.metadata)
            metadata["claimed_by"] = None
            metadata["claimed_at"] = None
            updated = messages.render_message(metadata, current_payload.body)
            client.update(
                UpdateIssueRequest(
                    issue_id=message_id,
                    assignee="" if current_assignee else None,
                    status="open" if current_assignee else None,
                    description=updated,
                )
            )

        actions.append(GcAction(description=description_text, apply=_apply_release))
    return actions


def collect_message_retention(
    *,
    beads_root: Path,
    repo_root: Path,
) -> list[GcAction]:
    import datetime as dt

    now = dt.datetime.now(tz=dt.timezone.utc)
    actions: list[GcAction] = []
    client = build_sync_beads_client(beads_root=beads_root, cwd=repo_root)
    issues = client.list(
        ListIssuesRequest(labels=(beads.issue_label("message", beads_root=beads_root),))
    )
    for issue in issues:
        issue_id = issue.id
        if not isinstance(issue_id, str) or not issue_id:
            continue
        description = issue.description
        if not isinstance(description, str):
            continue
        payload = messages.parse_message(description)
        channel = payload.metadata.get("channel")
        if not isinstance(channel, str) or not channel.strip():
            continue
        expires_at = payload.metadata.get("expires_at")
        retention_days = coerce_float(payload.metadata.get("retention_days"))
        expiry_time: dt.datetime | None = None
        if isinstance(expires_at, str):
            expiry_time = parse_rfc3339(expires_at)
        if expiry_time is None and retention_days is not None:
            created_at_raw = issue.extra_fields.get("created_at")
            created_at = parse_rfc3339(created_at_raw if isinstance(created_at_raw, str) else None)
            if created_at is not None:
                expiry_time = created_at + dt.timedelta(days=retention_days)
        if expiry_time is None or now < expiry_time:
            continue
        description_text = f"Close expired channel message {issue_id}"

        def _apply_close(message_id: str = issue_id) -> None:
            client.close(CloseIssueRequest(issue_id=message_id))

        actions.append(GcAction(description=description_text, apply=_apply_close))
    return actions

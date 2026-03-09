"""Tests for gc.messages."""

import datetime as dt
from pathlib import Path
from unittest.mock import patch

import atelier.gc.messages as gc_messages
from atelier.lib.beads import SyncBeadsClient
from atelier.messages import parse_message, render_message
from atelier.testing.beads import IssueFixtureBuilder, build_in_memory_beads_client


def _seed_sync_client(*issues: dict[str, object]) -> tuple[SyncBeadsClient, object]:
    client, store = build_in_memory_beads_client(issues=issues)
    return SyncBeadsClient(client), store


def test_collect_message_retention_closes_expired_channel_messages() -> None:
    builder = IssueFixtureBuilder()
    description = render_message(
        {"channel": "ops", "retention_days": 1},
        "hello",
    )
    issue = builder.issue(
        "msg-1",
        labels=("at:message",),
        description=description,
        created_at="2026-01-01T00:00:00Z",
    )
    sync_client, store = _seed_sync_client(issue)

    with patch("atelier.gc.common.build_sync_beads_client", return_value=sync_client):
        actions = gc_messages.collect_message_retention(
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
        )
        assert len(actions) == 1
        actions[0].apply()

    assert store.show("msg-1")["status"] == "closed"


def test_collect_message_retention_skips_non_expired() -> None:
    builder = IssueFixtureBuilder()
    description = render_message(
        {"channel": "ops", "retention_days": 365},
        "hello",
    )
    issue = builder.issue(
        "msg-1",
        labels=("at:message",),
        description=description,
        created_at="2026-02-27T00:00:00Z",
    )
    sync_client, _store = _seed_sync_client(issue)

    with patch("atelier.gc.common.build_sync_beads_client", return_value=sync_client):
        actions = gc_messages.collect_message_retention(
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
        )

    assert actions == []


def test_collect_message_claims_releases_stale_claim_and_clears_assignment() -> None:
    builder = IssueFixtureBuilder()
    now = dt.datetime.now(tz=dt.timezone.utc)
    stale_time = (now - dt.timedelta(hours=25)).isoformat()
    description = render_message(
        {
            "channel": "ops",
            "queue": "work",
            "claimed_by": "agent-1",
            "claimed_at": stale_time,
        },
        "hello",
    )
    issue = builder.issue(
        "msg-1",
        labels=("at:message",),
        assignee="agent-1",
        status="blocked",
        description=description,
    )
    sync_client, store = _seed_sync_client(issue)

    with patch("atelier.gc.common.build_sync_beads_client", return_value=sync_client):
        actions = gc_messages.collect_message_claims(
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            stale_hours=24.0,
        )
        assert len(actions) == 1
        actions[0].apply()

    updated = store.show("msg-1")
    assert updated["status"] == "open"
    assert "assignee" not in updated
    payload = parse_message(str(updated["description"]))
    assert payload.metadata["claimed_by"] is None
    assert payload.metadata["claimed_at"] is None


def test_collect_message_claims_skips_release_when_claim_owner_changes() -> None:
    builder = IssueFixtureBuilder()
    now = dt.datetime.now(tz=dt.timezone.utc)
    stale_time = (now - dt.timedelta(hours=25)).isoformat()
    fresh_time = (now - dt.timedelta(hours=1)).isoformat()
    stale_description = render_message(
        {
            "channel": "ops",
            "queue": "work",
            "claimed_by": "agent-1",
            "claimed_at": stale_time,
        },
        "hello",
    )
    current_description = render_message(
        {
            "channel": "ops",
            "queue": "work",
            "claimed_by": "agent-2",
            "claimed_at": fresh_time,
        },
        "hello",
    )
    listed_issue = builder.issue(
        "msg-1",
        labels=("at:message",),
        assignee="agent-1",
        description=stale_description,
    )
    sync_client, store = _seed_sync_client(listed_issue)
    current_issue = builder.issue(
        "msg-1",
        assignee="agent-2",
        description=current_description,
    )

    with (
        patch("atelier.gc.common.build_sync_beads_client", return_value=sync_client),
        patch("atelier.gc.messages.try_show_issue", return_value=current_issue),
    ):
        actions = gc_messages.collect_message_claims(
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            stale_hours=24.0,
        )
        assert len(actions) == 1
        actions[0].apply()

    assert store.show("msg-1")["assignee"] == "agent-1"


def test_collect_message_claims_skips_release_when_assignee_changes_from_unassigned() -> None:
    builder = IssueFixtureBuilder()
    now = dt.datetime.now(tz=dt.timezone.utc)
    stale_time = (now - dt.timedelta(hours=25)).isoformat()
    stale_description = render_message(
        {
            "channel": "ops",
            "queue": "work",
            "claimed_by": "agent-1",
            "claimed_at": stale_time,
        },
        "hello",
    )
    listed_issue = builder.issue(
        "msg-1",
        labels=("at:message",),
        description=stale_description,
    )
    sync_client, store = _seed_sync_client(listed_issue)
    current_issue = builder.issue(
        "msg-1",
        assignee="agent-2",
        description=stale_description,
    )

    with (
        patch("atelier.gc.common.build_sync_beads_client", return_value=sync_client),
        patch("atelier.gc.messages.try_show_issue", return_value=current_issue),
    ):
        actions = gc_messages.collect_message_claims(
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            stale_hours=24.0,
        )
        assert len(actions) == 1
        actions[0].apply()

    payload = parse_message(str(store.show("msg-1")["description"]))
    assert payload.metadata["claimed_by"] == "agent-1"

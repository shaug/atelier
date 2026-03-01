"""Tests for gc.messages."""

import datetime as dt
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import atelier.gc.messages as gc_messages
from atelier.messages import render_message


def test_collect_message_retention_closes_expired_channel_messages() -> None:
    description = render_message(
        {"channel": "ops", "retention_days": 1},
        "hello",
    )
    issue = {
        "id": "msg-1",
        "description": description,
        "created_at": "2026-01-01T00:00:00Z",
    }

    calls: list[list[str]] = []

    def fake_run_bd_json(
        args: list[str], *, beads_root: Path, cwd: Path
    ) -> list[dict[str, object]]:
        if args[:3] == ["list", "--label", "at:message"]:
            return [issue]
        if args[:2] == ["show", "msg-1"]:
            return [issue]
        return []

    def fake_run_bd_command(
        args: list[str], *, beads_root: Path, cwd: Path, allow_failure: bool = False
    ) -> object:
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    with (
        patch("atelier.beads.run_bd_json", side_effect=fake_run_bd_json),
        patch("atelier.beads.run_bd_command", side_effect=fake_run_bd_command),
    ):
        actions = gc_messages.collect_message_retention(
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
        )
        assert len(actions) == 1
        actions[0].apply()

    assert any(cmd[:2] == ["close", "msg-1"] for cmd in calls)


def test_collect_message_retention_skips_non_expired() -> None:
    description = render_message(
        {"channel": "ops", "retention_days": 365},
        "hello",
    )
    issue = {
        "id": "msg-1",
        "description": description,
        "created_at": "2026-02-27T00:00:00Z",
    }

    def fake_run_bd_json(
        args: list[str], *, beads_root: Path, cwd: Path
    ) -> list[dict[str, object]]:
        if args[:3] == ["list", "--label", "at:message"]:
            return [issue]
        if args[:2] == ["show", "msg-1"]:
            return [issue]
        return []

    with patch("atelier.beads.run_bd_json", side_effect=fake_run_bd_json):
        actions = gc_messages.collect_message_retention(
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
        )

    assert actions == []


def test_collect_message_claims_releases_stale_claim() -> None:
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
    issue = {
        "id": "msg-1",
        "description": description,
    }

    commands: list[list[str]] = []

    def fake_run_bd_json(
        args: list[str], *, beads_root: Path, cwd: Path
    ) -> list[dict[str, object]]:
        if args[:3] == ["list", "--label", "at:message"]:
            return [issue]
        if args[:2] == ["show", "msg-1"]:
            return [issue]
        return []

    def fake_run_bd_command(
        args: list[str], *, beads_root: Path, cwd: Path, allow_failure: bool = False
    ) -> object:
        commands.append(args)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    with (
        patch("atelier.beads.run_bd_json", side_effect=fake_run_bd_json),
        patch("atelier.beads.run_bd_command", side_effect=fake_run_bd_command),
    ):
        actions = gc_messages.collect_message_claims(
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            stale_hours=24.0,
        )
        assert len(actions) == 1
        actions[0].apply()

    assert any(cmd[:2] == ["update", "msg-1"] and "--body-file" in cmd for cmd in commands)


def test_collect_message_claims_skips_release_when_claim_owner_changes() -> None:
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
    listed_issue = {
        "id": "msg-1",
        "assignee": "agent-1",
        "description": stale_description,
    }
    current_issue = {
        "id": "msg-1",
        "assignee": "agent-2",
        "description": current_description,
    }

    commands: list[list[str]] = []

    def fake_run_bd_json(
        args: list[str], *, beads_root: Path, cwd: Path
    ) -> list[dict[str, object]]:
        if args[:3] == ["list", "--label", "at:message"]:
            return [listed_issue]
        if args[:2] == ["show", "msg-1"]:
            return [current_issue]
        return []

    def fake_run_bd_command(
        args: list[str], *, beads_root: Path, cwd: Path, allow_failure: bool = False
    ) -> object:
        commands.append(args)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    with (
        patch("atelier.beads.run_bd_json", side_effect=fake_run_bd_json),
        patch("atelier.beads.run_bd_command", side_effect=fake_run_bd_command),
    ):
        actions = gc_messages.collect_message_claims(
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            stale_hours=24.0,
        )
        assert len(actions) == 1
        actions[0].apply()

    assert commands == []

"""Tests for gc.hooks."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import atelier.gc.hooks as gc_hooks


def test_collect_hooks_returns_empty_when_no_agents() -> None:
    with patch("atelier.beads.run_bd_json", return_value=[]):
        with patch("atelier.beads.list_epics", return_value=[]):
            actions = gc_hooks.collect_hooks(
                beads_root=Path("/beads"),
                repo_root=Path("/repo"),
                stale_hours=24.0,
                include_missing_heartbeat=True,
            )
    assert actions == []


def test_collect_hooks_releases_stale_hook_when_heartbeat_missing() -> None:
    agent_issue = {
        "id": "agent-1",
        "title": "atelier/worker/codex/p4242-t1",
        "labels": ["at:agent"],
        "description": "agent_id: agent-1\nhook_bead: epic-1\n",
    }
    epic = {"id": "epic-1", "labels": ["at:epic", "at:hooked"], "assignee": "agent-1"}

    def fake_run_bd_json(
        args: list[str], *, beads_root: Path, cwd: Path
    ) -> list[dict[str, object]]:
        if args[:3] == ["list", "--label", "at:agent"]:
            return [agent_issue]
        return []

    def fake_list_epics(*, beads_root: Path, cwd: Path, include_closed: bool) -> list:
        return [epic]

    calls: list[tuple[str, str]] = []

    with (
        patch("atelier.beads.run_bd_json", side_effect=fake_run_bd_json),
        patch("atelier.beads.list_epics", side_effect=fake_list_epics),
        patch("atelier.beads.get_agent_hook", return_value="epic-1"),
        patch(
            "atelier.gc.hooks.try_show_issue",
            return_value=epic,
        ),
        patch(
            "atelier.gc.hooks.release_epic",
            side_effect=lambda e, *, beads_root, cwd: calls.append(("release", str(e["id"]))),
        ),
        patch(
            "atelier.beads.clear_agent_hook",
            side_effect=lambda issue_id, *, beads_root, cwd: calls.append(("clear", issue_id)),
        ),
    ):
        actions = gc_hooks.collect_hooks(
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            stale_hours=24.0,
            include_missing_heartbeat=True,
        )
        assert len(actions) == 1
        assert "Release stale hook for agent-1" in actions[0].description
        actions[0].apply()
        assert ("release", "epic-1") in calls
        assert ("clear", "agent-1") in calls


def test_release_epic_clears_assignee_and_hooked_label() -> None:
    epic = {
        "id": "epic-1",
        "labels": ["at:epic", "at:hooked"],
        "status": "in_progress",
        "assignee": "agent-1",
    }
    calls: list[list[str]] = []

    def fake_run_bd_command(
        args: list[str], *, beads_root: Path, cwd: Path, allow_failure: bool = False
    ) -> object:
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    with patch("atelier.beads.run_bd_command", side_effect=fake_run_bd_command):
        gc_hooks.release_epic(epic, beads_root=Path("/beads"), cwd=Path("/repo"))

    expected = [
        "update",
        "epic-1",
        "--assignee",
        "",
        "--remove-label",
        "at:hooked",
        "--status",
        "open",
    ]
    assert any(call == expected for call in calls), f"Expected {expected} in {calls}"

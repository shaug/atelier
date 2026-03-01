"""Tests for gc.hooks."""

from pathlib import Path
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
            side_effect=lambda issue_id, **_kwargs: calls.append(("clear", issue_id)),
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
    with patch("atelier.beads.release_epic_assignment", return_value=True) as release_assignment:
        gc_hooks.release_epic(epic, beads_root=Path("/beads"), cwd=Path("/repo"))
    release_assignment.assert_called_once_with(
        "epic-1",
        beads_root=Path("/beads"),
        cwd=Path("/repo"),
        expected_assignee="agent-1",
        expected_hooked=True,
    )

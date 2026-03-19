"""Tests for gc.agents."""

from pathlib import Path
from unittest.mock import patch

import atelier.gc.agents as gc_agents


def test_collect_agent_homes_prunes_stale_session_agent_beads_deterministically() -> None:
    project_dir = Path("/project")
    beads_root = Path("/beads")
    repo_root = Path("/repo")

    live_agent = "atelier/worker/codex/p1111-t1"
    stale_hook_agent = "atelier/worker/codex/p2222-t2"
    stale_no_hook_agent = "atelier/worker/codex/p3333-t3"
    legacy_agent = "atelier/worker/codex"

    agent_issues = [
        {
            "id": "agent-live",
            "title": live_agent,
            "labels": ["at:agent"],
            "description": f"agent_id: {live_agent}\nrole_type: worker\n",
        },
        {
            "id": "agent-stale-hook",
            "title": stale_hook_agent,
            "labels": ["at:agent"],
            "description": f"agent_id: {stale_hook_agent}\nrole_type: worker\n",
        },
        {
            "id": "agent-stale-nohook",
            "title": stale_no_hook_agent,
            "labels": ["at:agent"],
            "description": f"agent_id: {stale_no_hook_agent}\nrole_type: worker\n",
        },
        {
            "id": "agent-legacy",
            "title": legacy_agent,
            "labels": ["at:agent"],
            "description": f"agent_id: {legacy_agent}\nrole_type: worker\n",
        },
    ]
    epics = [
        {
            "id": "epic-1",
            "labels": ["at:epic", "at:hooked"],
            "assignee": stale_hook_agent,
            "status": "hooked",
            "description": "",
        }
    ]

    calls: list[tuple[str, str]] = []

    def fake_run_bd_json(
        args: list[str], *, beads_root: Path, cwd: Path
    ) -> list[dict[str, object]]:
        if args[:3] == ["list", "--label", "at:agent"]:
            return agent_issues
        if args[:3] == ["list", "--label", "at:epic"]:
            return epics
        return []

    def fake_run_bd_command(
        args: list[str], *, beads_root: Path, cwd: Path, allow_failure: bool = False
    ) -> object:
        if args[:1] == ["close"] and len(args) >= 2:
            calls.append(("close", str(args[1])))
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    def fake_is_session_agent_active(agent_id: str) -> bool:
        return agent_id == live_agent

    with (
        patch("atelier.gc.agents.beads.run_bd_json", side_effect=fake_run_bd_json),
        patch("atelier.gc.agents.beads.run_bd_command", side_effect=fake_run_bd_command),
        patch(
            "atelier.gc.agents.beads.get_agent_hook",
            side_effect=lambda issue_id, *, beads_root, cwd: {"agent-stale-hook": "epic-1"}.get(
                issue_id
            ),
        ),
        patch(
            "atelier.agent_home.is_session_agent_active",
            side_effect=fake_is_session_agent_active,
        ),
        patch(
            "atelier.gc.agents.release_epic",
            side_effect=lambda epic, *, beads_root, cwd: calls.append(("release", str(epic["id"]))),
        ),
        patch(
            "atelier.gc.agents.worker_store.clear_agent_hook",
            side_effect=lambda issue_id, **_kwargs: calls.append(("clear", issue_id)),
        ),
        patch(
            "atelier.agent_home.cleanup_agent_home_by_id",
            side_effect=lambda project_dir, agent_id: calls.append(("cleanup", agent_id)),
        ),
    ):
        actions = gc_agents.collect_agent_homes(
            project_dir=project_dir,
            beads_root=beads_root,
            repo_root=repo_root,
        )
        assert [action.description for action in actions] == [
            f"Prune stale session agent bead for {stale_hook_agent}",
            f"Prune stale session agent bead for {stale_no_hook_agent}",
        ]
        for action in actions:
            action.apply()

    assert calls == [
        ("release", "epic-1"),
        ("clear", "agent-stale-hook"),
        ("close", "agent-stale-hook"),
        ("cleanup", stale_hook_agent),
        ("close", "agent-stale-nohook"),
        ("cleanup", stale_no_hook_agent),
    ]


def test_collect_agent_homes_scans_all_agent_pages_for_stale_sessions() -> None:
    project_dir = Path("/project")
    beads_root = Path("/beads")
    repo_root = Path("/repo")

    expected_args = ["list", "--label", "at:agent", "--all", "--limit", "0"]
    total_agents = 75
    stale_agents = [f"atelier/worker/codex/p{index:04d}-t1" for index in range(total_agents)]
    agent_issues = [
        {
            "id": f"agent-{index}",
            "title": agent_id,
            "labels": ["at:agent"],
            "description": f"agent_id: {agent_id}\nrole_type: worker\n",
        }
        for index, agent_id in enumerate(stale_agents)
    ]

    def fake_run_bd_json(
        args: list[str], *, beads_root: Path, cwd: Path
    ) -> list[dict[str, object]]:
        if args == expected_args:
            return agent_issues
        return []

    with (
        patch("atelier.gc.agents.beads.run_bd_json", side_effect=fake_run_bd_json) as run_bd_json,
        patch("atelier.gc.agents.beads.list_epics", return_value=[]),
        patch("atelier.gc.agents.beads.get_agent_hook", return_value=None),
        patch("atelier.agent_home.session_pid_from_agent_id", return_value=1234),
        patch("atelier.agent_home.is_session_agent_active", return_value=False),
    ):
        actions = gc_agents.collect_agent_homes(
            project_dir=project_dir,
            beads_root=beads_root,
            repo_root=repo_root,
        )

    assert len(actions) == total_agents
    assert actions[0].description == f"Prune stale session agent bead for {stale_agents[0]}"
    assert actions[-1].description == f"Prune stale session agent bead for {stale_agents[-1]}"
    run_bd_json.assert_called_once_with(expected_args, beads_root=beads_root, cwd=repo_root)

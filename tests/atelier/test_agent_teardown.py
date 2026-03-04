from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from atelier import agent_teardown


def test_teardown_agent_runtime_no_agent_bead_is_noop() -> None:
    with patch("atelier.agent_teardown.beads.find_agent_bead", return_value=None):
        result = agent_teardown.teardown_agent_runtime(
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            agent_id="atelier/worker/codex/p1",
            close_agent_bead=True,
        )

    assert result.agent_id == "atelier/worker/codex/p1"
    assert result.agent_bead_id is None
    assert result.hook_cleared is False
    assert result.agent_closed is False


def test_teardown_agent_runtime_releases_expected_hook_and_closes_bead() -> None:
    close_result = CompletedProcess(args=["bd"], returncode=0, stdout="", stderr="")
    with (
        patch(
            "atelier.agent_teardown.beads.find_agent_bead",
            return_value={"id": "agent-1"},
        ),
        patch(
            "atelier.agent_teardown.beads.get_agent_hook",
            side_effect=["epic-new", None],
        ),
        patch(
            "atelier.agent_teardown.beads.release_epic_assignment",
            return_value=True,
        ) as release_epic_assignment,
        patch("atelier.agent_teardown.beads.clear_agent_hook") as clear_agent_hook,
        patch("atelier.agent_teardown.beads.close_issue", return_value=close_result) as close_issue,
    ):
        result = agent_teardown.teardown_agent_runtime(
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            agent_id="atelier/worker/codex/p1",
            expected_epic_id="epic-expected",
            close_agent_bead=True,
        )

    release_epic_assignment.assert_called_once_with(
        "epic-expected",
        beads_root=Path("/beads"),
        cwd=Path("/repo"),
        expected_assignee="atelier/worker/codex/p1",
        expected_hooked=None,
    )
    clear_agent_hook.assert_called_once_with(
        "agent-1",
        beads_root=Path("/beads"),
        cwd=Path("/repo"),
        expected_hook="epic-expected",
    )
    close_issue.assert_called_once_with(
        "agent-1",
        beads_root=Path("/beads"),
        cwd=Path("/repo"),
        allow_failure=True,
    )
    assert result.released_epic is True
    assert result.hook_cleared is True
    assert result.agent_closed is True


def test_teardown_agent_runtime_does_not_close_when_hook_remains() -> None:
    with (
        patch(
            "atelier.agent_teardown.beads.find_agent_bead",
            return_value={"id": "agent-3"},
        ),
        patch(
            "atelier.agent_teardown.beads.get_agent_hook",
            side_effect=["epic-expected", "epic-expected"],
        ),
        patch("atelier.agent_teardown.beads.release_epic_assignment", return_value=True),
        patch("atelier.agent_teardown.beads.clear_agent_hook", side_effect=SystemExit(1)),
        patch("atelier.agent_teardown.beads.close_issue") as close_issue,
    ):
        result = agent_teardown.teardown_agent_runtime(
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            agent_id="atelier/worker/codex/p3",
            expected_epic_id="epic-expected",
            close_agent_bead=True,
        )

    close_issue.assert_not_called()
    assert result.hook_cleared is False
    assert result.agent_closed is False


def test_teardown_agent_runtime_verifies_closed_status_when_close_fails() -> None:
    close_result = CompletedProcess(args=["bd"], returncode=1, stdout="", stderr="")
    with (
        patch(
            "atelier.agent_teardown.beads.find_agent_bead",
            return_value={"id": "agent-2"},
        ),
        patch("atelier.agent_teardown.beads.get_agent_hook", return_value=None),
        patch("atelier.agent_teardown.beads.close_issue", return_value=close_result),
        patch(
            "atelier.agent_teardown.beads.run_bd_json",
            return_value=[{"id": "agent-2", "status": "closed"}],
        ) as run_bd_json,
    ):
        result = agent_teardown.teardown_agent_runtime(
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            agent_id="atelier/planner/codex/p2",
            close_agent_bead=True,
        )

    run_bd_json.assert_called_once_with(
        ["show", "agent-2"],
        beads_root=Path("/beads"),
        cwd=Path("/repo"),
    )
    assert result.agent_closed is True

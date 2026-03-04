from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import call, patch

import pytest

from atelier import agent_teardown


@pytest.fixture(autouse=True)
def _clear_runtime_teardown_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ATELIER_AGENT_ID", raising=False)
    monkeypatch.delenv("ATELIER_AGENT_BEAD_ID", raising=False)
    monkeypatch.delenv("ATELIER_EPIC_ID", raising=False)


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
        patch(
            "atelier.agent_teardown.beads.run_bd_json",
            return_value=[{"id": "epic-expected", "assignee": None, "labels": ["at:epic"]}],
        ) as run_bd_json,
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
    run_bd_json.assert_called_once_with(
        ["show", "epic-expected"],
        beads_root=Path("/beads"),
        cwd=Path("/repo"),
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


def test_teardown_agent_runtime_does_not_close_when_epic_release_unverified() -> None:
    with (
        patch(
            "atelier.agent_teardown.beads.find_agent_bead",
            return_value={"id": "agent-4"},
        ),
        patch(
            "atelier.agent_teardown.beads.get_agent_hook",
            side_effect=["epic-expected", None],
        ),
        patch("atelier.agent_teardown.beads.release_epic_assignment", return_value=False),
        patch(
            "atelier.agent_teardown.beads.run_bd_json",
            return_value=[
                {
                    "id": "epic-expected",
                    "assignee": "atelier/worker/codex/p4",
                    "labels": ["at:epic", "at:hooked"],
                }
            ],
        ) as run_bd_json,
        patch("atelier.agent_teardown.beads.clear_agent_hook"),
        patch("atelier.agent_teardown.beads.close_issue") as close_issue,
    ):
        result = agent_teardown.teardown_agent_runtime(
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            agent_id="atelier/worker/codex/p4",
            expected_epic_id="epic-expected",
            close_agent_bead=True,
        )

    run_bd_json.assert_called_once_with(
        ["show", "epic-expected"],
        beads_root=Path("/beads"),
        cwd=Path("/repo"),
    )
    close_issue.assert_not_called()
    assert result.released_epic is False
    assert result.hook_cleared is True
    assert result.agent_closed is False


def test_teardown_agent_runtime_closes_when_epic_is_already_released() -> None:
    close_result = CompletedProcess(args=["bd"], returncode=0, stdout="", stderr="")
    with (
        patch(
            "atelier.agent_teardown.beads.find_agent_bead",
            return_value={"id": "agent-5"},
        ),
        patch(
            "atelier.agent_teardown.beads.get_agent_hook",
            side_effect=["epic-expected", None],
        ),
        patch("atelier.agent_teardown.beads.release_epic_assignment", return_value=False),
        patch(
            "atelier.agent_teardown.beads.run_bd_json",
            return_value=[{"id": "epic-expected", "assignee": None, "labels": ["at:epic"]}],
        ) as run_bd_json,
        patch("atelier.agent_teardown.beads.clear_agent_hook"),
        patch("atelier.agent_teardown.beads.close_issue", return_value=close_result) as close_issue,
    ):
        result = agent_teardown.teardown_agent_runtime(
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            agent_id="atelier/worker/codex/p5",
            expected_epic_id="epic-expected",
            close_agent_bead=True,
        )

    run_bd_json.assert_has_calls(
        [
            call(
                ["show", "epic-expected"],
                beads_root=Path("/beads"),
                cwd=Path("/repo"),
            ),
            call(
                ["show", "epic-expected"],
                beads_root=Path("/beads"),
                cwd=Path("/repo"),
            ),
        ]
    )
    assert run_bd_json.call_count == 2
    close_issue.assert_called_once()
    assert result.released_epic is True
    assert result.hook_cleared is True
    assert result.agent_closed is True


def test_teardown_agent_runtime_does_not_close_when_close_time_check_fails() -> None:
    with (
        patch(
            "atelier.agent_teardown.beads.find_agent_bead",
            return_value={"id": "agent-6"},
        ),
        patch(
            "atelier.agent_teardown.beads.get_agent_hook",
            side_effect=["epic-expected", None],
        ),
        patch("atelier.agent_teardown.beads.release_epic_assignment", return_value=True),
        patch(
            "atelier.agent_teardown.beads.run_bd_json",
            return_value=[
                {
                    "id": "epic-expected",
                    "assignee": "atelier/worker/codex/p6",
                    "labels": ["at:epic", "at:hooked"],
                }
            ],
        ) as run_bd_json,
        patch("atelier.agent_teardown.beads.clear_agent_hook"),
        patch("atelier.agent_teardown.beads.close_issue") as close_issue,
    ):
        result = agent_teardown.teardown_agent_runtime(
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            agent_id="atelier/worker/codex/p6",
            expected_epic_id="epic-expected",
            close_agent_bead=True,
        )

    run_bd_json.assert_called_once_with(
        ["show", "epic-expected"],
        beads_root=Path("/beads"),
        cwd=Path("/repo"),
    )
    close_issue.assert_not_called()
    assert result.released_epic is False
    assert result.hook_cleared is True
    assert result.agent_closed is False


def test_teardown_agent_runtime_does_not_close_when_assignee_only_payload_still_owned() -> None:
    with (
        patch(
            "atelier.agent_teardown.beads.find_agent_bead",
            return_value={"id": "agent-7"},
        ),
        patch(
            "atelier.agent_teardown.beads.get_agent_hook",
            side_effect=[None, None],
        ),
        patch(
            "atelier.agent_teardown.beads.run_bd_json",
            return_value=[
                {
                    "id": "epic-stale",
                    "assignee": "atelier/worker/codex/p7",
                    "issue_type": "epic",
                    "labels": [],
                    "status": "open",
                }
            ],
        ) as run_bd_json,
        patch("atelier.agent_teardown.beads.close_issue") as close_issue,
    ):
        result = agent_teardown.teardown_agent_runtime(
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            agent_id="atelier/worker/codex/p7",
            close_agent_bead=True,
        )

    run_bd_json.assert_called_once_with(
        ["list", "--assignee", "atelier/worker/codex/p7", "--all", "--limit", "0"],
        beads_root=Path("/beads"),
        cwd=Path("/repo"),
    )
    close_issue.assert_not_called()
    assert result.released_epic is False
    assert result.hook_cleared is True
    assert result.agent_closed is False


def test_teardown_agent_runtime_does_not_close_when_owner_only_payload_still_owned() -> None:
    with (
        patch(
            "atelier.agent_teardown.beads.find_agent_bead",
            return_value={"id": "agent-7-owner"},
        ),
        patch(
            "atelier.agent_teardown.beads.get_agent_hook",
            side_effect=[None, None],
        ),
        patch(
            "atelier.agent_teardown.beads.run_bd_json",
            return_value=[
                {
                    "id": "epic-owner-only",
                    "owner": "atelier/worker/codex/p7",
                    "issue_type": "epic",
                    "labels": [],
                    "status": "open",
                }
            ],
        ) as run_bd_json,
        patch("atelier.agent_teardown.beads.close_issue") as close_issue,
    ):
        result = agent_teardown.teardown_agent_runtime(
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            agent_id="atelier/worker/codex/p7",
            close_agent_bead=True,
        )

    run_bd_json.assert_called_once_with(
        ["list", "--assignee", "atelier/worker/codex/p7", "--all", "--limit", "0"],
        beads_root=Path("/beads"),
        cwd=Path("/repo"),
    )
    close_issue.assert_not_called()
    assert result.released_epic is False
    assert result.hook_cleared is True
    assert result.agent_closed is False


def test_teardown_agent_runtime_does_not_close_when_owner_only_payload_mismatches_agent() -> None:
    with (
        patch(
            "atelier.agent_teardown.beads.find_agent_bead",
            return_value={"id": "agent-7-owner-mismatch"},
        ),
        patch(
            "atelier.agent_teardown.beads.get_agent_hook",
            side_effect=[None, None],
        ),
        patch(
            "atelier.agent_teardown.beads.run_bd_json",
            return_value=[
                {
                    "id": "epic-owner-mismatch",
                    "owner": "atelier/worker/codex/other",
                    "issue_type": "epic",
                    "labels": [],
                    "status": "open",
                }
            ],
        ) as run_bd_json,
        patch("atelier.agent_teardown.beads.close_issue") as close_issue,
    ):
        result = agent_teardown.teardown_agent_runtime(
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            agent_id="atelier/worker/codex/p7",
            close_agent_bead=True,
        )

    run_bd_json.assert_called_once_with(
        ["list", "--assignee", "atelier/worker/codex/p7", "--all", "--limit", "0"],
        beads_root=Path("/beads"),
        cwd=Path("/repo"),
    )
    close_issue.assert_not_called()
    assert result.released_epic is False
    assert result.hook_cleared is True
    assert result.agent_closed is False


def test_teardown_agent_runtime_does_not_close_when_ownership_fields_missing() -> None:
    with (
        patch(
            "atelier.agent_teardown.beads.find_agent_bead",
            return_value={"id": "agent-7-missing"},
        ),
        patch(
            "atelier.agent_teardown.beads.get_agent_hook",
            side_effect=[None, None],
        ),
        patch(
            "atelier.agent_teardown.beads.run_bd_json",
            return_value=[
                {
                    "id": "epic-missing-ownership",
                    "issue_type": "epic",
                    "labels": [],
                    "status": "open",
                }
            ],
        ) as run_bd_json,
        patch("atelier.agent_teardown.beads.close_issue") as close_issue,
    ):
        result = agent_teardown.teardown_agent_runtime(
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            agent_id="atelier/worker/codex/p7",
            close_agent_bead=True,
        )

    run_bd_json.assert_called_once_with(
        ["list", "--assignee", "atelier/worker/codex/p7", "--all", "--limit", "0"],
        beads_root=Path("/beads"),
        cwd=Path("/repo"),
    )
    close_issue.assert_not_called()
    assert result.released_epic is False
    assert result.hook_cleared is True
    assert result.agent_closed is False


def test_teardown_agent_runtime_does_not_close_when_owner_assignee_conflict() -> None:
    with (
        patch(
            "atelier.agent_teardown.beads.find_agent_bead",
            return_value={"id": "agent-7-conflict"},
        ),
        patch(
            "atelier.agent_teardown.beads.get_agent_hook",
            side_effect=[None, None],
        ),
        patch(
            "atelier.agent_teardown.beads.run_bd_json",
            return_value=[
                {
                    "id": "epic-conflict",
                    "assignee": "atelier/worker/codex/other",
                    "owner": "atelier/worker/codex/p7",
                    "issue_type": "epic",
                    "labels": [],
                    "status": "open",
                }
            ],
        ) as run_bd_json,
        patch("atelier.agent_teardown.beads.close_issue") as close_issue,
    ):
        result = agent_teardown.teardown_agent_runtime(
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            agent_id="atelier/worker/codex/p7",
            close_agent_bead=True,
        )

    run_bd_json.assert_called_once_with(
        ["list", "--assignee", "atelier/worker/codex/p7", "--all", "--limit", "0"],
        beads_root=Path("/beads"),
        cwd=Path("/repo"),
    )
    close_issue.assert_not_called()
    assert result.released_epic is False
    assert result.hook_cleared is True
    assert result.agent_closed is False


def test_teardown_agent_runtime_does_not_close_when_ownership_check_fails() -> None:
    with (
        patch(
            "atelier.agent_teardown.beads.find_agent_bead",
            return_value={"id": "agent-8"},
        ),
        patch(
            "atelier.agent_teardown.beads.get_agent_hook",
            side_effect=[None, None],
        ),
        patch(
            "atelier.agent_teardown.beads.run_bd_json",
            side_effect=SystemExit(1),
        ),
        patch("atelier.agent_teardown.beads.close_issue") as close_issue,
    ):
        result = agent_teardown.teardown_agent_runtime(
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            agent_id="atelier/worker/codex/p8",
            close_agent_bead=True,
        )

    close_issue.assert_not_called()
    assert result.released_epic is False
    assert result.hook_cleared is True
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
            side_effect=[
                [],
                [{"id": "agent-2", "status": "closed"}],
            ],
        ) as run_bd_json,
    ):
        result = agent_teardown.teardown_agent_runtime(
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            agent_id="atelier/planner/codex/p2",
            close_agent_bead=True,
        )

    run_bd_json.assert_has_calls(
        [
            call(
                ["list", "--assignee", "atelier/planner/codex/p2", "--all", "--limit", "0"],
                beads_root=Path("/beads"),
                cwd=Path("/repo"),
            ),
            call(
                ["show", "agent-2"],
                beads_root=Path("/beads"),
                cwd=Path("/repo"),
            ),
        ]
    )
    assert result.agent_closed is True

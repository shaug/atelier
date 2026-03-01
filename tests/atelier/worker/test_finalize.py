from pathlib import Path
from unittest.mock import patch

from atelier.worker import finalize
from atelier.worker.models import FinalizeResult


def test_finalize_terminal_changeset_merged_updates_integrated_sha() -> None:
    merged: list[str] = []
    closed_ancestors: list[str] = []

    with patch("atelier.worker.finalize.beads.update_changeset_integrated_sha") as update_sha:
        result = finalize.finalize_terminal_changeset(
            changeset_id="at-1.1",
            epic_id="at-1",
            terminal_state="merged",
            integrated_sha="abc1234",
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            mark_changeset_merged=lambda issue_id: merged.append(issue_id),
            mark_changeset_abandoned=lambda issue_id: None,
            close_completed_ancestor_container_changesets=lambda issue_id: closed_ancestors.append(
                issue_id
            ),
            finalize_epic_if_complete=lambda: FinalizeResult(
                continue_running=True, reason="changeset_complete"
            ),
        )

    assert result.reason == "changeset_complete"
    assert merged == ["at-1.1"]
    assert closed_ancestors == ["at-1.1"]
    update_sha.assert_called_once()


def test_finalize_epic_if_complete_returns_early_when_not_ready() -> None:
    result = finalize.finalize_epic_if_complete(
        epic_id="at-1",
        agent_id="worker/1",
        agent_bead_id="at-agent",
        branch_pr=False,
        branch_history="rebase",
        branch_squash_message="deterministic",
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
        project_data_dir=Path("/project"),
        squash_message_agent_spec=None,
        squash_message_agent_options=None,
        squash_message_agent_home=None,
        squash_message_agent_env=None,
        git_path=None,
        log=None,
        epic_ready_to_finalize=lambda _epic_id: False,
        normalize_branch_value=lambda value: str(value) if value else None,
        extract_changeset_root_branch=lambda _issue: None,
        send_planner_notification=lambda **_kwargs: None,
        resolve_epic_integration_cwd=lambda **_kwargs: Path("/repo"),
        integrate_epic_root_to_parent=lambda **_kwargs: (True, None, None),
        cleanup_epic_branches_and_worktrees=lambda **_kwargs: None,
    )

    assert result.reason == "changeset_complete"


def test_finalize_epic_if_complete_blocks_when_metadata_missing() -> None:
    notifications: list[str] = []

    with patch(
        "atelier.worker.finalize.beads.run_bd_json",
        return_value=[{"description": ""}],
    ):
        result = finalize.finalize_epic_if_complete(
            epic_id="at-1",
            agent_id="worker/1",
            agent_bead_id="at-agent",
            branch_pr=False,
            branch_history="rebase",
            branch_squash_message="deterministic",
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            project_data_dir=Path("/project"),
            squash_message_agent_spec=None,
            squash_message_agent_options=None,
            squash_message_agent_home=None,
            squash_message_agent_env=None,
            git_path=None,
            log=None,
            epic_ready_to_finalize=lambda _epic_id: True,
            normalize_branch_value=lambda _value: None,
            extract_changeset_root_branch=lambda _issue: None,
            send_planner_notification=lambda **kwargs: notifications.append(
                str(kwargs.get("subject"))
            ),
            resolve_epic_integration_cwd=lambda **_kwargs: Path("/repo"),
            integrate_epic_root_to_parent=lambda **_kwargs: (True, None, None),
            cleanup_epic_branches_and_worktrees=lambda **_kwargs: None,
        )

    assert result.reason == "epic_blocked_missing_metadata"
    assert notifications == ["NEEDS-DECISION: Missing epic branch metadata (at-1)"]

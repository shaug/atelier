from pathlib import Path
from unittest.mock import patch

from atelier import config
from atelier.worker import reconcile
from atelier.worker.models import FinalizeResult


def _project_config() -> config.ProjectConfig:
    return config.ProjectConfig(
        project=config.ProjectSection(origin="org/repo"),
        branch=config.BranchConfig(),
    )


def test_list_reconcile_epic_candidates_groups_by_epic() -> None:
    issues = [
        {
            "id": "at-1.1",
            "status": "blocked",
            "labels": ["at:changeset", "cs:merged"],
        }
    ]
    with patch("atelier.worker.reconcile.beads.run_bd_json", return_value=issues):
        candidates = reconcile.list_reconcile_epic_candidates(
            project_config=_project_config(),
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            changeset_integration_signal=lambda *_args, **_kwargs: (True, "abc1234"),
            resolve_epic_id_for_changeset=lambda *_args, **_kwargs: "at-1",
            is_closed_status=lambda _status: False,
            epic_root_integrated_into_parent=lambda *_args, **_kwargs: False,
        )

    assert candidates == {"at-1": ["at-1.1"]}


def test_resolve_hook_agent_bead_for_epic_prefers_epic_assignee() -> None:
    with (
        patch(
            "atelier.worker.reconcile.beads.run_bd_json",
            return_value=[{"assignee": "atelier/worker/codex/p1"}],
        ),
        patch(
            "atelier.worker.reconcile.beads.find_agent_bead",
            return_value={"id": "at-agent"},
        ),
    ):
        resolved = reconcile.resolve_hook_agent_bead_for_epic(
            "at-1",
            fallback_agent_bead_id="fallback",
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
        )

    assert resolved == "at-agent"


def test_reconcile_blocked_merged_changesets_dry_run_counts_candidates() -> None:
    project = config.ProjectConfig(
        project=config.ProjectSection(origin="org/repo"),
        branch=config.BranchConfig(pr=False),
    )
    issues = [
        {
            "id": "at-1.1",
            "status": "blocked",
            "labels": ["at:changeset", "cs:merged"],
        }
    ]
    with patch("atelier.worker.reconcile.beads.run_bd_json", return_value=issues):
        result = reconcile.reconcile_blocked_merged_changesets(
            agent_id="worker/1",
            agent_bead_id="at-agent",
            project_config=project,
            project_data_dir=Path("/project"),
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            dry_run=True,
            resolve_epic_id_for_changeset=lambda *_args, **_kwargs: "at-1",
            changeset_integration_signal=lambda *_args, **_kwargs: (True, "abc1234"),
            issue_dependency_ids=lambda _issue: tuple(),
            issue_labels=lambda issue: {
                str(label) for label in issue.get("labels", [])
            },
            finalize_changeset=lambda **_kwargs: FinalizeResult(
                continue_running=True, reason="changeset_complete"
            ),
            finalize_epic_if_complete=lambda **_kwargs: FinalizeResult(
                continue_running=True, reason="changeset_complete"
            ),
        )

    assert result.scanned == 1
    assert result.actionable == 1
    assert result.reconciled == 1
    assert result.failed == 0

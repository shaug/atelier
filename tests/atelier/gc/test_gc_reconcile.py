"""Tests for gc.reconcile."""

from pathlib import Path
from unittest.mock import patch

import atelier.gc.reconcile as gc_reconcile
from atelier import config, prs


def test_reconcile_preview_lines_includes_epic_and_changeset_info() -> None:
    epic = {
        "id": "at-epic",
        "description": ("workspace.root_branch: feat/root\nworkspace.parent_branch: main\n"),
    }
    changeset = {
        "id": "at-epic.1",
        "status": "closed",
        "description": "changeset.integrated_sha: abc123\n",
    }

    def fake_try_show_issue(issue_id: str, *, beads_root: Path, cwd: Path):
        if issue_id == "at-epic":
            return epic
        if issue_id == "at-epic.1":
            return changeset
        return None

    with patch(
        "atelier.gc.reconcile.try_show_issue",
        side_effect=fake_try_show_issue,
    ):
        lines = gc_reconcile.reconcile_preview_lines(
            "at-epic",
            ["at-epic.1"],
            project_dir=None,
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
        )

    assert any("final integration" in line for line in lines)
    assert any("at-epic.1" in line for line in lines)
    assert any("at-epic" in line for line in lines)


def test_reconcile_preview_lines_includes_mapping_when_project_dir_given() -> None:
    project_dir = Path("/project")
    epic = {"id": "at-epic", "description": ""}

    mapping = type(
        "Mapping",
        (),
        {
            "root_branch": "feat/root",
            "changesets": {"at-epic.1": "feat/root-at-epic.1"},
            "worktree_path": "worktrees/at-epic",
            "changeset_worktrees": {"at-epic.1": "worktrees/at-epic.1"},
        },
    )()

    with (
        patch("atelier.gc.reconcile.try_show_issue", return_value=epic),
        patch("atelier.gc.reconcile.worktrees.load_mapping", return_value=mapping),
    ):
        lines = gc_reconcile.reconcile_preview_lines(
            "at-epic",
            ["at-epic.1"],
            project_dir=project_dir,
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
        )

    assert any("mapped branches" in line for line in lines)
    assert any("mapped worktrees" in line for line in lines)


def test_reconcile_preview_lines_reports_operator_triage_for_stale_metadata() -> None:
    project_config = config.ProjectConfig(
        project=config.ProjectSection(origin="https://github.com/org/repo"),
        branch=config.BranchConfig(pr=True),
    )
    issue = {
        "id": "at-epic.1",
        "status": "blocked",
        "description": "changeset.work_branch: feat/root-at-epic.1\npr_state: draft-pr\n",
    }

    with (
        patch("atelier.gc.reconcile.try_show_issue", return_value=issue),
        patch("atelier.gc.reconcile.stale_pr_lifecycle.git.git_ref_exists", return_value=True),
        patch(
            "atelier.gc.reconcile.stale_pr_lifecycle.prs.lookup_github_pr_status",
            return_value=prs.GithubPrLookup(
                outcome="found",
                payload={
                    "number": 17,
                    "state": "CLOSED",
                    "isDraft": False,
                    "reviewDecision": None,
                    "mergedAt": "2026-03-01T00:00:00Z",
                    "closedAt": "2026-03-01T00:00:00Z",
                },
            ),
        ),
    ):
        lines = gc_reconcile.reconcile_preview_lines(
            "at-epic",
            ["at-epic.1"],
            project_dir=None,
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            project_config=project_config,
            git_path="git",
        )

    assert any("triage=metadata-stale" in line for line in lines)

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import atelier.prefix_migration_drift as prefix_migration_drift
import atelier.worktrees as worktrees


def _git_worktree_output(path: Path, branch: str) -> str:
    return (
        f"worktree {path}\n"
        "HEAD 0123456789abcdef0123456789abcdef01234567\n"
        f"branch refs/heads/{branch}\n\n"
    )


def test_scan_prefix_migration_drift_reports_conflicts_deterministically(tmp_path: Path) -> None:
    project_data_dir = tmp_path / "data"
    repo_root = tmp_path / "repo"
    project_data_dir.mkdir(parents=True)
    repo_root.mkdir(parents=True)
    worktrees.write_mapping(
        worktrees.mapping_path(project_data_dir, "ts-epic"),
        worktrees.WorktreeMapping(
            epic_id="ts-epic",
            worktree_path="worktrees/ts-epic",
            root_branch="feat/new-root",
            changesets={"ts-epic.1": "feat/legacy-branch"},
            changeset_worktrees={"ts-epic.1": "worktrees/at-legacy.1"},
        ),
    )

    epic_issue = {
        "id": "ts-epic",
        "labels": ["at:epic"],
        "description": "workspace.root_branch: feat/new-root\n",
    }
    changeset_issue = {
        "id": "ts-epic.1",
        "labels": [],
        "type": "task",
        "description": (
            "changeset.root_branch: feat/new-root\nchangeset.work_branch: feat/new-branch\n"
        ),
    }
    worktree_output = _git_worktree_output(
        project_data_dir / "worktrees" / "ts-epic.1",
        "feat/new-branch",
    )

    def fake_lookup(repo: str, branch: str) -> SimpleNamespace:
        assert repo == "org/repo"
        if branch == "feat/legacy-branch":
            return SimpleNamespace(
                found=True,
                failed=False,
                payload={"headRefName": "feat/pr-head"},
            )
        return SimpleNamespace(found=False, failed=False, payload=None)

    with (
        patch("atelier.prefix_migration_drift.beads.list_epics", return_value=[epic_issue]),
        patch(
            "atelier.prefix_migration_drift.beads.list_descendant_changesets",
            return_value=[changeset_issue],
        ),
        patch("atelier.prefix_migration_drift.beads.list_work_children", return_value=[]),
        patch(
            "atelier.prefix_migration_drift.exec_util.try_run_command",
            return_value=subprocess.CompletedProcess(
                args=["git", "worktree", "list", "--porcelain"],
                returncode=0,
                stdout=worktree_output,
                stderr="",
            ),
        ),
    ):
        first = prefix_migration_drift.scan_prefix_migration_drift(
            project_data_dir=project_data_dir,
            beads_root=tmp_path / ".beads",
            repo_root=repo_root,
            repo_slug="org/repo",
            lookup_pr_status=fake_lookup,
        )
        second = prefix_migration_drift.scan_prefix_migration_drift(
            project_data_dir=project_data_dir,
            beads_root=tmp_path / ".beads",
            repo_root=repo_root,
            repo_slug="org/repo",
            lookup_pr_status=fake_lookup,
        )

    assert first == second
    assert [record["drift_class"] for record in first] == [
        "work-branch-conflict",
        "worktree-path-conflict",
    ]
    branch_conflict = first[0]
    assert branch_conflict["changeset_id"] == "ts-epic.1"
    assert branch_conflict["values"]["metadata.changeset.work_branch"] == "feat/new-branch"
    assert branch_conflict["values"]["mapping.work_branch"] == "feat/legacy-branch"
    assert branch_conflict["values"]["pr.head_ref"] == "feat/pr-head"
    path_conflict = first[1]
    assert path_conflict["values"]["mapping.worktree_path"] == "worktrees/at-legacy.1"
    assert path_conflict["values"]["filesystem.path_for_metadata_branch"] == "worktrees/ts-epic.1"


def test_scan_prefix_migration_drift_returns_empty_when_metadata_mapping_and_worktree_align(
    tmp_path: Path,
) -> None:
    project_data_dir = tmp_path / "data"
    repo_root = tmp_path / "repo"
    project_data_dir.mkdir(parents=True)
    repo_root.mkdir(parents=True)
    worktrees.write_mapping(
        worktrees.mapping_path(project_data_dir, "ts-epic"),
        worktrees.WorktreeMapping(
            epic_id="ts-epic",
            worktree_path="worktrees/ts-epic",
            root_branch="feat/new-root",
            changesets={"ts-epic.1": "feat/new-branch"},
            changeset_worktrees={"ts-epic.1": "worktrees/ts-epic.1"},
        ),
    )

    epic_issue = {
        "id": "ts-epic",
        "labels": ["at:epic"],
        "description": "workspace.root_branch: feat/new-root\n",
    }
    changeset_issue = {
        "id": "ts-epic.1",
        "labels": [],
        "type": "task",
        "description": (
            "changeset.root_branch: feat/new-root\nchangeset.work_branch: feat/new-branch\n"
        ),
    }
    worktree_output = _git_worktree_output(
        project_data_dir / "worktrees" / "ts-epic.1",
        "feat/new-branch",
    )

    with (
        patch("atelier.prefix_migration_drift.beads.list_epics", return_value=[epic_issue]),
        patch(
            "atelier.prefix_migration_drift.beads.list_descendant_changesets",
            return_value=[changeset_issue],
        ),
        patch("atelier.prefix_migration_drift.beads.list_work_children", return_value=[]),
        patch(
            "atelier.prefix_migration_drift.exec_util.try_run_command",
            return_value=subprocess.CompletedProcess(
                args=["git", "worktree", "list", "--porcelain"],
                returncode=0,
                stdout=worktree_output,
                stderr="",
            ),
        ),
    ):
        records = prefix_migration_drift.scan_prefix_migration_drift(
            project_data_dir=project_data_dir,
            beads_root=tmp_path / ".beads",
            repo_root=repo_root,
            repo_slug=None,
        )

    assert records == []

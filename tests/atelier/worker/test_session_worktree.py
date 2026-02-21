from __future__ import annotations

from pathlib import Path

from atelier import worktrees
from atelier.worker.session import worktree


def test_prepare_worktrees_dry_run_derives_changeset_branch(tmp_path: Path) -> None:
    logs: list[str] = []

    result = worktree.prepare_worktrees(
        dry_run=True,
        project_data_dir=tmp_path,
        repo_root=Path("/repo"),
        beads_root=Path("/beads"),
        selected_epic="at-epic",
        changeset_id="at-epic.1",
        root_branch_value="feat/root",
        changeset_parent_branch="feat/root",
        git_path="git",
        emit=lambda _message: None,
        dry_run_log=logs.append,
    )

    assert result.epic_worktree_path == worktrees.worktree_dir(tmp_path, "at-epic")
    assert result.changeset_worktree_path == (
        tmp_path / worktrees.changeset_worktree_relpath("at-epic.1")
    )
    assert result.branch == worktrees.derive_changeset_branch("feat/root", "at-epic.1")
    assert any("Would ensure git worktrees and checkout." in line for line in logs)


def test_prepare_worktrees_dry_run_reuses_epic_worktree_for_epic_changeset(
    tmp_path: Path,
) -> None:
    logs: list[str] = []

    result = worktree.prepare_worktrees(
        dry_run=True,
        project_data_dir=tmp_path,
        repo_root=Path("/repo"),
        beads_root=Path("/beads"),
        selected_epic="at-epic",
        changeset_id="at-epic",
        root_branch_value="feat/root",
        changeset_parent_branch="feat/root",
        git_path="git",
        emit=lambda _message: None,
        dry_run_log=logs.append,
    )

    assert result.changeset_worktree_path == result.epic_worktree_path
    assert result.branch == "feat/root"
    assert any("Changeset branch: feat/root" in line for line in logs)

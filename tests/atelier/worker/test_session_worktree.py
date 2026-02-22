from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from atelier import worktrees
from atelier.worker.session import worktree


class _TestControl:
    def __init__(self, logs: list[str]) -> None:
        self.logs = logs

    def say(self, message: str) -> None:
        self.logs.append(message)

    def dry_run_log(self, message: str) -> None:
        self.logs.append(message)


def test_prepare_worktrees_dry_run_derives_changeset_branch(tmp_path: Path) -> None:
    logs: list[str] = []

    result = worktree.prepare_worktrees(
        context=worktree.WorktreePreparationContext(
            dry_run=True,
            project_data_dir=tmp_path,
            repo_root=Path("/repo"),
            beads_root=Path("/beads"),
            selected_epic="at-epic",
            changeset_id="at-epic.1",
            root_branch_value="feat/root",
            changeset_parent_branch="feat/root",
            git_path="git",
        ),
        control=_TestControl(logs),
    )

    assert result.epic_worktree_path == worktrees.worktree_dir(tmp_path, "at-epic")
    assert result.changeset_worktree_path == (
        tmp_path / worktrees.changeset_worktree_relpath("at-epic.1")
    )
    assert result.branch == worktrees.derive_changeset_branch("feat/root", "at-epic.1")
    assert any("Would ensure git worktrees and checkout." in line for line in logs)
    assert any("Would bootstrap conventional-commit git hooks." in line for line in logs)


def test_prepare_worktrees_dry_run_reuses_epic_worktree_for_epic_changeset(
    tmp_path: Path,
) -> None:
    logs: list[str] = []

    result = worktree.prepare_worktrees(
        context=worktree.WorktreePreparationContext(
            dry_run=True,
            project_data_dir=tmp_path,
            repo_root=Path("/repo"),
            beads_root=Path("/beads"),
            selected_epic="at-epic",
            changeset_id="at-epic",
            root_branch_value="feat/root",
            changeset_parent_branch="feat/root",
            git_path="git",
        ),
        control=_TestControl(logs),
    )

    assert result.changeset_worktree_path == result.epic_worktree_path
    assert result.branch == "feat/root"
    assert any("Changeset branch: feat/root" in line for line in logs)


def test_prepare_worktrees_bootstraps_hooks_for_epic_and_changeset_worktrees(
    tmp_path: Path,
) -> None:
    logs: list[str] = []
    epic_path = tmp_path / "worktrees" / "at-epic"
    changeset_path = tmp_path / "worktrees" / "at-epic.1"
    mapping = worktrees.WorktreeMapping(
        epic_id="at-epic",
        worktree_path="worktrees/at-epic",
        root_branch="feat/root",
        changesets={"at-epic.1": "feat/root-at-epic.1"},
        changeset_worktrees={"at-epic.1": "worktrees/at-epic.1"},
    )

    with (
        patch(
            "atelier.worker.session.worktree.worktrees.ensure_git_worktree", return_value=epic_path
        ),
        patch(
            "atelier.worker.session.worktree.worktrees.ensure_changeset_branch",
            return_value=("feat/root-at-epic.1", mapping),
        ),
        patch(
            "atelier.worker.session.worktree.worktrees.ensure_changeset_worktree",
            return_value=changeset_path,
        ),
        patch("atelier.worker.session.worktree.worktrees.ensure_changeset_checkout"),
        patch("atelier.worker.session.worktree.beads.update_worktree_path"),
        patch("atelier.worker.session.worktree.git.git_rev_parse", side_effect=["root", "parent"]),
        patch("atelier.worker.session.worktree.beads.update_changeset_branch_metadata"),
        patch(
            "atelier.worker.session.worktree.worktree_hooks.bootstrap_conventional_commit_hook"
        ) as bootstrap_hook,
    ):
        result = worktree.prepare_worktrees(
            context=worktree.WorktreePreparationContext(
                dry_run=False,
                project_data_dir=tmp_path,
                repo_root=Path("/repo"),
                beads_root=Path("/beads"),
                selected_epic="at-epic",
                changeset_id="at-epic.1",
                root_branch_value="feat/root",
                changeset_parent_branch="feat/root",
                git_path="git",
            ),
            control=_TestControl(logs),
        )

    assert result.epic_worktree_path == epic_path
    assert result.changeset_worktree_path == changeset_path
    calls = [call.args[0] for call in bootstrap_hook.call_args_list]
    assert calls == [epic_path, changeset_path]

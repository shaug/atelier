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
            allow_parent_branch_override=False,
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
            allow_parent_branch_override=False,
            git_path="git",
        ),
        control=_TestControl(logs),
    )

    assert result.changeset_worktree_path == result.epic_worktree_path
    assert result.branch == "feat/root"
    assert any("Changeset branch: feat/root" in line for line in logs)


def test_prepare_worktrees_reconciles_ownership_before_worktree_setup(tmp_path: Path) -> None:
    logs: list[str] = []
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True)
    changeset_worktree_path = tmp_path / "worktrees" / "at-gnc.1"
    changeset_worktree_path.mkdir(parents=True)
    (changeset_worktree_path / ".git").write_text("gitdir: /tmp/gitdir", encoding="utf-8")

    mapping = worktrees.WorktreeMapping(
        epic_id="at-gnc",
        worktree_path="worktrees/at-gnc",
        root_branch="feat/gnc",
        changesets={"at-gnc.1": "feat/gnc-at-gnc.1"},
        changeset_worktrees={"at-gnc.1": "worktrees/at-gnc.1"},
    )
    epics = [
        {
            "id": "at-gnc",
            "labels": ["at:epic"],
            "description": "workspace.root_branch: feat/gnc\n",
        },
        {
            "id": "at-1my",
            "labels": ["at:epic", "at:changeset"],
            "description": "workspace.root_branch: feat/1my\n",
        },
    ]
    descendants_by_epic = {
        "at-gnc": [{"id": "at-gnc.1"}],
        "at-1my": [{"id": "at-1my.1"}],
    }

    def fake_descendants(
        parent_id: str,
        *,
        beads_root: Path,
        cwd: Path,
        include_closed: bool = False,
    ) -> list[dict[str, object]]:
        del beads_root, cwd, include_closed
        return descendants_by_epic[parent_id]

    with (
        patch("atelier.worker.session.worktree.beads.run_bd_json", return_value=epics),
        patch(
            "atelier.worker.session.worktree.beads.list_descendant_changesets",
            side_effect=fake_descendants,
        ),
        patch(
            "atelier.worker.session.worktree.worktrees.reconcile_mapping_ownership",
            return_value=("at-1my", "at-gnc"),
        ) as reconcile_mapping,
        patch(
            "atelier.worker.session.worktree.worktrees.ensure_git_worktree",
            return_value=tmp_path / "worktrees" / "at-gnc",
        ),
        patch(
            "atelier.worker.session.worktree.worktrees.ensure_changeset_branch",
            return_value=("feat/gnc-at-gnc.1", mapping),
        ),
        patch("atelier.worker.session.worktree.beads.update_worktree_path"),
        patch(
            "atelier.worker.session.worktree.worktrees.ensure_changeset_worktree",
            return_value=changeset_worktree_path,
        ),
        patch("atelier.worker.session.worktree.worktrees.ensure_changeset_checkout"),
        patch("atelier.worker.session.worktree.git.git_rev_parse", return_value="abc1234"),
        patch("atelier.worker.session.worktree.beads.update_changeset_branch_metadata"),
    ):
        worktree.prepare_worktrees(
            context=worktree.WorktreePreparationContext(
                dry_run=False,
                project_data_dir=tmp_path,
                repo_root=repo_root,
                beads_root=tmp_path / "beads",
                selected_epic="at-gnc",
                changeset_id="at-gnc.1",
                root_branch_value="feat/gnc",
                changeset_parent_branch="feat/gnc",
                allow_parent_branch_override=False,
                git_path="git",
            ),
            control=_TestControl(logs),
        )

    reconcile_mapping.assert_called_once_with(
        tmp_path,
        owner_by_changeset={
            "at-gnc.1": "at-gnc",
            "at-1my": "at-1my",
            "at-1my.1": "at-1my",
        },
        epic_root_branches={
            "at-gnc": "feat/gnc",
            "at-1my": "feat/1my",
        },
    )
    assert any("Reconciled mapping ownership: at-1my, at-gnc" in line for line in logs)

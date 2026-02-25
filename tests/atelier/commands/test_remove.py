import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import atelier.commands.remove as remove_cmd
import atelier.config as config


def test_remove_project_dry_run_does_not_mutate() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        project_dir = root / "project-data"
        repo_root = root / "repo"
        project_dir.mkdir(parents=True, exist_ok=True)
        repo_root.mkdir(parents=True, exist_ok=True)
        project_config = config.ProjectConfig()

        with (
            patch(
                "atelier.commands.remove.resolve_current_project_with_repo_root",
                return_value=(project_dir, project_config, str(repo_root), repo_root),
            ),
            patch(
                "atelier.commands.remove.config.resolve_project_data_dir",
                return_value=project_dir,
            ),
            patch(
                "atelier.commands.remove._managed_worktrees_from_git",
                return_value=[project_dir / "worktrees" / "at-1"],
            ),
            patch(
                "atelier.commands.remove._collect_mapped_branches",
                return_value={"feat/test"},
            ),
            patch("atelier.commands.remove.confirm") as confirm,
            patch("atelier.commands.remove.gc_cmd.gc") as run_gc,
            patch("atelier.commands.remove.shutil.rmtree") as rmtree,
        ):
            remove_cmd.remove_project(
                SimpleNamespace(
                    yes=False,
                    dry_run=True,
                    gc=False,
                    reconcile=False,
                    prune_branches=False,
                )
            )

        confirm.assert_not_called()
        run_gc.assert_not_called()
        rmtree.assert_not_called()
        assert project_dir.exists()


def test_remove_project_applies_cleanup_and_deletes_project_dir() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        project_dir = root / "project-data"
        repo_root = root / "repo"
        project_dir.mkdir(parents=True, exist_ok=True)
        repo_root.mkdir(parents=True, exist_ok=True)
        (project_dir / "state.txt").write_text("ok", encoding="utf-8")
        project_config = config.ProjectConfig()
        managed_worktree = project_dir / "worktrees" / "at-1"

        with (
            patch(
                "atelier.commands.remove.resolve_current_project_with_repo_root",
                return_value=(project_dir, project_config, str(repo_root), repo_root),
            ),
            patch(
                "atelier.commands.remove.config.resolve_project_data_dir",
                return_value=project_dir,
            ),
            patch(
                "atelier.commands.remove._managed_worktrees_from_git",
                side_effect=[[managed_worktree], [managed_worktree]],
            ),
            patch(
                "atelier.commands.remove._collect_mapped_branches",
                return_value={"main", "feat/test"},
            ),
            patch(
                "atelier.commands.remove._stop_worker_process",
                return_value=True,
            ),
            patch("atelier.commands.remove.gc_cmd.gc") as run_gc,
            patch("atelier.commands.remove._remove_worktree") as remove_worktree,
            patch("atelier.commands.remove._prune_worktree_registry") as prune_worktrees,
            patch(
                "atelier.commands.remove.git.git_default_branch",
                return_value="main",
            ),
            patch("atelier.commands.remove._delete_branch_refs") as delete_branch,
            patch("atelier.commands.remove.confirm") as confirm,
        ):
            remove_cmd.remove_project(
                SimpleNamespace(
                    yes=True,
                    dry_run=False,
                    gc=True,
                    reconcile=True,
                    prune_branches=True,
                )
            )

        confirm.assert_not_called()
        run_gc.assert_called_once()
        remove_worktree.assert_called_once_with(
            repo_root,
            managed_worktree,
            git_path="git",
        )
        prune_worktrees.assert_called_once_with(repo_root, git_path="git")
        delete_branch.assert_called_once_with(repo_root, "feat/test", git_path="git")
        assert not project_dir.exists()

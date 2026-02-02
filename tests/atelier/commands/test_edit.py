from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import atelier.commands.edit as edit_cmd
import atelier.config as config
import atelier.worktrees as worktrees


def test_edit_opens_workspace_repo_in_editor(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    project_data_dir = tmp_path / "data"
    project_data_dir.mkdir()
    worktree_path = project_data_dir / "worktrees" / "at-epic"
    worktree_path.mkdir(parents=True)
    (worktree_path / ".git").write_text("gitdir: /tmp\n", encoding="utf-8")

    project_config = config.ProjectConfig()
    env = {"ATELIER_WORKSPACE": "feat/root"}
    issue = {
        "id": "at-epic",
        "title": "Epic",
        "status": "open",
        "labels": ["workspace:feat/root"],
        "description": "workspace.root_branch: feat/root\n",
    }
    mapping = worktrees.WorktreeMapping(
        epic_id="at-epic",
        worktree_path="worktrees/at-epic",
        root_branch="feat/root",
        changesets={},
    )

    with (
        patch(
            "atelier.commands.edit.resolve_current_project_with_repo_root",
            return_value=(project_root, project_config, "/repo", repo_root),
        ),
        patch(
            "atelier.commands.edit.config.resolve_project_data_dir",
            return_value=project_data_dir,
        ),
        patch(
            "atelier.commands.edit.config.resolve_beads_root",
            return_value=Path("/beads"),
        ),
        patch(
            "atelier.commands.edit.beads.find_epics_by_root_branch",
            return_value=[issue],
        ),
        patch(
            "atelier.commands.edit.worktrees.load_mapping",
            return_value=mapping,
        ),
        patch(
            "atelier.commands.edit.editor.resolve_editor_command",
            return_value=["code"],
        ),
        patch(
            "atelier.commands.edit.workspace.workspace_environment",
            return_value=env,
        ),
        patch("atelier.commands.edit.exec.run_command_detached") as run_detached,
    ):
        edit_cmd.open_workspace_editor(
            SimpleNamespace(
                workspace_name="feat/root",
                raw=False,
                workspace_root=False,
                set_title=False,
            )
        )

    run_detached.assert_called_once_with(
        ["code", str(worktree_path)], cwd=worktree_path, env=env
    )

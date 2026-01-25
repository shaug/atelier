"""Implementation for the ``atelier work`` command.

Opens the workspace repo in the configured work editor without creating new
workspaces.
"""

from __future__ import annotations

from .. import config, editor, exec, git, term, workspace
from ..io import die
from .resolve import resolve_current_project, resolve_workspace_target


def open_workspace_repo(args: object) -> None:
    """Open the workspace repo (or root) in the configured work editor."""
    workspace_name = getattr(args, "workspace_name", None)
    if not workspace_name:
        die("workspace branch must not be empty")
    workspace_root = bool(getattr(args, "workspace_root", False))

    project_root, project_config, enlistment_path = resolve_current_project()
    project_enlistment = project_config.project.enlistment or enlistment_path

    git_path = config.resolve_git_path(project_config)
    branch, workspace_dir = resolve_workspace_target(
        project_root=project_root,
        project_config=project_config,
        enlistment_path=enlistment_path,
        workspace_name=str(workspace_name),
        raw=False,
        git_path=git_path,
    )

    repo_dir = workspace_dir / "repo"
    if not repo_dir.exists():
        die(f"workspace repo missing for {branch}")
    if not git.git_is_repo(repo_dir, git_path=git_path):
        die("workspace repo exists but is not a git repository")

    editor_cmd = editor.resolve_editor_command(project_config, role="work")
    target_path = workspace_dir if workspace_root else repo_dir
    env = workspace.workspace_environment(
        project_enlistment,
        branch,
        workspace_dir,
    )
    if bool(getattr(args, "set_title", False)):
        title = term.workspace_title(project_enlistment, branch)
        term.emit_title_escape(title)
    exec.run_command_detached(
        [*editor_cmd, str(target_path)],
        cwd=workspace_dir,
        env=env,
    )

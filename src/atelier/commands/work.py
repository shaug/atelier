"""Implementation for the ``atelier work`` command."""

from __future__ import annotations

from pathlib import Path

from .. import config, editor, exec, git, paths, workspace
from ..io import die


def _resolve_project() -> tuple[Path, config.ProjectConfig, str]:
    cwd = Path.cwd()
    _, enlistment_path, _, origin = git.resolve_repo_enlistment(cwd)
    project_root = paths.project_dir_for_enlistment(enlistment_path, origin)
    config_path = paths.project_config_path(project_root)
    config_payload = config.load_project_config(config_path)
    if not config_payload:
        die("no Atelier project config found for this repo; run 'atelier init'")
    project_enlistment = config_payload.project.enlistment
    if project_enlistment and project_enlistment != enlistment_path:
        die("project enlistment does not match current repo path")
    return project_root, config_payload, enlistment_path


def open_workspace_repo(args: object) -> None:
    """Open the workspace repo in the configured work editor."""
    workspace_name = getattr(args, "workspace_name", None)
    if not workspace_name:
        die("workspace branch must not be empty")

    project_root, project_config, enlistment_path = _resolve_project()

    normalized = workspace.normalize_workspace_name(str(workspace_name))
    if not normalized:
        die("workspace branch must not be empty")

    branch, workspace_dir, exists = workspace.resolve_workspace_target(
        project_root,
        project_config.project.enlistment or enlistment_path,
        normalized,
        project_config.branch.prefix,
        False,
    )
    if not exists:
        die(f"workspace not found: {normalized}")

    repo_dir = workspace_dir / "repo"
    if not repo_dir.exists():
        die(f"workspace repo missing for {branch}")
    if not git.git_is_repo(repo_dir):
        die("workspace repo exists but is not a git repository")

    editor_cmd = editor.resolve_editor_command(project_config, role="work")
    exec.run_command_detached([*editor_cmd, str(repo_dir)], cwd=workspace_dir)

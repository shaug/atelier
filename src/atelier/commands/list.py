"""Implementation for the ``atelier list`` command."""

from pathlib import Path

from .. import config, git, paths, workspace
from ..io import die, say


def list_workspaces(args: object) -> None:
    """List workspaces for the current project."""
    cwd = Path.cwd()
    repo_root, enlistment_path, _, origin = git.resolve_repo_enlistment(cwd)
    project_root = paths.project_dir_for_enlistment(enlistment_path, origin)
    config_path = paths.project_config_path(project_root)
    config_payload = config.load_project_config(config_path)
    if not config_payload:
        die("no Atelier project config found for this repo; run 'atelier init'")
    project_enlistment = config_payload.project.enlistment
    if project_enlistment and project_enlistment != enlistment_path:
        die("project enlistment does not match current repo path")

    git_path = config.resolve_git_path(config_payload)

    workspaces = workspace.collect_workspaces(
        project_root,
        config_payload,
        with_status=False,
        enlistment_repo_dir=repo_root,
        git_path=git_path,
    )
    if not workspaces:
        say("No workspaces found.")
        return

    for item in workspaces:
        say(item["name"])

"""Implementation for the ``atelier list`` command."""

from .. import config, workspace
from ..io import say
from .resolve import resolve_current_project_with_repo_root


def list_workspaces(args: object) -> None:
    """List workspaces for the current project."""
    project_root, config_payload, enlistment_path, repo_root = (
        resolve_current_project_with_repo_root()
    )
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

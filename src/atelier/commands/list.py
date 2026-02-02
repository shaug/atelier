"""Implementation for the ``atelier list`` command."""

from .. import beads, config
from ..io import say
from .resolve import resolve_current_project_with_repo_root


def list_workspaces(args: object) -> None:
    """List workspaces for the current project."""
    project_root, config_payload, _enlistment_path, repo_root = (
        resolve_current_project_with_repo_root()
    )
    project_data_dir = config.resolve_project_data_dir(project_root, config_payload)
    beads_root = config.resolve_beads_root(project_data_dir, repo_root)
    beads.run_bd_command(["prime"], beads_root=beads_root, cwd=repo_root)
    issues = beads.run_bd_json(
        ["list", "--label", "at:epic"], beads_root=beads_root, cwd=repo_root
    )
    names: list[str] = []
    for issue in issues:
        status = str(issue.get("status") or "").lower()
        if status in {"closed", "done"}:
            continue
        root_branch = beads.extract_workspace_root_branch(issue)
        if root_branch:
            names.append(root_branch)
    if not names:
        say("No workspaces found.")
        return
    for name in sorted(set(names)):
        say(name)

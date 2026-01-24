"""Implementation for the ``atelier list`` command."""

from pathlib import Path

from .. import config, git, paths, workspace
from ..io import die, say


def list_workspaces(args: object) -> None:
    """List workspaces for the current project.

    Args:
        args: CLI argument object with a ``status`` flag.

    Returns:
        None.

    Example:
        $ atelier list --status
    """
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

    workspaces = workspace.collect_workspaces(
        project_root,
        config_payload,
        with_status=getattr(args, "status", False),
        enlistment_repo_dir=repo_root,
    )
    if not workspaces:
        say("No workspaces found.")
        return

    if not getattr(args, "status", False):
        for item in workspaces:
            say(item["name"])
        return

    rows = [("workspace", "checked_out", "clean", "pushed")]
    for item in workspaces:
        rows.append(
            (
                item["name"],
                workspace.format_status(item["checked_out"]),
                workspace.format_status(item["clean"]),
                workspace.format_status(item["pushed"]),
            )
        )

    widths = [max(len(row[index]) for row in rows) for index in range(len(rows[0]))]
    for row in rows:
        say(
            "  ".join(
                value.ljust(widths[index]) for index, value in enumerate(row)
            ).rstrip()
        )

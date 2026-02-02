"""Implementation for the ``atelier plan`` command."""

from __future__ import annotations

from .. import beads, config
from ..io import say
from .resolve import resolve_current_project_with_repo_root


def run_planner(args: object) -> None:
    """Start a planning session for Beads epics and changesets."""
    project_root, project_config, _enlistment, repo_root = (
        resolve_current_project_with_repo_root()
    )
    project_data_dir = config.resolve_project_data_dir(project_root, project_config)
    beads_root = config.resolve_beads_root(project_data_dir, repo_root)

    say("Beads planning session")
    beads.run_bd_command(["prime"], beads_root=beads_root, cwd=repo_root)

    if bool(getattr(args, "create_epic", False)):
        beads.run_bd_command(
            ["create-form", "--type", "epic", "--label", "at:epic"],
            beads_root=beads_root,
            cwd=repo_root,
        )

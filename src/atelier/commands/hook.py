"""Hook command implementation for hook-capable runtimes."""

from __future__ import annotations

import os

from .. import beads, config, hooks
from ..io import say
from .resolve import resolve_current_project_with_repo_root


def _issue_title(issue_id: str, *, beads_root, repo_root) -> str | None:
    issues = beads.run_bd_json(["show", issue_id], beads_root=beads_root, cwd=repo_root)
    if not issues:
        return None
    title = issues[0].get("title")
    return str(title) if title else None


def run_hook(args: object) -> None:
    """Run a hook event handler for agent runtimes."""
    project_root, project_config, _enlistment, repo_root = (
        resolve_current_project_with_repo_root()
    )
    project_data_dir = config.resolve_project_data_dir(project_root, project_config)
    beads_root = config.resolve_beads_root(project_data_dir, repo_root)
    event = hooks.parse_hook_event(getattr(args, "event", None))

    if event in {"session-start", "pre-compact"}:
        beads.run_bd_command(["prime"], beads_root=beads_root, cwd=repo_root)

    if event != "session-start":
        return

    epic_id = os.environ.get("ATELIER_EPIC_ID", "").strip()
    changeset_id = os.environ.get("ATELIER_CHANGESET_ID", "").strip()
    if epic_id:
        title = _issue_title(epic_id, beads_root=beads_root, repo_root=repo_root)
        label = f"{epic_id}"
        if title:
            label = f"{label} {title}"
        say(f"Epic: {label}")
    if changeset_id:
        title = _issue_title(changeset_id, beads_root=beads_root, repo_root=repo_root)
        label = f"{changeset_id}"
        if title:
            label = f"{label} {title}"
        say(f"Changeset: {label}")

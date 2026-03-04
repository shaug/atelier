"""Implementation for the ``atelier doctor`` command."""

from __future__ import annotations

import json
from typing import Mapping

from rich import box
from rich.console import Console
from rich.table import Table

from .. import beads, config, prefix_migration_drift, prs
from ..io import die, say
from .resolve import resolve_current_project_with_repo_root

_FORMATS = {"table", "json"}


def doctor(args: object) -> None:
    """Detect and optionally repair prefix-migration drift."""
    format_value = str(getattr(args, "format", "table") or "table").lower()
    if format_value not in _FORMATS:
        die(f"unsupported format: {format_value}")

    fix = bool(getattr(args, "fix", False))
    project_root, project_config, _enlistment, repo_root = resolve_current_project_with_repo_root()
    project_data_dir = config.resolve_project_data_dir(project_root, project_config)
    beads_root = config.resolve_beads_root(project_data_dir, repo_root)
    git_path = config.resolve_git_path(project_config)

    beads.run_bd_command(["prime"], beads_root=beads_root, cwd=repo_root)
    origin = project_config.project.origin or project_config.project.repo_url
    repo_slug = prs.github_repo_slug(origin)
    actions = prefix_migration_drift.repair_prefix_migration_drift(
        project_data_dir=project_data_dir,
        beads_root=beads_root,
        repo_root=repo_root,
        apply=fix,
        repo_slug=repo_slug,
        git_path=git_path,
    )
    counts = _doctor_counts(actions)
    mode = "fix" if fix else "check"
    project_info = {
        "project_dir": str(project_root),
        "repo_root": str(repo_root),
        "beads_root": str(beads_root),
    }
    payload = {
        "scope": "project",
        "mode": mode,
        "fix": fix,
        "project": project_info,
        "counts": counts,
        "prefix_migration_drift": [action.as_dict() for action in actions],
    }
    if format_value == "json":
        say(json.dumps(payload, indent=2, sort_keys=True))
        return
    _render_doctor(project_info, counts, actions, fix=fix)


def _doctor_counts(
    actions: list[prefix_migration_drift.PrefixMigrationRepairAction],
) -> dict[str, int]:
    changed = sum(1 for action in actions if action.changed)
    applied = sum(1 for action in actions if action.applied and action.changed)
    return {
        "changesets_drifted": len(actions),
        "changesets_changed": changed,
        "changesets_applied": applied,
    }


def _render_doctor(
    project_info: Mapping[str, str],
    counts: Mapping[str, int],
    actions: list[prefix_migration_drift.PrefixMigrationRepairAction],
    *,
    fix: bool,
) -> None:
    console = Console()
    overview = Table(title="Prefix Migration Doctor", box=box.SIMPLE, show_header=False)
    overview.add_column("Field", style="bold")
    overview.add_column("Value", overflow="fold")
    overview.add_row("Project dir", _display_value(project_info.get("project_dir")))
    overview.add_row("Repo root", _display_value(project_info.get("repo_root")))
    overview.add_row("Beads root", _display_value(project_info.get("beads_root")))
    overview.add_row("Mode", "fix" if fix else "check")
    overview.add_row(
        "Drifted changesets",
        _display_value(counts.get("changesets_drifted")),
    )
    overview.add_row(
        "Changesets needing updates",
        _display_value(counts.get("changesets_changed")),
    )
    overview.add_row(
        "Changesets updated",
        _display_value(counts.get("changesets_applied")),
    )
    console.print(overview)
    if not actions:
        console.print("No prefix-migration drift detected.")
        return

    table = Table(title="Drift Details", box=box.SIMPLE)
    table.add_column("Changeset", no_wrap=True)
    table.add_column("Drift", overflow="fold")
    table.add_column("Canonical", overflow="fold")
    table.add_column("Worktree", overflow="fold")
    table.add_column("Action", overflow="fold")
    for action in actions:
        canonical = (
            f"root={action.canonical_root_branch}, "
            f"work={action.canonical_work_branch} ({action.work_branch_source})"
        )
        worktree = f"{action.canonical_worktree_path} ({action.worktree_path_source})"
        table.add_row(
            action.changeset_id,
            ", ".join(action.drift_classes),
            canonical,
            worktree,
            _action_summary(action),
        )
    console.print(table)
    if not fix:
        console.print("Run `atelier doctor --fix` to apply the planned updates.")


def _action_summary(action: prefix_migration_drift.PrefixMigrationRepairAction) -> str:
    targets: list[str] = []
    if action.update_workspace_root_branch:
        targets.append("workspace.root_branch")
    if action.update_changeset_metadata:
        targets.append("changeset lineage metadata")
    if action.update_changeset_worktree_path:
        targets.append("changeset worktree_path metadata")
    if action.update_mapping:
        targets.append("worktree mapping")
    if not targets:
        return "no-op"
    if action.applied:
        return "updated " + ", ".join(targets)
    return "would update " + ", ".join(targets)


def _display_value(value: object) -> str:
    if value is None or value == "":
        return "unknown"
    return str(value)

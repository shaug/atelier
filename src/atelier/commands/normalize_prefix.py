"""Implementation for the ``atelier normalize-prefix`` command."""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from rich import box
from rich.console import Console
from rich.table import Table

from .. import agent_home, beads, config, prefix_migration_drift, prs
from ..io import die, say
from .resolve import resolve_current_project_with_repo_root

_FORMATS = {"table", "json"}
_ACTIVE_HOOK_STALE_HOURS = 24.0


@dataclass(frozen=True)
class _ActiveHookBlocker:
    agent_id: str
    hook_bead: str
    session_state: str
    heartbeat_at: str | None


def normalize_prefix(args: object) -> None:
    """Run explicit prefix normalization in dry-run or apply mode.

    Args:
        args: CLI args namespace with ``format``, ``apply``, and ``force``.

    Returns:
        None.
    """
    format_value = str(getattr(args, "format", "table") or "table").lower()
    if format_value not in _FORMATS:
        die(f"unsupported format: {format_value}")

    apply = bool(getattr(args, "apply", False))
    force = bool(getattr(args, "force", False))

    project_root, project_config, _enlistment, repo_root = resolve_current_project_with_repo_root()
    project_data_dir = config.resolve_project_data_dir(project_root, project_config)
    beads_root = config.resolve_beads_root(project_data_dir, repo_root)
    git_path = config.resolve_git_path(project_config)

    beads.run_bd_command(["prime"], beads_root=beads_root, cwd=repo_root)
    if apply and not force:
        blockers = _active_agent_hook_blockers(beads_root=beads_root, repo_root=repo_root)
        if blockers:
            die(_active_hook_blockers_message(blockers))

    origin = project_config.project.origin or project_config.project.repo_url
    repo_slug = prs.github_repo_slug(origin)
    actions = prefix_migration_drift.repair_prefix_migration_drift(
        project_data_dir=project_data_dir,
        beads_root=beads_root,
        repo_root=repo_root,
        apply=apply,
        repo_slug=repo_slug,
        git_path=git_path,
    )

    changed = sum(1 for action in actions if action.changed)
    applied = sum(1 for action in actions if action.applied and action.changed)
    configured_prefix = config.resolve_beads_prefix(project_config)
    mode = "apply" if apply else "dry-run"
    project_info = {
        "project_dir": str(project_root),
        "repo_root": str(repo_root),
        "beads_root": str(beads_root),
        "configured_prefix": configured_prefix,
    }
    rollback_guidance = _rollback_guidance(project_data_dir=project_data_dir, beads_root=beads_root)
    payload = {
        "scope": "project",
        "scope_description": (
            "explicit prefix normalization for legacy metadata and mapping artifacts"
        ),
        "mode": mode,
        "apply": apply,
        "project": project_info,
        "counts": {
            "changesets_drifted": len(actions),
            "changesets_changed": changed,
            "changesets_applied": applied,
        },
        "safety_gate": {
            "active_hook_check": apply and not force,
            "force": force,
        },
        "rollback_guidance": rollback_guidance,
        "actions": [action.as_dict() for action in actions],
    }
    if format_value == "json":
        say(json.dumps(payload, indent=2, sort_keys=True))
        return
    _render_normalization_report(
        project_info=project_info,
        actions=actions,
        apply=apply,
        rollback_guidance=rollback_guidance,
    )


def _render_normalization_report(
    *,
    project_info: Mapping[str, str],
    actions: list[prefix_migration_drift.PrefixMigrationRepairAction],
    apply: bool,
    rollback_guidance: Mapping[str, str],
) -> None:
    console = Console()
    changed = sum(1 for action in actions if action.changed)
    applied = sum(1 for action in actions if action.applied and action.changed)

    overview = Table(title="Prefix Normalization", box=box.SIMPLE, show_header=False)
    overview.add_column("Field", style="bold")
    overview.add_column("Value", overflow="fold")
    overview.add_row("Project dir", _display_value(project_info.get("project_dir")))
    overview.add_row("Repo root", _display_value(project_info.get("repo_root")))
    overview.add_row("Beads root", _display_value(project_info.get("beads_root")))
    overview.add_row("Configured prefix", _display_value(project_info.get("configured_prefix")))
    overview.add_row("Mode", "apply" if apply else "dry-run")
    overview.add_row("Drifted changesets", _display_value(len(actions)))
    overview.add_row("Changesets with updates", _display_value(changed))
    overview.add_row("Changesets applied", _display_value(applied))
    console.print(overview)

    if actions:
        action_table = Table(title="Normalization Actions", box=box.SIMPLE)
        action_table.add_column("Changeset", no_wrap=True)
        action_table.add_column("Drift", overflow="fold")
        action_table.add_column("Canonical", overflow="fold")
        action_table.add_column("Worktree", overflow="fold")
        action_table.add_column("Action", overflow="fold")
        for action in sorted(actions, key=lambda item: (item.changeset_id, item.epic_id)):
            canonical = (
                f"root={action.canonical_root_branch}, "
                f"work={action.canonical_work_branch} ({action.work_branch_source})"
            )
            worktree = f"{action.canonical_worktree_path} ({action.worktree_path_source})"
            action_table.add_row(
                action.changeset_id,
                ", ".join(action.drift_classes),
                canonical,
                worktree,
                _action_summary(action),
            )
        console.print(action_table)
    else:
        console.print("No prefix normalization drift detected.")

    if apply:
        console.print("Rollback guidance:")
        console.print(f"- Export Beads state: {rollback_guidance['beads_export']}")
        console.print(f"- Backup mapping metadata: {rollback_guidance['mapping_backup']}")
        console.print(
            "Configured project prefix remains authoritative; this command does not edit config."
        )
    elif changed:
        console.print(
            "Run `atelier normalize-prefix --apply` to persist canonical metadata alignment."
        )


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


def _rollback_guidance(*, project_data_dir: Path, beads_root: Path) -> dict[str, str]:
    timestamp = dt.datetime.now(tz=dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    meta_dir = project_data_dir / "worktrees" / ".meta"
    meta_backup = project_data_dir / "worktrees" / f".meta.backup-{timestamp}"
    beads_backup = f"prefix-normalize-beads-{timestamp}.jsonl"
    return {
        "beads_export": f'BEADS_DIR="{beads_root}" bd export > "{beads_backup}"',
        "mapping_backup": f'cp -R "{meta_dir}" "{meta_backup}"',
    }


def _active_agent_hook_blockers(
    *,
    beads_root: Path,
    repo_root: Path,
) -> list[_ActiveHookBlocker]:
    stale_delta = dt.timedelta(hours=_ACTIVE_HOOK_STALE_HOURS)
    now = dt.datetime.now(tz=dt.timezone.utc)
    blockers: list[_ActiveHookBlocker] = []

    issues = beads.run_bd_json(
        ["list", "--label", beads.issue_label("agent", beads_root=beads_root)],
        beads_root=beads_root,
        cwd=repo_root,
    )
    for issue in issues:
        description = issue.get("description")
        fields = beads.parse_description_fields(description if isinstance(description, str) else "")
        agent_id = _normalize_text(fields.get("agent_id")) or _normalize_text(issue.get("title"))
        if agent_id is None:
            agent_id = _normalize_text(issue.get("id"))
        if agent_id is None:
            continue

        hook_bead = _agent_hook_for_issue_no_write(
            issue, beads_root=beads_root, repo_root=repo_root
        )
        if hook_bead is None:
            continue

        heartbeat_at = (
            fields.get("heartbeat_at") if isinstance(fields.get("heartbeat_at"), str) else None
        )
        session_state = _agent_hook_session_state(
            agent_id,
            heartbeat_at=heartbeat_at,
            now=now,
            stale_delta=stale_delta,
        )
        if session_state == "stale":
            continue
        blockers.append(
            _ActiveHookBlocker(
                agent_id=agent_id,
                hook_bead=hook_bead,
                session_state=session_state,
                heartbeat_at=heartbeat_at,
            )
        )
    return sorted(blockers, key=lambda blocker: blocker.agent_id)


def _agent_hook_for_issue_no_write(
    issue: dict[str, object],
    *,
    beads_root: Path,
    repo_root: Path,
) -> str | None:
    issue_id = _normalize_text(issue.get("id"))
    if issue_id:
        result = beads.run_bd_command(
            ["slot", "show", issue_id, "--json"],
            beads_root=beads_root,
            cwd=repo_root,
            allow_failure=True,
        )
        if result.returncode == 0:
            raw = result.stdout.strip() if result.stdout else ""
            if raw:
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    payload = None
                hook = _extract_hook_from_slot_payload(payload)
                if hook:
                    return hook

    description = issue.get("description")
    fields = beads.parse_description_fields(description if isinstance(description, str) else "")
    return _normalize_text(fields.get("hook_bead"))


def _extract_hook_from_slot_payload(payload: object) -> str | None:
    if isinstance(payload, str):
        return _normalize_text(payload)
    if isinstance(payload, list):
        for item in payload:
            hook = _extract_hook_from_slot_payload(item)
            if hook:
                return hook
        return None
    if not isinstance(payload, dict):
        return None
    if "hook" in payload:
        return _extract_hook_from_slot_payload(payload.get("hook"))
    slots = payload.get("slots")
    if isinstance(slots, dict):
        return _extract_hook_from_slot_payload(slots.get("hook"))
    for key in ("id", "issue_id", "bead_id", "bead"):
        value = _normalize_text(payload.get(key))
        if value:
            return value
    return None


def _agent_hook_session_state(
    agent_id: str,
    *,
    heartbeat_at: str | None,
    now: dt.datetime,
    stale_delta: dt.timedelta,
) -> str:
    if agent_home.session_pid_from_agent_id(agent_id) is not None:
        return "live" if agent_home.is_session_agent_active(agent_id) else "stale"
    heartbeat = _parse_rfc3339(heartbeat_at)
    if heartbeat is None:
        return "unknown"
    age = now - heartbeat
    if age > stale_delta:
        return "stale"
    return "live"


def _parse_rfc3339(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw.replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


def _normalize_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned or cleaned.lower() == "null":
        return None
    return cleaned


def _active_hook_blockers_message(blockers: list[_ActiveHookBlocker]) -> str:
    lines = [
        "refusing `atelier normalize-prefix --apply`: active agent hooks detected",
        "running with active workers can race metadata and mapping writes",
        "re-run after workers stop, or pass `--force` to override this safety gate",
    ]
    for blocker in blockers:
        heartbeat = blocker.heartbeat_at or "missing"
        lines.append(
            "- agent="
            f"{blocker.agent_id} hook={blocker.hook_bead} state={blocker.session_state} "
            f"heartbeat_at={heartbeat}"
        )
    return "\n".join(lines)


__all__ = ["normalize_prefix"]

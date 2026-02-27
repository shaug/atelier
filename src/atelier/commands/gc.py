"""Garbage collection for stale Atelier state."""

from __future__ import annotations

from .. import config
from ..gc import GcAction
from ..gc import agents as gc_agents
from ..gc import hooks as gc_hooks
from ..gc import labels as gc_labels
from ..gc import messages as gc_messages
from ..gc import reconcile as gc_reconcile
from ..gc import worktrees as gc_worktrees
from ..gc.common import log_debug
from ..io import confirm, say, warn
from . import work as work_cmd
from .resolve import resolve_current_project_with_repo_root


def gc(args: object) -> None:
    """Garbage collect stale hooks and orphaned worktrees."""
    project_root, project_config, _enlistment, repo_root = resolve_current_project_with_repo_root()
    project_data_dir = config.resolve_project_data_dir(project_root, project_config)
    beads_root = config.resolve_beads_root(project_data_dir, repo_root)

    stale_hours = getattr(args, "stale_hours", 24.0)
    try:
        stale_hours = float(stale_hours)
    except (TypeError, ValueError):
        warn("invalid --stale-hours value; defaulting to 24")
        stale_hours = 24.0
    if stale_hours < 0:
        stale_hours = 0

    dry_run = bool(getattr(args, "dry_run", False))
    yes = bool(getattr(args, "yes", False))
    reconcile = bool(getattr(args, "reconcile", False))
    include_missing_heartbeat = bool(getattr(args, "stale_if_missing_heartbeat", False))
    log_debug(
        "gc start "
        f"dry_run={dry_run} yes={yes} reconcile={reconcile} "
        f"stale_hours={stale_hours} include_missing_heartbeat={include_missing_heartbeat}"
    )

    if reconcile:
        git_path = config.resolve_git_path(project_config)
        candidates = work_cmd.list_reconcile_epic_candidates(
            project_config=project_config,
            beads_root=beads_root,
            repo_root=repo_root,
            git_path=git_path,
        )
        if not candidates:
            say("No reconcile candidates.")
            log_debug("reconcile candidates none")
        if dry_run or yes:
            if not candidates:
                say("Reconcile blocked changesets: scanned=0, actionable=0, reconciled=0, failed=0")
                return
            for epic_id, changesets in candidates.items():
                log_debug(
                    f"reconcile candidate epic={epic_id} "
                    f"changesets={len(changesets)} "
                    f"mode={'dry-run' if dry_run else 'yes'}"
                )
                say(f"Reconcile candidate: epic {epic_id} ({len(changesets)} merged changesets)")
                for detail in gc_reconcile.reconcile_preview_lines(
                    epic_id,
                    changesets,
                    project_dir=project_data_dir,
                    beads_root=beads_root,
                    repo_root=repo_root,
                ):
                    say(f"- {detail}")
            reconcile_result = work_cmd.reconcile_blocked_merged_changesets(
                agent_id="atelier/system/gc",
                agent_bead_id="",
                project_config=project_config,
                project_data_dir=project_data_dir,
                beads_root=beads_root,
                repo_root=repo_root,
                git_path=git_path,
                dry_run=dry_run,
                log=say,
            )
            say(
                "Reconcile blocked changesets: "
                f"scanned={reconcile_result.scanned}, "
                f"actionable={reconcile_result.actionable}, "
                f"reconciled={reconcile_result.reconciled}, "
                f"failed={reconcile_result.failed}"
            )
            log_debug(
                "reconcile totals "
                f"scanned={reconcile_result.scanned} "
                f"actionable={reconcile_result.actionable} "
                f"reconciled={reconcile_result.reconciled} "
                f"failed={reconcile_result.failed}"
            )
        else:
            total_scanned = 0
            total_actionable = 0
            total_reconciled = 0
            total_failed = 0
            for epic_id, changesets in candidates.items():
                preview = ", ".join(changesets[:3])
                if len(changesets) > 3:
                    preview = f"{preview}, +{len(changesets) - 3} more"
                prompt_text = (
                    f"Reconcile epic {epic_id} ({len(changesets)} merged changesets: {preview})?"
                )
                say(f"Reconcile candidate: epic {epic_id}")
                for detail in gc_reconcile.reconcile_preview_lines(
                    epic_id,
                    changesets,
                    project_dir=project_data_dir,
                    beads_root=beads_root,
                    repo_root=repo_root,
                ):
                    say(f"- {detail}")
                if not confirm(prompt_text, default=False):
                    say(f"Skipped reconcile: epic {epic_id}")
                    log_debug(f"reconcile skipped epic={epic_id}")
                    continue
                reconcile_result = work_cmd.reconcile_blocked_merged_changesets(
                    agent_id="atelier/system/gc",
                    agent_bead_id="",
                    project_config=project_config,
                    project_data_dir=project_data_dir,
                    beads_root=beads_root,
                    repo_root=repo_root,
                    git_path=git_path,
                    epic_filter=epic_id,
                    changeset_filter=set(changesets),
                    dry_run=False,
                    log=say,
                )
                total_scanned += reconcile_result.scanned
                total_actionable += reconcile_result.actionable
                total_reconciled += reconcile_result.reconciled
                total_failed += reconcile_result.failed
                say(
                    f"Reconcile epic {epic_id}: "
                    f"scanned={reconcile_result.scanned}, "
                    f"actionable={reconcile_result.actionable}, "
                    f"reconciled={reconcile_result.reconciled}, "
                    f"failed={reconcile_result.failed}"
                )
                log_debug(
                    f"reconcile epic={epic_id} "
                    f"scanned={reconcile_result.scanned} "
                    f"actionable={reconcile_result.actionable} "
                    f"reconciled={reconcile_result.reconciled} "
                    f"failed={reconcile_result.failed}"
                )
            say(
                "Reconcile blocked changesets: "
                f"scanned={total_scanned}, "
                f"actionable={total_actionable}, "
                f"reconciled={total_reconciled}, "
                f"failed={total_failed}"
            )
            log_debug(
                "reconcile totals "
                f"scanned={total_scanned} actionable={total_actionable} "
                f"reconciled={total_reconciled} failed={total_failed}"
            )

    actions: list[GcAction] = []
    actions.extend(
        gc_labels.collect_normalize_changeset_labels(
            beads_root=beads_root,
            repo_root=repo_root,
        )
    )
    actions.extend(
        gc_labels.collect_backfill_epic_identity_labels(
            beads_root=beads_root,
            repo_root=repo_root,
        )
    )
    for label, detail in [
        ("at:changeset", "changeset role inferred from graph"),
        ("at:subtask", "subtask role inferred from graph"),
        ("at:ready", "readiness inferred from open status"),
        ("at:draft", "draft state inferred from deferred status"),
    ]:
        actions.extend(
            gc_labels.collect_remove_deprecated_label(
                label=label,
                detail=detail,
                beads_root=beads_root,
                repo_root=repo_root,
            )
        )
    for label, detail in [
        ("cs:ready", "readiness inferred from open status"),
        ("cs:in_progress", "progress inferred from in_progress status"),
        ("cs:blocked", "block state inferred from blocked status"),
        ("cs:planned", "planned state inferred from deferred status"),
    ]:
        actions.extend(
            gc_labels.collect_remove_deprecated_label(
                label=label,
                detail=detail,
                beads_root=beads_root,
                repo_root=repo_root,
            )
        )
    actions.extend(
        gc_labels.collect_normalize_epic_labels(
            beads_root=beads_root,
            repo_root=repo_root,
        )
    )
    actions.extend(
        gc_hooks.collect_hooks(
            beads_root=beads_root,
            repo_root=repo_root,
            stale_hours=stale_hours,
            include_missing_heartbeat=include_missing_heartbeat,
        )
    )
    actions.extend(
        gc_worktrees.collect_orphan_worktrees(
            project_dir=project_data_dir,
            beads_root=beads_root,
            repo_root=repo_root,
            git_path=config.resolve_git_path(project_config),
            assume_yes=yes,
        )
    )
    actions.extend(
        gc_worktrees.collect_resolved_epic_artifacts(
            project_dir=project_data_dir,
            beads_root=beads_root,
            repo_root=repo_root,
            git_path=config.resolve_git_path(project_config),
            assume_yes=yes,
        )
    )
    actions.extend(
        gc_worktrees.collect_closed_workspace_branches_without_mapping(
            project_dir=project_data_dir,
            beads_root=beads_root,
            repo_root=repo_root,
            git_path=config.resolve_git_path(project_config),
        )
    )
    actions.extend(
        gc_messages.collect_message_claims(
            beads_root=beads_root,
            repo_root=repo_root,
            stale_hours=stale_hours,
        )
    )
    actions.extend(
        gc_messages.collect_message_retention(
            beads_root=beads_root,
            repo_root=repo_root,
        )
    )
    actions.extend(
        gc_agents.collect_agent_homes(
            project_dir=project_data_dir,
            beads_root=beads_root,
            repo_root=repo_root,
        )
    )

    if not actions:
        say("No GC actions needed.")
        log_debug("gc no actions")
        return

    for action in actions:
        log_debug(f"gc action queued description={action.description}")
        say(f"GC action: {action.description}")
        for detail in action.details:
            say(f"- {detail}")
        if dry_run:
            say(f"Would: {action.description}")
            log_debug(f"gc action dry-run description={action.description}")
            continue
        if yes or confirm(f"{action.description}?", default=False):
            say(f"Running: {action.description}")
            log_debug(f"gc action run description={action.description}")
            action.apply()
            say(f"Done: {action.description}")
            log_debug(f"gc action done description={action.description}")
        else:
            say(f"Skipped: {action.description}")
            log_debug(f"gc action skipped description={action.description}")

"""Worker session command controller."""

from __future__ import annotations

import time
from pathlib import Path

from .. import agent_home, agent_teardown, beads, cli_defaults, config
from ..io import confirm, die, say
from ..worker import models as worker_models
from ..worker import restart_runtime as worker_restart_runtime
from ..worker import runtime as worker_runtime
from ..worker.context import WorkerRunContext
from ..worker.session import runner as worker_session_runner
from ..worker.work_command_helpers import (
    dry_run_log,
    list_reconcile_epic_candidates,
    normalize_mode,
    normalize_run_mode,
    normalize_startup_select,
    reconcile_blocked_merged_changesets,
    report_translated_cli_default,
    report_worker_summary,
    root_branch,
    watch_interval_seconds,
)
from .resolve import resolve_current_project_with_repo_root

__all__ = [
    "ReconcileResult",
    "list_reconcile_epic_candidates",
    "reconcile_blocked_merged_changesets",
    "root_branch",
    "start_worker",
]

ReconcileResult = worker_models.ReconcileResult


def _run_worker_once(
    args: object, *, mode: str, dry_run: bool, session_key: str
) -> worker_models.WorkerRunSummary:
    """Start a single worker session by selecting an epic and changeset."""
    runner_deps = worker_runtime.build_worker_runtime_dependencies(
        resolve_current_project_with_repo_root=resolve_current_project_with_repo_root,
        confirm_fn=confirm,
        die_fn=die,
        emit=say,
    )
    return worker_session_runner.run_worker_once(
        args,
        run_context=WorkerRunContext(mode=mode, dry_run=dry_run, session_key=session_key),
        deps=runner_deps,
    )


def start_worker(args: object) -> None:
    """Start worker sessions based on the configured run mode."""
    yes_default = cli_defaults.resolve_work_yes_default(bool(getattr(args, "yes", False)))
    report_translated_cli_default(yes_default)
    setattr(args, "yes", yes_default.value)
    setattr(args, "startup_runtime", worker_restart_runtime.capture_worker_startup_runtime())
    mode = normalize_mode(getattr(args, "mode", None))
    run_mode = normalize_run_mode(getattr(args, "run_mode", None))
    explicit_restart_on_update = getattr(args, "restart_on_update", None)
    restart_on_update = (
        bool(explicit_restart_on_update)
        if explicit_restart_on_update is not None
        else run_mode == "watch"
    )
    setattr(args, "restart_on_update", restart_on_update)
    watch_interval = watch_interval_seconds(getattr(args, "watch_interval", None))
    dry_run = bool(getattr(args, "dry_run", False))
    session_key = agent_home.generate_session_key()
    cleanup_agent: agent_home.AgentHome | None = None
    cleanup_project_dir: Path | None = None
    cleanup_beads_root: Path | None = None
    cleanup_repo_root: Path | None = None
    cleanup_agent_bead_id: str | None = None
    configured_select_default: str | None = None
    if not dry_run:
        (
            cleanup_project_root,
            cleanup_project_config,
            _cleanup_enlistment,
            cleanup_repo_root,
        ) = resolve_current_project_with_repo_root()
        configured_select_default = cleanup_project_config.worker.select
        cleanup_project_dir = config.resolve_project_data_dir(
            cleanup_project_root, cleanup_project_config
        )
        cleanup_beads_root = config.resolve_beads_root(cleanup_project_dir, cleanup_repo_root)
        cleanup_agent = agent_home.preview_agent_home(
            cleanup_project_dir,
            cleanup_project_config,
            role="worker",
            session_key=session_key,
        )
        agent_bead = beads.ensure_agent_bead(
            cleanup_agent.agent_id,
            beads_root=cleanup_beads_root,
            cwd=cleanup_repo_root,
            role="worker",
        )
        bead_id = agent_bead.get("id")
        cleanup_agent_bead_id = bead_id if isinstance(bead_id, str) and bead_id else None
        if cleanup_agent_bead_id is not None:
            setattr(args, "agent_bead_id", cleanup_agent_bead_id)
    select = normalize_startup_select(
        getattr(args, "select", None),
        configured_default=configured_select_default,
    )
    setattr(args, "select", select)
    try:
        worker_runtime.run_worker_sessions(
            args=args,
            mode=mode,
            run_mode=run_mode,
            dry_run=dry_run,
            session_key=session_key,
            run_worker_once=_run_worker_once,
            report_worker_summary=lambda summary, is_dry_run: report_worker_summary(
                summary, dry_run=is_dry_run
            ),
            watch_interval_seconds=lambda: watch_interval,
            dry_run_log=dry_run_log,
            emit=say,
            sleep_fn=time.sleep,
        )
    finally:
        if (
            cleanup_agent is not None
            and cleanup_beads_root is not None
            and cleanup_repo_root is not None
        ):
            agent_teardown.teardown_agent_runtime(
                beads_root=cleanup_beads_root,
                repo_root=cleanup_repo_root,
                agent_id=cleanup_agent.agent_id,
                agent_bead_id=cleanup_agent_bead_id,
                close_agent_bead=True,
            )
        if cleanup_agent is not None and cleanup_project_dir is not None:
            agent_home.cleanup_agent_home(cleanup_agent, project_dir=cleanup_project_dir)

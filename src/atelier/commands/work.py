"""Worker session command controller."""

from __future__ import annotations

import time

from .. import agent_home, config
from ..io import confirm, die, say
from ..worker import models as worker_models
from ..worker import runtime as worker_runtime
from ..worker.context import WorkerRunContext
from ..worker.session import runner as worker_session_runner
from ..worker.work_command_helpers import (
    _dry_run_log,
    _normalize_mode,
    _normalize_run_mode,
    _report_worker_summary,
    _watch_interval_seconds,
    list_reconcile_epic_candidates,
    reconcile_blocked_merged_changesets,
    root_branch,
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
    mode = _normalize_mode(getattr(args, "mode", None))
    run_mode = _normalize_run_mode(getattr(args, "run_mode", None))
    dry_run = bool(getattr(args, "dry_run", False))
    session_key = agent_home.generate_session_key()
    cleanup_agent: agent_home.AgentHome | None = None
    cleanup_project_dir = None
    if not dry_run:
        (
            cleanup_project_root,
            cleanup_project_config,
            _cleanup_enlistment,
            _cleanup_repo_root,
        ) = resolve_current_project_with_repo_root()
        cleanup_project_dir = config.resolve_project_data_dir(
            cleanup_project_root, cleanup_project_config
        )
        cleanup_agent = agent_home.preview_agent_home(
            cleanup_project_dir,
            cleanup_project_config,
            role="worker",
            session_key=session_key,
        )
    try:
        worker_runtime.run_worker_sessions(
            args=args,
            mode=mode,
            run_mode=run_mode,
            dry_run=dry_run,
            session_key=session_key,
            run_worker_once=_run_worker_once,
            report_worker_summary=lambda summary, is_dry_run: _report_worker_summary(
                summary, dry_run=is_dry_run
            ),
            watch_interval_seconds=_watch_interval_seconds,
            dry_run_log=_dry_run_log,
            emit=say,
            sleep_fn=time.sleep,
        )
    finally:
        if cleanup_agent is not None and cleanup_project_dir is not None:
            agent_home.cleanup_agent_home(cleanup_agent, project_dir=cleanup_project_dir)

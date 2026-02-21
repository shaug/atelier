"""Worker runtime loop orchestration helpers."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from .. import agent_home, agents, beads, branching, config, git, prs
from .. import root_branch as root_branch_module
from ..config import ProjectConfig
from . import work_command_helpers as worker_work
from .models import WorkerRunSummary
from .ports import (
    ConfirmFn,
    WorkerCommandService,
    WorkerControlPorts,
    WorkerInfrastructurePorts,
    WorkerLifecycleService,
    WorkerRuntimeDependencies,
)
from .session import agent as worker_session_agent
from .session import worktree as worker_session_worktree


class RunWorkerOnceFn(Protocol):
    def __call__(
        self, args: object, *, mode: str, dry_run: bool, session_key: str
    ) -> WorkerRunSummary: ...


class WorkerLifecycleAdapter:
    """Concrete lifecycle service object backed by worker helper functions."""

    def __init__(self) -> None:
        self.capture_review_feedback_snapshot = (
            worker_work._capture_review_feedback_snapshot
        )
        self.changeset_parent_branch = worker_work._changeset_parent_branch
        self.changeset_pr_url = worker_work._changeset_pr_url
        self.changeset_work_branch = worker_work._changeset_work_branch
        self.extract_changeset_root_branch = worker_work._extract_changeset_root_branch
        self.extract_workspace_parent_branch = (
            worker_work._extract_workspace_parent_branch
        )
        self.finalize_changeset = worker_work._finalize_changeset
        self.find_invalid_changeset_labels = worker_work._find_invalid_changeset_labels
        self.lookup_pr_payload = worker_work._lookup_pr_payload
        self.mark_changeset_blocked = worker_work._mark_changeset_blocked
        self.mark_changeset_in_progress = worker_work._mark_changeset_in_progress
        self.next_changeset = worker_work._next_changeset
        self.persist_review_feedback_cursor = (
            worker_work._persist_review_feedback_cursor
        )
        self.release_epic_assignment = worker_work._release_epic_assignment
        self.reconcile_blocked_merged_changesets = (
            worker_work.reconcile_blocked_merged_changesets
        )
        self.resolve_epic_id_for_changeset = worker_work._resolve_epic_id_for_changeset
        self.review_feedback_progressed = worker_work._review_feedback_progressed
        self.run_startup_contract = worker_work._run_startup_contract
        self.send_invalid_changeset_labels_notification = (
            worker_work._send_invalid_changeset_labels_notification
        )
        self.send_no_ready_changesets = worker_work._send_no_ready_changesets
        self.send_planner_notification = worker_work._send_planner_notification


class WorkerCommandAdapter:
    """Concrete command service object backed by worker helper functions."""

    def __init__(self) -> None:
        self.ensure_exec_subcommand_flag = worker_work._ensure_exec_subcommand_flag
        self.strip_flag_with_value = worker_work._strip_flag_with_value
        self.with_codex_exec = worker_work._with_codex_exec
        self.worker_opening_prompt = worker_work._worker_opening_prompt


def run_worker_sessions(
    *,
    args: object,
    mode: str,
    run_mode: str,
    dry_run: bool,
    session_key: str,
    run_worker_once: RunWorkerOnceFn,
    report_worker_summary: Callable[[WorkerRunSummary, bool], None],
    watch_interval_seconds: Callable[[], int],
    dry_run_log: Callable[[str], None],
    emit: Callable[[str], None],
    sleep_fn: Callable[[float], None] = time.sleep,
) -> None:
    if bool(getattr(args, "queue", False)):
        summary = run_worker_once(
            args, mode=mode, dry_run=dry_run, session_key=session_key
        )
        report_worker_summary(summary, dry_run)
        return

    if dry_run:
        while True:
            summary = run_worker_once(
                args, mode=mode, dry_run=True, session_key=session_key
            )
            report_worker_summary(summary, True)
            if summary.started:
                if run_mode == "once":
                    return
                continue
            if summary.reason == "no_ready_changesets":
                if run_mode == "watch":
                    interval = watch_interval_seconds()
                    dry_run_log(
                        "Watching for updates "
                        f"(sleeping {interval}s before next check)."
                    )
                    sleep_fn(interval)
                continue
            if run_mode != "watch":
                return
            interval = watch_interval_seconds()
            dry_run_log(
                f"Watching for updates (sleeping {interval}s before next check)."
            )
            sleep_fn(interval)
        return

    while True:
        summary = run_worker_once(
            args, mode=mode, dry_run=False, session_key=session_key
        )
        report_worker_summary(summary, False)
        if summary.started:
            if run_mode == "once":
                return
            continue
        if summary.reason == "no_ready_changesets":
            if run_mode == "watch":
                interval = watch_interval_seconds()
                emit(f"No ready work; watching for updates (sleeping {interval}s).")
                sleep_fn(interval)
            continue
        if run_mode == "watch":
            interval = watch_interval_seconds()
            emit(f"No ready work; watching for updates (sleeping {interval}s).")
            sleep_fn(interval)
            continue
        return


def build_worker_runtime_dependencies(
    *,
    resolve_current_project_with_repo_root: Callable[
        [], tuple[Path, ProjectConfig, str, Path]
    ],
    confirm_fn: ConfirmFn,
    die_fn: Callable[[str], None],
    emit: Callable[[str], None],
) -> WorkerRuntimeDependencies:
    """Build worker runtime service ports for runner orchestration."""
    lifecycle: WorkerLifecycleService = WorkerLifecycleAdapter()
    commands: WorkerCommandService = WorkerCommandAdapter()
    return WorkerRuntimeDependencies(
        infra=WorkerInfrastructurePorts(
            resolve_current_project_with_repo_root=resolve_current_project_with_repo_root,
            agent_home=agent_home,
            agents=agents,
            beads=beads,
            branching=branching,
            config=config,
            git=git,
            prs=prs,
            root_branch=root_branch_module,
            worker_session_agent=worker_session_agent,
            worker_session_worktree=worker_session_worktree,
        ),
        lifecycle=lifecycle,
        commands=commands,
        control=WorkerControlPorts(
            dry_run_log=worker_work._dry_run_log,
            report_timings=worker_work._report_timings,
            step=worker_work._step,
            trace_enabled=worker_work._trace_enabled,
            confirm=confirm_fn,
            die=die_fn,
            say=emit,
        ),
    )

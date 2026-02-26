"""Worker runtime loop orchestration helpers."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from .. import agent_home, agents, beads, branching, config, git, prs
from .. import root_branch as root_branch_module
from ..config import ProjectConfig
from ..models import BranchHistory, BranchPrMode, BranchSquashMessage
from ..pr_strategy import PrStrategy
from ..work_feedback import ReviewFeedbackSnapshot
from . import work_command_helpers as worker_work
from .models import (
    FinalizeResult,
    ReconcileResult,
    StartupContractResult,
    WorkerRunSummary,
)
from .ports import (
    ConfirmFn,
    Issue,
    ReportTimingsFn,
    StepFactory,
    StepFinish,
    WorkerCommandService,
    WorkerControlService,
    WorkerInfrastructurePorts,
    WorkerLifecycleService,
    WorkerRuntimeDependencies,
)
from .session import agent as worker_session_agent
from .session import worktree as worker_session_worktree
from .session.startup import StartupContractContext


class RunWorkerOnceFn(Protocol):
    def __call__(
        self, args: object, *, mode: str, dry_run: bool, session_key: str
    ) -> WorkerRunSummary: ...


NON_WATCH_EXIT_REASON_NO_WORK_EXPLICIT = "no_work_explicit_epic"
NON_WATCH_EXIT_REASON_NO_WORK_GLOBAL = "no_work_global"
NON_WATCH_EXIT_REASON_FAIL_CLOSED = "fail_closed"

_EXPLICIT_NO_WORK_REASONS = {"explicit_epic_not_actionable", "explicit_epic_completed"}
_GLOBAL_NO_WORK_REASONS = {"no_eligible_epics"}


@dataclass(frozen=True)
class NonWatchExitOutcome:
    """Classify a terminal non-watch worker outcome for stable reporting."""

    taxonomy: str
    success: bool
    summary_reason: str


def classify_non_watch_exit_outcome(
    summary: WorkerRunSummary, *, explicit_epic_requested: bool
) -> NonWatchExitOutcome:
    """Classify terminal non-watch exits into deterministic taxonomy labels."""
    reason = summary.reason
    if explicit_epic_requested and reason in _EXPLICIT_NO_WORK_REASONS:
        return NonWatchExitOutcome(
            taxonomy=NON_WATCH_EXIT_REASON_NO_WORK_EXPLICIT,
            success=True,
            summary_reason=reason,
        )
    if reason in _GLOBAL_NO_WORK_REASONS:
        return NonWatchExitOutcome(
            taxonomy=NON_WATCH_EXIT_REASON_NO_WORK_GLOBAL,
            success=True,
            summary_reason=reason,
        )
    return NonWatchExitOutcome(
        taxonomy=NON_WATCH_EXIT_REASON_FAIL_CLOSED,
        success=False,
        summary_reason=reason,
    )


def _terminal_outcome_detail(summary: WorkerRunSummary, outcome: NonWatchExitOutcome) -> str:
    parts = [
        "Terminal outcome",
        f"taxonomy={outcome.taxonomy}",
        f"summary_reason={summary.reason}",
    ]
    if summary.epic_id:
        parts.append(f"epic={summary.epic_id}")
    if summary.changeset_id:
        parts.append(f"changeset={summary.changeset_id}")
    return ": ".join((parts[0], ", ".join(parts[1:])))


class WorkerLifecycleAdapter:
    """Concrete lifecycle service object backed by worker helper functions."""

    def capture_review_feedback_snapshot(
        self,
        *,
        issue: Issue,
        repo_slug: str | None,
        repo_root: Path,
        git_path: str | None,
    ) -> ReviewFeedbackSnapshot:
        return worker_work.capture_review_feedback_snapshot(
            issue=issue,
            repo_slug=repo_slug,
            repo_root=repo_root,
            git_path=git_path,
        )

    def changeset_parent_branch(
        self,
        issue: Issue,
        *,
        root_branch: str,
        beads_root: Path | None = None,
        repo_root: Path | None = None,
    ) -> str:
        return worker_work.changeset_parent_branch(
            issue,
            root_branch=root_branch,
            beads_root=beads_root,
            repo_root=repo_root,
        )

    def changeset_pr_url(self, issue: Issue) -> str | None:
        return worker_work.changeset_pr_url(issue)

    def changeset_work_branch(self, issue: Issue) -> str | None:
        return worker_work.changeset_work_branch(issue)

    def extract_changeset_root_branch(self, issue: Issue) -> str | None:
        return worker_work.extract_changeset_root_branch(issue)

    def extract_workspace_parent_branch(self, issue: Issue) -> str | None:
        return worker_work.extract_workspace_parent_branch(issue)

    def finalize_changeset(
        self,
        *,
        changeset_id: str,
        epic_id: str,
        agent_id: str,
        agent_bead_id: str,
        started_at: datetime,
        repo_slug: str | None,
        beads_root: Path,
        repo_root: Path,
        branch_pr: bool,
        branch_pr_mode: BranchPrMode,
        branch_pr_strategy: PrStrategy,
        branch_history: BranchHistory,
        branch_squash_message: BranchSquashMessage,
        project_data_dir: Path | None,
        squash_message_agent_spec: agents.AgentSpec | None,
        squash_message_agent_options: list[str],
        squash_message_agent_home: Path,
        squash_message_agent_env: dict[str, str],
        git_path: str | None,
    ) -> FinalizeResult:
        return worker_work.finalize_changeset(
            changeset_id=changeset_id,
            epic_id=epic_id,
            agent_id=agent_id,
            agent_bead_id=agent_bead_id,
            started_at=started_at,
            repo_slug=repo_slug,
            beads_root=beads_root,
            repo_root=repo_root,
            branch_pr=branch_pr,
            branch_pr_mode=branch_pr_mode,
            branch_pr_strategy=branch_pr_strategy,
            branch_history=branch_history,
            branch_squash_message=branch_squash_message,
            project_data_dir=project_data_dir,
            squash_message_agent_spec=squash_message_agent_spec,
            squash_message_agent_options=squash_message_agent_options,
            squash_message_agent_home=squash_message_agent_home,
            squash_message_agent_env=squash_message_agent_env,
            git_path=git_path,
        )

    def find_invalid_changeset_labels(
        self, root_id: str, *, beads_root: Path, repo_root: Path
    ) -> list[str]:
        return worker_work.find_invalid_changeset_labels(
            root_id, beads_root=beads_root, repo_root=repo_root
        )

    def lookup_pr_payload(self, repo_slug: str | None, branch: str) -> Issue | None:
        return worker_work.lookup_pr_payload(repo_slug, branch)

    def mark_changeset_blocked(
        self, changeset_id: str, *, beads_root: Path, repo_root: Path, reason: str
    ) -> None:
        worker_work.mark_changeset_blocked(
            changeset_id, beads_root=beads_root, repo_root=repo_root, reason=reason
        )

    def mark_changeset_in_progress(
        self, changeset_id: str, *, beads_root: Path, repo_root: Path
    ) -> None:
        worker_work.mark_changeset_in_progress(
            changeset_id, beads_root=beads_root, repo_root=repo_root
        )

    def next_changeset(
        self,
        *,
        epic_id: str,
        beads_root: Path,
        repo_root: Path,
        repo_slug: str | None,
        branch_pr: bool,
        branch_pr_strategy: PrStrategy,
        git_path: str | None,
        resume_review: bool,
    ) -> Issue | None:
        return worker_work.next_changeset(
            epic_id=epic_id,
            beads_root=beads_root,
            repo_root=repo_root,
            repo_slug=repo_slug,
            branch_pr=branch_pr,
            branch_pr_strategy=branch_pr_strategy,
            git_path=git_path,
            resume_review=resume_review,
        )

    def persist_review_feedback_cursor(
        self,
        *,
        changeset_id: str,
        issue: Issue,
        repo_slug: str | None,
        beads_root: Path,
        repo_root: Path,
    ) -> None:
        worker_work.persist_review_feedback_cursor(
            changeset_id=changeset_id,
            issue=issue,
            repo_slug=repo_slug,
            beads_root=beads_root,
            repo_root=repo_root,
        )

    def release_epic_assignment(self, epic_id: str, *, beads_root: Path, repo_root: Path) -> None:
        worker_work.release_epic_assignment(epic_id, beads_root=beads_root, repo_root=repo_root)

    def reconcile_blocked_merged_changesets(
        self,
        *,
        agent_id: str,
        agent_bead_id: str | None,
        project_config: ProjectConfig,
        project_data_dir: Path | None,
        beads_root: Path,
        repo_root: Path,
        git_path: str | None,
        dry_run: bool,
        log: Callable[[str], None] | None,
    ) -> ReconcileResult:
        return worker_work.reconcile_blocked_merged_changesets(
            agent_id=agent_id,
            agent_bead_id=agent_bead_id,
            project_config=project_config,
            project_data_dir=project_data_dir,
            beads_root=beads_root,
            repo_root=repo_root,
            git_path=git_path,
            dry_run=dry_run,
            log=log,
        )

    def resolve_epic_id_for_changeset(
        self, issue: Issue, *, beads_root: Path, repo_root: Path
    ) -> str | None:
        return worker_work.resolve_epic_id_for_changeset(
            issue, beads_root=beads_root, repo_root=repo_root
        )

    def review_feedback_progressed(
        self, before: ReviewFeedbackSnapshot, after: ReviewFeedbackSnapshot
    ) -> bool:
        return worker_work.review_feedback_progressed(before, after)

    def run_startup_contract(self, *, context: StartupContractContext) -> StartupContractResult:
        return worker_work.run_startup_contract(context=context)

    def send_invalid_changeset_labels_notification(
        self,
        *,
        epic_id: str,
        invalid_changesets: list[str],
        agent_id: str,
        beads_root: Path,
        repo_root: Path,
        dry_run: bool,
    ) -> str:
        return worker_work.send_invalid_changeset_labels_notification(
            epic_id=epic_id,
            invalid_changesets=invalid_changesets,
            agent_id=agent_id,
            beads_root=beads_root,
            repo_root=repo_root,
            dry_run=dry_run,
        )

    def send_no_ready_changesets(
        self,
        *,
        epic_id: str,
        agent_id: str,
        beads_root: Path,
        repo_root: Path,
        dry_run: bool,
    ) -> None:
        worker_work.send_no_ready_changesets(
            epic_id=epic_id,
            agent_id=agent_id,
            beads_root=beads_root,
            repo_root=repo_root,
            dry_run=dry_run,
        )

    def send_planner_notification(
        self,
        *,
        subject: str,
        body: str,
        agent_id: str,
        thread_id: str | None,
        beads_root: Path,
        repo_root: Path,
        dry_run: bool,
    ) -> None:
        worker_work.send_planner_notification(
            subject=subject,
            body=body,
            agent_id=agent_id,
            thread_id=thread_id,
            beads_root=beads_root,
            repo_root=repo_root,
            dry_run=dry_run,
        )


class WorkerCommandAdapter:
    """Concrete command service object backed by worker helper functions."""

    def ensure_exec_subcommand_flag(self, args: list[str], flag: str) -> list[str]:
        return worker_work.ensure_exec_subcommand_flag(args, flag)

    def strip_flag_with_value(self, args: list[str], flag: str) -> list[str]:
        return worker_work.strip_flag_with_value(args, flag)

    def with_codex_exec(self, cmd: list[str], prompt: str) -> list[str]:
        return worker_work.with_codex_exec(cmd, prompt)

    def worker_opening_prompt(
        self,
        *,
        project_enlistment: Path,
        workspace_branch: str,
        epic_id: str,
        changeset_id: str,
        changeset_title: str,
        merge_conflict: bool = False,
        review_feedback: bool = False,
        review_pr_url: str | None = None,
    ) -> str:
        return worker_work.worker_opening_prompt(
            project_enlistment=str(project_enlistment),
            workspace_branch=workspace_branch,
            epic_id=epic_id,
            changeset_id=changeset_id,
            changeset_title=changeset_title,
            merge_conflict=merge_conflict,
            review_feedback=review_feedback,
            review_pr_url=review_pr_url,
        )


class WorkerControlAdapter:
    """Concrete control service backed by injected IO/tracing callables."""

    def __init__(
        self,
        *,
        dry_run_log_fn: Callable[[str], None],
        report_timings_fn: ReportTimingsFn,
        step_fn: StepFactory,
        trace_enabled_fn: Callable[[], bool],
        confirm_fn: ConfirmFn,
        die_fn: Callable[[str], None],
        say_fn: Callable[[str], None],
    ) -> None:
        self._dry_run_log_fn = dry_run_log_fn
        self._report_timings_fn = report_timings_fn
        self._step_fn = step_fn
        self._trace_enabled_fn = trace_enabled_fn
        self._confirm_fn = confirm_fn
        self._die_fn = die_fn
        self._say_fn = say_fn

    def dry_run_log(self, message: str) -> None:
        self._dry_run_log_fn(message)

    def report_timings(self, timings: list[tuple[str, float]], *, trace: bool) -> None:
        self._report_timings_fn(timings, trace=trace)

    def step(self, label: str, *, timings: list[tuple[str, float]], trace: bool) -> StepFinish:
        return self._step_fn(label, timings=timings, trace=trace)

    def trace_enabled(self) -> bool:
        return self._trace_enabled_fn()

    def confirm(self, prompt: str, *, default: bool = False) -> bool:
        return self._confirm_fn(prompt, default=default)

    def die(self, message: str) -> None:
        self._die_fn(message)

    def say(self, message: str) -> None:
        self._say_fn(message)


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
    explicit_epic_requested = bool(str(getattr(args, "epic_id", "")).strip())

    if bool(getattr(args, "queue", False)):
        summary = run_worker_once(args, mode=mode, dry_run=dry_run, session_key=session_key)
        report_worker_summary(summary, dry_run)
        return

    if dry_run:
        while True:
            summary = run_worker_once(args, mode=mode, dry_run=True, session_key=session_key)
            report_worker_summary(summary, True)
            if summary.started:
                if run_mode == "once":
                    return
                continue
            if summary.reason == "no_ready_changesets":
                if run_mode == "watch":
                    interval = watch_interval_seconds()
                    dry_run_log(f"Watching for updates (sleeping {interval}s before next check).")
                    sleep_fn(interval)
                continue
            if run_mode != "watch":
                outcome = classify_non_watch_exit_outcome(
                    summary,
                    explicit_epic_requested=explicit_epic_requested,
                )
                dry_run_log(_terminal_outcome_detail(summary, outcome))
                if not outcome.success:
                    raise SystemExit(1)
                return
            interval = watch_interval_seconds()
            dry_run_log(f"Watching for updates (sleeping {interval}s before next check).")
            sleep_fn(interval)
        return

    while True:
        summary = run_worker_once(args, mode=mode, dry_run=False, session_key=session_key)
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
        outcome = classify_non_watch_exit_outcome(
            summary,
            explicit_epic_requested=explicit_epic_requested,
        )
        emit(_terminal_outcome_detail(summary, outcome))
        if not outcome.success:
            raise SystemExit(1)
        return


def build_worker_runtime_dependencies(
    *,
    resolve_current_project_with_repo_root: Callable[[], tuple[Path, ProjectConfig, str, Path]],
    confirm_fn: ConfirmFn,
    die_fn: Callable[[str], None],
    emit: Callable[[str], None],
) -> WorkerRuntimeDependencies:
    """Build worker runtime service ports for runner orchestration."""
    lifecycle: WorkerLifecycleService = WorkerLifecycleAdapter()
    commands: WorkerCommandService = WorkerCommandAdapter()
    control: WorkerControlService = WorkerControlAdapter(
        dry_run_log_fn=worker_work.dry_run_log,
        report_timings_fn=worker_work.report_timings,
        step_fn=worker_work.step,
        trace_enabled_fn=worker_work.trace_enabled,
        confirm_fn=confirm_fn,
        die_fn=die_fn,
        say_fn=emit,
    )
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
        control=control,
    )

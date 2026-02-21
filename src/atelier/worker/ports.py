"""Typed runtime ports used by worker orchestration services."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..agent_home import AgentHome
from ..config import ProjectConfig
from ..work_feedback import ReviewFeedbackSnapshot
from .models import FinalizeResult, ReconcileResult, StartupContractResult
from .session.agent import AgentSessionPreparation, AgentSessionRunResult
from .session.worktree import WorktreePreparation

Issue = dict[str, object]
StepTimings = list[tuple[str, float]]


class StepFinish(Protocol):
    """Step completion callback emitted by tracing helpers."""

    def __call__(self, *, extra: str | None = None) -> None: ...


class StepFactory(Protocol):
    """Factory for timed step wrappers."""

    def __call__(
        self, label: str, *, timings: StepTimings, trace: bool
    ) -> StepFinish: ...


class AgentHomeService(Protocol):
    """Agent home lifecycle operations used by worker runtime."""

    def preview_agent_home(
        self,
        project_dir: Path,
        project_config: ProjectConfig,
        *,
        role: str,
        session_key: str,
    ) -> AgentHome: ...

    def resolve_agent_home(
        self,
        project_dir: Path,
        project_config: ProjectConfig,
        *,
        role: str,
        session_key: str,
    ) -> AgentHome: ...


class AgentsService(Protocol):
    """Agent environment operations used by worker runtime."""

    def scoped_agent_env(self, agent_id: str) -> AbstractContextManager[object]: ...


class BeadsService(Protocol):
    """Beads operations required by worker runtime orchestration."""

    def run_bd_command(
        self,
        args: list[str],
        *,
        beads_root: Path,
        cwd: Path,
        allow_failure: bool = False,
        daemon: bool = False,
    ) -> subprocess.CompletedProcess[str]: ...

    def run_bd_json(
        self,
        args: list[str],
        *,
        beads_root: Path,
        cwd: Path,
    ) -> list[Issue]: ...

    def ensure_agent_bead(
        self,
        agent_id: str,
        *,
        beads_root: Path,
        cwd: Path,
        role: str,
    ) -> Issue: ...

    def find_agent_bead(
        self,
        agent_id: str,
        *,
        beads_root: Path,
        cwd: Path,
    ) -> Issue | None: ...

    def claim_epic(
        self,
        epic_id: str,
        assignee: str,
        *,
        beads_root: Path,
        cwd: Path,
        allow_takeover_from: str | None = None,
    ) -> Issue: ...

    def clear_agent_hook(
        self, agent_issue_id: str, *, beads_root: Path, cwd: Path
    ) -> None: ...

    def extract_workspace_root_branch(self, issue: Issue) -> str | None: ...

    def update_workspace_root_branch(
        self, issue_id: str, root_branch: str, *, beads_root: Path, cwd: Path
    ) -> None: ...

    def update_workspace_parent_branch(
        self,
        issue_id: str,
        parent_branch: str,
        *,
        beads_root: Path,
        cwd: Path,
        allow_override: bool = False,
    ) -> None: ...

    def set_agent_hook(
        self, agent_issue_id: str, epic_issue_id: str, *, beads_root: Path, cwd: Path
    ) -> None: ...


class BranchingService(Protocol):
    """Branch naming and existence helpers."""

    def suggest_root_branch(self, title: str, prefix: str) -> str: ...

    def branch_exists(
        self, branch: str, *, repo_root: Path, git_path: str | None = None
    ) -> bool: ...


class ConfigService(Protocol):
    """Project config path resolution helpers."""

    def resolve_project_data_dir(
        self, project_root: Path, project_config: ProjectConfig
    ) -> Path: ...

    def resolve_beads_root(self, project_data_dir: Path, repo_root: Path) -> Path: ...

    def resolve_git_path(self, project_config: ProjectConfig) -> str | None: ...


class GitService(Protocol):
    """Git metadata operations needed by worker runtime."""

    def git_default_branch(
        self, repo_root: Path, *, git_path: str | None = None
    ) -> str | None: ...


class PrsService(Protocol):
    """PR metadata operations needed by worker runtime."""

    def clear_runtime_cache(self) -> None: ...

    def github_repo_slug(self, origin: str | None) -> str | None: ...


class RootBranchService(Protocol):
    """Interactive root-branch resolver."""

    def prompt_root_branch(
        self,
        *,
        title: str,
        branch_prefix: str,
        beads_root: Path,
        repo_root: Path,
        assume_yes: bool = False,
    ) -> str: ...


class WorkerSessionAgentService(Protocol):
    """Agent session preparation and execution operations."""

    def prepare_agent_session(
        self,
        *,
        project_config: ProjectConfig,
        project_data_dir: Path,
        repo_root: Path,
        beads_root: Path,
        agent: AgentHome,
        changeset_worktree_path: Path | None,
        selected_epic: str,
        changeset_id: str,
        root_branch_value: str,
        enlistment_path: Path,
        yes: bool,
        dry_run: bool,
        strip_flag_with_value: Callable[[list[str], str], list[str]],
        confirm_update: Callable[[str], bool],
        dry_run_log: Callable[[str], None],
        emit: Callable[[str], None],
    ) -> AgentSessionPreparation: ...

    def install_agent_hooks(
        self,
        *,
        dry_run: bool,
        agent: AgentHome,
        agent_spec: object,
        env: dict[str, str],
        dry_run_log: Callable[[str], None],
    ) -> None: ...

    def start_agent_session(
        self,
        *,
        dry_run: bool,
        agent: AgentHome,
        agent_spec: object,
        agent_options: list[str],
        opening_prompt: str,
        env: dict[str, str],
        with_codex_exec: Callable[[list[str], str], list[str]],
        strip_flag_with_value: Callable[[list[str], str], list[str]],
        ensure_exec_subcommand_flag: Callable[[list[str], str], list[str]],
        mark_changeset_blocked: Callable[[str], None],
        die_fn: Callable[[str], None],
        dry_run_log: Callable[[str], None],
        emit: Callable[[str], None],
    ) -> AgentSessionRunResult | None: ...


class WorkerSessionWorktreeService(Protocol):
    """Worktree preparation operations."""

    def prepare_worktrees(
        self,
        *,
        dry_run: bool,
        project_data_dir: Path,
        repo_root: Path,
        beads_root: Path,
        selected_epic: str,
        changeset_id: str,
        root_branch_value: str,
        changeset_parent_branch: str,
        git_path: str | None,
        emit: Callable[[str], None],
        dry_run_log: Callable[[str], None],
    ) -> WorktreePreparation: ...


class CaptureReviewFeedbackSnapshotFn(Protocol):
    def __call__(
        self,
        *,
        issue: Issue,
        repo_slug: str | None,
        repo_root: Path,
        git_path: str | None,
    ) -> ReviewFeedbackSnapshot: ...


class ChangesetParentBranchFn(Protocol):
    def __call__(self, issue: Issue, *, root_branch: str) -> str: ...


class FinalizeChangesetFn(Protocol):
    def __call__(
        self,
        *,
        changeset_id: str,
        epic_id: str,
        agent_id: str,
        agent_bead_id: str,
        started_at: object,
        repo_slug: str | None,
        beads_root: Path,
        repo_root: Path,
        branch_pr: bool,
        branch_pr_strategy: object,
        branch_history: str,
        branch_squash_message: str,
        project_data_dir: Path | None,
        squash_message_agent_spec: object,
        squash_message_agent_options: list[str],
        squash_message_agent_home: Path,
        squash_message_agent_env: dict[str, str],
        git_path: str | None,
    ) -> FinalizeResult: ...


class FindInvalidChangesetLabelsFn(Protocol):
    def __call__(
        self, root_id: str, *, beads_root: Path, repo_root: Path
    ) -> list[str]: ...


class MarkChangesetBlockedFn(Protocol):
    def __call__(
        self, changeset_id: str, *, beads_root: Path, repo_root: Path, reason: str
    ) -> None: ...


class MarkChangesetInProgressFn(Protocol):
    def __call__(
        self, changeset_id: str, *, beads_root: Path, repo_root: Path
    ) -> None: ...


class NextChangesetFn(Protocol):
    def __call__(
        self,
        *,
        epic_id: str,
        beads_root: Path,
        repo_root: Path,
        repo_slug: str | None,
        branch_pr: bool,
        branch_pr_strategy: object,
        git_path: str | None,
    ) -> Issue | None: ...


class PersistReviewFeedbackCursorFn(Protocol):
    def __call__(
        self,
        *,
        changeset_id: str,
        issue: Issue,
        repo_slug: str | None,
        beads_root: Path,
        repo_root: Path,
    ) -> None: ...


class ReleaseEpicAssignmentFn(Protocol):
    def __call__(self, epic_id: str, *, beads_root: Path, repo_root: Path) -> None: ...


class ReconcileBlockedMergedChangesetsFn(Protocol):
    def __call__(
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
    ) -> ReconcileResult: ...


class ResolveEpicIdForChangesetFn(Protocol):
    def __call__(
        self, issue: Issue, *, beads_root: Path, repo_root: Path
    ) -> str | None: ...


class RunStartupContractFn(Protocol):
    def __call__(
        self,
        *,
        agent_id: str,
        agent_bead_id: str | None,
        beads_root: Path,
        repo_root: Path,
        mode: str,
        explicit_epic_id: str | None,
        queue_only: bool,
        dry_run: bool,
        assume_yes: bool,
        repo_slug: str | None,
        branch_pr: bool,
        branch_pr_strategy: object,
        git_path: str | None,
    ) -> StartupContractResult: ...


class SendInvalidChangesetLabelsNotificationFn(Protocol):
    def __call__(
        self,
        *,
        epic_id: str,
        invalid_changesets: list[str],
        agent_id: str,
        beads_root: Path,
        repo_root: Path,
        dry_run: bool,
    ) -> str: ...


class SendNoReadyChangesetsFn(Protocol):
    def __call__(
        self,
        *,
        epic_id: str,
        agent_id: str,
        beads_root: Path,
        repo_root: Path,
        dry_run: bool,
    ) -> None: ...


class SendPlannerNotificationFn(Protocol):
    def __call__(
        self,
        *,
        subject: str,
        body: str,
        agent_id: str,
        thread_id: str | None,
        beads_root: Path,
        repo_root: Path,
        dry_run: bool,
    ) -> None: ...


class WorkerOpeningPromptFn(Protocol):
    def __call__(
        self,
        *,
        project_enlistment: Path,
        workspace_branch: str,
        epic_id: str,
        changeset_id: str,
        changeset_title: str,
        review_feedback: bool = False,
        review_pr_url: str | None = None,
    ) -> str: ...


class ReportTimingsFn(Protocol):
    def __call__(self, timings: StepTimings, *, trace: bool) -> None: ...


class ConfirmFn(Protocol):
    def __call__(self, prompt: str, *, default: bool = False) -> bool: ...


class RunBdJsonFn(Protocol):
    def __call__(
        self,
        args: list[str],
        *,
        beads_root: Path,
        cwd: Path,
    ) -> list[Issue]: ...


@dataclass(frozen=True)
class WorkerInfrastructurePorts:
    """External module integrations required by worker runtime."""

    resolve_current_project_with_repo_root: Callable[
        [], tuple[Path, ProjectConfig, str, Path]
    ]
    agent_home: AgentHomeService
    agents: AgentsService
    beads: BeadsService
    branching: BranchingService
    config: ConfigService
    git: GitService
    prs: PrsService
    root_branch: RootBranchService
    worker_session_agent: WorkerSessionAgentService
    worker_session_worktree: WorkerSessionWorktreeService


class WorkerLifecycleService(Protocol):
    """Worker lifecycle service contract used by runner orchestration."""

    capture_review_feedback_snapshot: CaptureReviewFeedbackSnapshotFn
    changeset_parent_branch: ChangesetParentBranchFn
    changeset_pr_url: Callable[[Issue], str | None]
    changeset_work_branch: Callable[[Issue], str | None]
    extract_changeset_root_branch: Callable[[Issue], str | None]
    extract_workspace_parent_branch: Callable[[Issue], str | None]
    finalize_changeset: FinalizeChangesetFn
    find_invalid_changeset_labels: FindInvalidChangesetLabelsFn
    lookup_pr_payload: Callable[[str | None, str], Issue | None]
    mark_changeset_blocked: MarkChangesetBlockedFn
    mark_changeset_in_progress: MarkChangesetInProgressFn
    next_changeset: NextChangesetFn
    persist_review_feedback_cursor: PersistReviewFeedbackCursorFn
    release_epic_assignment: ReleaseEpicAssignmentFn
    reconcile_blocked_merged_changesets: ReconcileBlockedMergedChangesetsFn
    resolve_epic_id_for_changeset: ResolveEpicIdForChangesetFn
    review_feedback_progressed: Callable[
        [ReviewFeedbackSnapshot, ReviewFeedbackSnapshot], bool
    ]
    run_startup_contract: RunStartupContractFn
    send_invalid_changeset_labels_notification: SendInvalidChangesetLabelsNotificationFn
    send_no_ready_changesets: SendNoReadyChangesetsFn
    send_planner_notification: SendPlannerNotificationFn


class WorkerCommandService(Protocol):
    """Agent command-line argument transformation contract."""

    ensure_exec_subcommand_flag: Callable[[list[str], str], list[str]]
    strip_flag_with_value: Callable[[list[str], str], list[str]]
    with_codex_exec: Callable[[list[str], str], list[str]]
    worker_opening_prompt: WorkerOpeningPromptFn


@dataclass(frozen=True)
class WorkerControlPorts:
    """Logging, prompting, and tracing controls."""

    dry_run_log: Callable[[str], None]
    report_timings: ReportTimingsFn
    step: StepFactory
    trace_enabled: Callable[[], bool]
    confirm: ConfirmFn
    die: Callable[[str], None]
    say: Callable[[str], None]


@dataclass(frozen=True)
class WorkerRuntimeDependencies:
    """Compact runtime dependency graph for worker session runner."""

    infra: WorkerInfrastructurePorts
    lifecycle: WorkerLifecycleService
    commands: WorkerCommandService
    control: WorkerControlPorts


@dataclass(frozen=True)
class ChangesetSelectionPorts:
    """Dependency ports used by changeset selection."""

    run_bd_json: RunBdJsonFn
    resolve_epic_id_for_changeset: ResolveEpicIdForChangesetFn
    next_changeset: NextChangesetFn

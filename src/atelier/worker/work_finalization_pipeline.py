"""Finalize pipeline runtime binding helpers."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from .. import agents, pr_strategy
from ..models import BranchPrMode
from ..worker import finalize_pipeline as worker_finalize_pipeline
from ..worker.models import FinalizeResult, PublishSignalDiagnostics
from .work_finalization_integration import (
    attempt_push_work_branch,
    collect_publish_signal_diagnostics,
    finalize_epic_if_complete,
    finalize_terminal_changeset,
    format_publish_diagnostics,
)
from .work_finalization_state import (
    align_existing_pr_base,
    changeset_integration_signal,
    changeset_stack_integrity_preflight,
    changeset_waiting_on_review_or_signals,
    handle_pushed_without_pr,
    has_blocking_messages,
    has_open_descendant_changesets,
    issue_labels,
    lookup_pr_payload,
    lookup_pr_payload_diagnostic,
    mark_changeset_blocked,
    mark_changeset_children_in_progress,
    mark_changeset_closed,
    mark_changeset_in_progress,
    recover_premature_merged_changeset,
    send_planner_notification,
    set_changeset_review_pending_state,
    update_changeset_review_from_pr,
)


class _FinalizePipelineService(worker_finalize_pipeline.FinalizePipelineService):
    """Finalize pipeline dependencies bound to worker repository context."""

    def __init__(self, *, beads_root: Path, repo_root: Path, git_path: str | None) -> None:
        self._beads_root = beads_root
        self._repo_root = repo_root
        self._git_path = git_path

    def issue_labels(self, issue: dict[str, object]) -> set[str]:
        return issue_labels(issue)

    def has_open_descendant_changesets(self, changeset_id: str) -> bool:
        return has_open_descendant_changesets(
            changeset_id, beads_root=self._beads_root, repo_root=self._repo_root
        )

    def has_blocking_messages(self, *, thread_ids: set[str], started_at: dt.datetime) -> bool:
        return has_blocking_messages(
            thread_ids=thread_ids,
            started_at=started_at,
            beads_root=self._beads_root,
            repo_root=self._repo_root,
        )

    def mark_changeset_children_in_progress(self, changeset_id: str) -> None:
        mark_changeset_children_in_progress(
            changeset_id, beads_root=self._beads_root, repo_root=self._repo_root
        )

    def changeset_integration_signal(
        self,
        issue: dict[str, object],
        *,
        repo_slug: str | None,
        git_path: str | None,
        require_target_branch_proof: bool = False,
    ) -> tuple[bool, str | None]:
        return changeset_integration_signal(
            issue,
            repo_slug=repo_slug,
            repo_root=self._repo_root,
            git_path=git_path,
            require_target_branch_proof=require_target_branch_proof,
        )

    def recover_premature_merged_changeset(
        self,
        *,
        issue: dict[str, object],
        context: worker_finalize_pipeline.FinalizePipelineContext,
    ) -> FinalizeResult | None:
        return recover_premature_merged_changeset(
            issue=issue,
            changeset_id=context.changeset_id,
            epic_id=context.epic_id,
            agent_id=context.agent_id,
            agent_bead_id=context.agent_bead_id,
            branch_pr=context.branch_pr,
            branch_pr_mode=context.branch_pr_mode,
            branch_history=context.branch_history,
            branch_squash_message=context.branch_squash_message,
            branch_pr_strategy=context.branch_pr_strategy,
            repo_slug=context.repo_slug,
            beads_root=self._beads_root,
            repo_root=self._repo_root,
            project_data_dir=context.project_data_dir or self._repo_root,
            squash_message_agent_spec=context.squash_message_agent_spec,
            squash_message_agent_options=context.squash_message_agent_options or [],
            squash_message_agent_home=context.squash_message_agent_home,
            squash_message_agent_env=context.squash_message_agent_env,
            git_path=context.git_path,
        )

    def mark_changeset_blocked(self, changeset_id: str, *, reason: str) -> None:
        mark_changeset_blocked(
            changeset_id,
            beads_root=self._beads_root,
            repo_root=self._repo_root,
            reason=reason,
        )

    def send_planner_notification(
        self, *, subject: str, body: str, agent_id: str, thread_id: str | None
    ) -> None:
        send_planner_notification(
            subject=subject,
            body=body,
            agent_id=agent_id,
            thread_id=thread_id,
            beads_root=self._beads_root,
            repo_root=self._repo_root,
            dry_run=False,
        )

    def mark_changeset_closed(self, changeset_id: str) -> None:
        mark_changeset_closed(changeset_id, beads_root=self._beads_root, repo_root=self._repo_root)

    def finalize_epic_if_complete(
        self, *, context: worker_finalize_pipeline.FinalizePipelineContext
    ) -> FinalizeResult:
        return finalize_epic_if_complete(
            epic_id=context.epic_id,
            agent_id=context.agent_id,
            agent_bead_id=context.agent_bead_id,
            branch_pr=context.branch_pr,
            branch_history=context.branch_history,
            branch_squash_message=context.branch_squash_message,
            beads_root=self._beads_root,
            repo_root=self._repo_root,
            project_data_dir=context.project_data_dir,
            squash_message_agent_spec=context.squash_message_agent_spec,
            squash_message_agent_options=context.squash_message_agent_options,
            squash_message_agent_home=context.squash_message_agent_home,
            squash_message_agent_env=context.squash_message_agent_env,
            git_path=context.git_path,
        )

    def mark_changeset_in_progress(self, changeset_id: str) -> None:
        mark_changeset_in_progress(
            changeset_id, beads_root=self._beads_root, repo_root=self._repo_root
        )

    def stack_integrity_preflight(
        self,
        issue: dict[str, object],
        *,
        context: worker_finalize_pipeline.FinalizePipelineContext,
    ) -> worker_finalize_pipeline.StackIntegrityCheck:
        preflight = changeset_stack_integrity_preflight(
            issue,
            repo_slug=context.repo_slug,
            repo_root=self._repo_root,
            git_path=context.git_path,
            branch_pr_strategy=context.branch_pr_strategy,
            beads_root=self._beads_root,
        )
        return worker_finalize_pipeline.StackIntegrityCheck(
            ok=preflight.ok,
            reason=preflight.reason,
            edge=preflight.edge,
            detail=preflight.detail,
            remediation=preflight.remediation,
        )

    def changeset_waiting_on_review_or_signals(
        self,
        issue: dict[str, object],
        *,
        context: worker_finalize_pipeline.FinalizePipelineContext,
    ) -> bool:
        return changeset_waiting_on_review_or_signals(
            issue,
            repo_slug=context.repo_slug,
            repo_root=self._repo_root,
            branch_pr=context.branch_pr,
            branch_pr_strategy=context.branch_pr_strategy,
            git_path=context.git_path,
        )

    def lookup_pr_payload(self, repo_slug: str | None, branch: str) -> dict[str, object] | None:
        return lookup_pr_payload(repo_slug, branch)

    def lookup_pr_payload_diagnostic(
        self, repo_slug: str | None, branch: str
    ) -> tuple[dict[str, object] | None, str | None]:
        return lookup_pr_payload_diagnostic(repo_slug, branch)

    def align_existing_pr_base(
        self,
        *,
        issue: dict[str, object],
        pr_payload: dict[str, object],
        context: worker_finalize_pipeline.FinalizePipelineContext,
    ) -> tuple[bool, str | None]:
        if not context.repo_slug:
            return False, "missing repo slug for PR base alignment"
        return align_existing_pr_base(
            issue=issue,
            changeset_id=context.changeset_id,
            pr_payload=pr_payload,
            repo_slug=context.repo_slug,
            beads_root=self._beads_root,
            repo_root=self._repo_root,
            git_path=context.git_path,
            branch_pr_strategy=context.branch_pr_strategy,
        )

    def update_changeset_review_from_pr(
        self,
        changeset_id: str,
        *,
        pr_payload: dict[str, object] | None,
        pushed: bool,
    ) -> None:
        update_changeset_review_from_pr(
            changeset_id,
            pr_payload=pr_payload,
            pushed=pushed,
            beads_root=self._beads_root,
            repo_root=self._repo_root,
        )

    def finalize_terminal_changeset(
        self,
        *,
        context: worker_finalize_pipeline.FinalizePipelineContext,
        terminal_state: str,
        integrated_sha: str | None,
    ) -> FinalizeResult:
        return finalize_terminal_changeset(
            changeset_id=context.changeset_id,
            epic_id=context.epic_id,
            agent_id=context.agent_id,
            agent_bead_id=context.agent_bead_id,
            terminal_state=terminal_state,
            integrated_sha=integrated_sha,
            branch_pr=context.branch_pr,
            branch_history=context.branch_history,
            branch_squash_message=context.branch_squash_message,
            beads_root=self._beads_root,
            repo_root=self._repo_root,
            project_data_dir=context.project_data_dir,
            squash_message_agent_spec=context.squash_message_agent_spec,
            squash_message_agent_options=context.squash_message_agent_options,
            squash_message_agent_home=context.squash_message_agent_home,
            squash_message_agent_env=context.squash_message_agent_env,
            git_path=context.git_path,
        )

    def handle_pushed_without_pr(
        self,
        *,
        issue: dict[str, object],
        context: worker_finalize_pipeline.FinalizePipelineContext,
        create_as_draft: bool,
        create_detail_prefix: str | None = None,
    ) -> FinalizeResult:
        return handle_pushed_without_pr(
            issue=issue,
            changeset_id=context.changeset_id,
            agent_id=context.agent_id,
            repo_slug=context.repo_slug,
            repo_root=self._repo_root,
            beads_root=self._beads_root,
            branch_pr_strategy=context.branch_pr_strategy,
            git_path=context.git_path,
            create_as_draft=create_as_draft,
            create_detail_prefix=create_detail_prefix,
        )

    def attempt_push_work_branch(self, work_branch: str) -> tuple[bool, str | None]:
        return attempt_push_work_branch(
            work_branch, repo_root=self._repo_root, git_path=self._git_path
        )

    def collect_publish_signal_diagnostics(
        self,
        *,
        work_branch: str,
        context: worker_finalize_pipeline.FinalizePipelineContext,
    ) -> PublishSignalDiagnostics:
        return collect_publish_signal_diagnostics(
            work_branch=work_branch,
            epic_id=context.epic_id,
            changeset_id=context.changeset_id,
            project_data_dir=context.project_data_dir,
            repo_root=self._repo_root,
            git_path=context.git_path,
        )

    def format_publish_diagnostics(
        self, diagnostics: PublishSignalDiagnostics, *, push_detail: str | None = None
    ) -> str:
        return format_publish_diagnostics(diagnostics, push_detail=push_detail)

    def set_changeset_review_pending_state(
        self,
        *,
        changeset_id: str,
        pr_payload: dict[str, object] | None,
        pushed: bool,
        fallback_pr_state: str | None,
    ) -> None:
        set_changeset_review_pending_state(
            changeset_id=changeset_id,
            pr_payload=pr_payload,
            pushed=pushed,
            fallback_pr_state=fallback_pr_state,
            beads_root=self._beads_root,
            repo_root=self._repo_root,
        )


def finalize_changeset(
    *,
    changeset_id: str,
    epic_id: str,
    agent_id: str,
    agent_bead_id: str,
    started_at: dt.datetime,
    repo_slug: str | None,
    beads_root: Path,
    repo_root: Path,
    branch_pr: bool = True,
    branch_pr_mode: BranchPrMode = "draft",
    branch_pr_strategy: pr_strategy.PrStrategy = pr_strategy.PR_STRATEGY_DEFAULT,
    branch_history: str = "manual",
    branch_squash_message: str = "deterministic",
    project_data_dir: Path | None = None,
    squash_message_agent_spec: agents.AgentSpec | None = None,
    squash_message_agent_options: list[str] | None = None,
    squash_message_agent_home: Path | None = None,
    squash_message_agent_env: dict[str, str] | None = None,
    git_path: str | None = None,
) -> FinalizeResult:
    """Finalize changeset.

    Args:
        changeset_id: Value for `changeset_id`.
        epic_id: Value for `epic_id`.
        agent_id: Value for `agent_id`.
        agent_bead_id: Value for `agent_bead_id`.
        started_at: Value for `started_at`.
        repo_slug: Value for `repo_slug`.
        beads_root: Value for `beads_root`.
        repo_root: Value for `repo_root`.
        branch_pr: Value for `branch_pr`.
        branch_pr_mode: Value for `branch_pr_mode`.
        branch_pr_strategy: Value for `branch_pr_strategy`.
        branch_history: Value for `branch_history`.
        branch_squash_message: Value for `branch_squash_message`.
        project_data_dir: Value for `project_data_dir`.
        squash_message_agent_spec: Value for `squash_message_agent_spec`.
        squash_message_agent_options: Value for `squash_message_agent_options`.
        squash_message_agent_home: Value for `squash_message_agent_home`.
        squash_message_agent_env: Value for `squash_message_agent_env`.
        git_path: Value for `git_path`.

    Returns:
        Function result.
    """
    context = worker_finalize_pipeline.FinalizePipelineContext(
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
    service = _FinalizePipelineService(
        beads_root=beads_root, repo_root=repo_root, git_path=git_path
    )
    return worker_finalize_pipeline.run_finalize_pipeline(
        context=context,
        service=service,
    )


__all__ = ["finalize_changeset"]

"""Finalize pipeline runtime binding helpers."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from .. import agents, pr_strategy
from ..worker import finalize_pipeline as worker_finalize_pipeline
from ..worker.models import FinalizeResult, PublishSignalDiagnostics
from .work_finalization_integration import (
    _attempt_push_work_branch,
    _collect_publish_signal_diagnostics,
    _finalize_epic_if_complete,
    _finalize_terminal_changeset,
    _format_publish_diagnostics,
)
from .work_finalization_state import (
    _changeset_integration_signal,
    _changeset_waiting_on_review_or_signals,
    _close_completed_container_changesets,
    _find_invalid_changeset_labels,
    _handle_pushed_without_pr,
    _has_blocking_messages,
    _has_open_descendant_changesets,
    _issue_labels,
    _lookup_pr_payload,
    _lookup_pr_payload_diagnostic,
    _mark_changeset_blocked,
    _mark_changeset_children_in_progress,
    _mark_changeset_closed,
    _mark_changeset_in_progress,
    _promote_planned_descendant_changesets,
    _recover_premature_merged_changeset,
    _send_invalid_changeset_labels_notification,
    _send_planner_notification,
    _set_changeset_review_pending_state,
    _update_changeset_review_from_pr,
)


class _FinalizePipelineService(worker_finalize_pipeline.FinalizePipelineService):
    """Concrete finalize pipeline dependencies bound to a worker repository context."""

    def __init__(
        self, *, beads_root: Path, repo_root: Path, git_path: str | None
    ) -> None:
        self._beads_root = beads_root
        self._repo_root = repo_root
        self._git_path = git_path

    def issue_labels(self, issue: dict[str, object]) -> set[str]:
        return _issue_labels(issue)

    def find_invalid_changeset_labels(self, epic_id: str) -> list[str]:
        return _find_invalid_changeset_labels(
            epic_id, beads_root=self._beads_root, repo_root=self._repo_root
        )

    def send_invalid_changeset_labels_notification(
        self, *, epic_id: str, invalid_changesets: list[str], agent_id: str
    ) -> str:
        return _send_invalid_changeset_labels_notification(
            epic_id=epic_id,
            invalid_changesets=invalid_changesets,
            agent_id=agent_id,
            beads_root=self._beads_root,
            repo_root=self._repo_root,
            dry_run=False,
        )

    def has_open_descendant_changesets(self, changeset_id: str) -> bool:
        return _has_open_descendant_changesets(
            changeset_id, beads_root=self._beads_root, repo_root=self._repo_root
        )

    def has_blocking_messages(
        self, *, thread_ids: set[str], started_at: dt.datetime
    ) -> bool:
        return _has_blocking_messages(
            thread_ids=thread_ids,
            started_at=started_at,
            beads_root=self._beads_root,
            repo_root=self._repo_root,
        )

    def mark_changeset_children_in_progress(self, changeset_id: str) -> None:
        _mark_changeset_children_in_progress(
            changeset_id, beads_root=self._beads_root, repo_root=self._repo_root
        )

    def close_completed_container_changesets(self, epic_id: str) -> list[str]:
        return _close_completed_container_changesets(
            epic_id, beads_root=self._beads_root, repo_root=self._repo_root
        )

    def promote_planned_descendant_changesets(self, changeset_id: str) -> None:
        _promote_planned_descendant_changesets(
            changeset_id, beads_root=self._beads_root, repo_root=self._repo_root
        )

    def changeset_integration_signal(
        self,
        issue: dict[str, object],
        *,
        repo_slug: str | None,
        git_path: str | None,
    ) -> tuple[bool, str | None]:
        return _changeset_integration_signal(
            issue,
            repo_slug=repo_slug,
            repo_root=self._repo_root,
            git_path=git_path,
        )

    def recover_premature_merged_changeset(
        self,
        *,
        issue: dict[str, object],
        context: worker_finalize_pipeline.FinalizePipelineContext,
    ) -> FinalizeResult | None:
        return _recover_premature_merged_changeset(
            issue=issue,
            changeset_id=context.changeset_id,
            epic_id=context.epic_id,
            agent_id=context.agent_id,
            agent_bead_id=context.agent_bead_id,
            branch_pr=context.branch_pr,
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
        _mark_changeset_blocked(
            changeset_id,
            beads_root=self._beads_root,
            repo_root=self._repo_root,
            reason=reason,
        )

    def send_planner_notification(
        self, *, subject: str, body: str, agent_id: str, thread_id: str | None
    ) -> None:
        _send_planner_notification(
            subject=subject,
            body=body,
            agent_id=agent_id,
            thread_id=thread_id,
            beads_root=self._beads_root,
            repo_root=self._repo_root,
            dry_run=False,
        )

    def mark_changeset_closed(self, changeset_id: str) -> None:
        _mark_changeset_closed(
            changeset_id, beads_root=self._beads_root, repo_root=self._repo_root
        )

    def finalize_epic_if_complete(
        self, *, context: worker_finalize_pipeline.FinalizePipelineContext
    ) -> FinalizeResult:
        return _finalize_epic_if_complete(
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
        _mark_changeset_in_progress(
            changeset_id, beads_root=self._beads_root, repo_root=self._repo_root
        )

    def changeset_waiting_on_review_or_signals(
        self,
        issue: dict[str, object],
        *,
        context: worker_finalize_pipeline.FinalizePipelineContext,
    ) -> bool:
        return _changeset_waiting_on_review_or_signals(
            issue,
            repo_slug=context.repo_slug,
            repo_root=self._repo_root,
            branch_pr=context.branch_pr,
            branch_pr_strategy=context.branch_pr_strategy,
            git_path=context.git_path,
        )

    def lookup_pr_payload(
        self, repo_slug: str | None, branch: str
    ) -> dict[str, object] | None:
        return _lookup_pr_payload(repo_slug, branch)

    def lookup_pr_payload_diagnostic(
        self, repo_slug: str | None, branch: str
    ) -> tuple[dict[str, object] | None, str | None]:
        return _lookup_pr_payload_diagnostic(repo_slug, branch)

    def update_changeset_review_from_pr(
        self,
        changeset_id: str,
        *,
        pr_payload: dict[str, object] | None,
        pushed: bool,
    ) -> None:
        _update_changeset_review_from_pr(
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
        return _finalize_terminal_changeset(
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
        create_detail_prefix: str | None = None,
    ) -> FinalizeResult:
        return _handle_pushed_without_pr(
            issue=issue,
            changeset_id=context.changeset_id,
            agent_id=context.agent_id,
            repo_slug=context.repo_slug,
            repo_root=self._repo_root,
            beads_root=self._beads_root,
            branch_pr_strategy=context.branch_pr_strategy,
            git_path=context.git_path,
            create_detail_prefix=create_detail_prefix,
        )

    def attempt_push_work_branch(self, work_branch: str) -> tuple[bool, str | None]:
        return _attempt_push_work_branch(
            work_branch, repo_root=self._repo_root, git_path=self._git_path
        )

    def collect_publish_signal_diagnostics(
        self,
        *,
        work_branch: str,
        context: worker_finalize_pipeline.FinalizePipelineContext,
    ) -> PublishSignalDiagnostics:
        return _collect_publish_signal_diagnostics(
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
        return _format_publish_diagnostics(diagnostics, push_detail=push_detail)

    def set_changeset_review_pending_state(
        self,
        *,
        changeset_id: str,
        pr_payload: dict[str, object] | None,
        pushed: bool,
        fallback_pr_state: str | None,
    ) -> None:
        _set_changeset_review_pending_state(
            changeset_id=changeset_id,
            pr_payload=pr_payload,
            pushed=pushed,
            fallback_pr_state=fallback_pr_state,
            beads_root=self._beads_root,
            repo_root=self._repo_root,
        )


def _finalize_changeset(
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
    branch_pr_strategy: object = pr_strategy.PR_STRATEGY_DEFAULT,
    branch_history: str = "manual",
    branch_squash_message: str = "deterministic",
    project_data_dir: Path | None = None,
    squash_message_agent_spec: agents.AgentSpec | None = None,
    squash_message_agent_options: list[str] | None = None,
    squash_message_agent_home: Path | None = None,
    squash_message_agent_env: dict[str, str] | None = None,
    git_path: str | None = None,
) -> FinalizeResult:
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


__all__ = [name for name in globals() if name.startswith("_")]

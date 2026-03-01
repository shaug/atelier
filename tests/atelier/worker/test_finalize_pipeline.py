from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

from atelier.worker import finalize_pipeline
from atelier.worker.models import FinalizeResult, PublishSignalDiagnostics


class _FinalizeServiceStub(finalize_pipeline.FinalizePipelineService):
    def __init__(self) -> None:
        self.issue_labels_fn = lambda issue: set(issue.get("labels") or [])
        self.has_open_descendant_changesets_fn = lambda _changeset_id: False
        self.has_blocking_messages_fn = lambda *, thread_ids, started_at: False
        self.mark_changeset_children_in_progress_fn = lambda _changeset_id: None
        self.close_completed_container_changesets_fn = lambda _epic_id: []
        self.promote_planned_descendant_changesets_fn = lambda _changeset_id: None
        self.changeset_integration_signal_fn = lambda issue, *, repo_slug, git_path: (
            False,
            None,
        )
        self.recover_premature_merged_changeset_fn = lambda *, issue, context: None
        self.mark_changeset_blocked_fn = lambda _changeset_id, *, reason: None
        self.send_planner_notification_fn = lambda *, subject, body, agent_id, thread_id: None
        self.mark_changeset_closed_fn = lambda _changeset_id: None
        self.finalize_epic_if_complete_fn = lambda *, context: FinalizeResult(
            continue_running=True, reason="changeset_complete"
        )
        self.mark_changeset_in_progress_fn = lambda _changeset_id: None
        self.stack_integrity_preflight_fn = lambda issue, *, context: (
            finalize_pipeline.StackIntegrityCheck(ok=True)
        )
        self.changeset_waiting_on_review_or_signals_fn = lambda issue, *, context: False
        self.lookup_pr_payload_fn = lambda repo_slug, branch: None
        self.lookup_pr_payload_diagnostic_fn = lambda repo_slug, branch: (None, None)
        self.align_existing_pr_base_fn = lambda *, issue, pr_payload, context: (True, None)
        self.update_changeset_review_from_pr_fn = lambda changeset_id, *, pr_payload, pushed: None
        self.finalize_terminal_changeset_fn = lambda *, context, terminal_state, integrated_sha: (
            FinalizeResult(
                continue_running=True,
                reason="changeset_terminal",
            )
        )
        self.handle_pushed_without_pr_fn = (
            lambda *, issue, context, create_as_draft, create_detail_prefix=None: FinalizeResult(
                continue_running=True,
                reason="changeset_review_pending",
            )
        )
        self.attempt_push_work_branch_fn = lambda work_branch: (False, None)
        self.collect_publish_signal_diagnostics_fn = lambda *, work_branch, context: (
            PublishSignalDiagnostics(
                local_branch_exists=False,
                remote_branch_exists=False,
                worktree_path=None,
                dirty_entries=(),
            )
        )
        self.format_publish_diagnostics_fn = lambda diagnostics, *, push_detail=None: "diag"
        self.set_changeset_review_pending_state_fn = (
            lambda *, changeset_id, pr_payload, pushed, fallback_pr_state: None
        )

    def issue_labels(self, issue: dict[str, object]) -> set[str]:
        return self.issue_labels_fn(issue)

    def has_open_descendant_changesets(self, changeset_id: str) -> bool:
        return self.has_open_descendant_changesets_fn(changeset_id)

    def has_blocking_messages(self, *, thread_ids: set[str], started_at: dt.datetime) -> bool:
        return self.has_blocking_messages_fn(thread_ids=thread_ids, started_at=started_at)

    def mark_changeset_children_in_progress(self, changeset_id: str) -> None:
        self.mark_changeset_children_in_progress_fn(changeset_id)

    def close_completed_container_changesets(self, epic_id: str) -> list[str]:
        return self.close_completed_container_changesets_fn(epic_id)

    def promote_planned_descendant_changesets(self, changeset_id: str) -> None:
        self.promote_planned_descendant_changesets_fn(changeset_id)

    def changeset_integration_signal(
        self,
        issue: dict[str, object],
        *,
        repo_slug: str | None,
        git_path: str | None,
        require_target_branch_proof: bool = False,
    ) -> tuple[bool, str | None]:
        del require_target_branch_proof
        return self.changeset_integration_signal_fn(issue, repo_slug=repo_slug, git_path=git_path)

    def recover_premature_merged_changeset(
        self,
        *,
        issue: dict[str, object],
        context: finalize_pipeline.FinalizePipelineContext,
    ) -> FinalizeResult | None:
        return self.recover_premature_merged_changeset_fn(issue=issue, context=context)

    def mark_changeset_blocked(self, changeset_id: str, *, reason: str) -> None:
        self.mark_changeset_blocked_fn(changeset_id, reason=reason)

    def send_planner_notification(
        self, *, subject: str, body: str, agent_id: str, thread_id: str | None
    ) -> None:
        self.send_planner_notification_fn(
            subject=subject,
            body=body,
            agent_id=agent_id,
            thread_id=thread_id,
        )

    def mark_changeset_closed(self, changeset_id: str) -> None:
        self.mark_changeset_closed_fn(changeset_id)

    def finalize_epic_if_complete(
        self, *, context: finalize_pipeline.FinalizePipelineContext
    ) -> FinalizeResult:
        return self.finalize_epic_if_complete_fn(context=context)

    def mark_changeset_in_progress(self, changeset_id: str) -> None:
        self.mark_changeset_in_progress_fn(changeset_id)

    def stack_integrity_preflight(
        self,
        issue: dict[str, object],
        *,
        context: finalize_pipeline.FinalizePipelineContext,
    ) -> finalize_pipeline.StackIntegrityCheck:
        return self.stack_integrity_preflight_fn(issue, context=context)

    def changeset_waiting_on_review_or_signals(
        self,
        issue: dict[str, object],
        *,
        context: finalize_pipeline.FinalizePipelineContext,
    ) -> bool:
        return self.changeset_waiting_on_review_or_signals_fn(issue, context=context)

    def lookup_pr_payload(self, repo_slug: str | None, branch: str) -> dict[str, object] | None:
        return self.lookup_pr_payload_fn(repo_slug, branch)

    def lookup_pr_payload_diagnostic(
        self, repo_slug: str | None, branch: str
    ) -> tuple[dict[str, object] | None, str | None]:
        return self.lookup_pr_payload_diagnostic_fn(repo_slug, branch)

    def update_changeset_review_from_pr(
        self,
        changeset_id: str,
        *,
        pr_payload: dict[str, object] | None,
        pushed: bool,
    ) -> None:
        self.update_changeset_review_from_pr_fn(
            changeset_id,
            pr_payload=pr_payload,
            pushed=pushed,
        )

    def align_existing_pr_base(
        self,
        *,
        issue: dict[str, object],
        pr_payload: dict[str, object],
        context: finalize_pipeline.FinalizePipelineContext,
    ) -> tuple[bool, str | None]:
        return self.align_existing_pr_base_fn(
            issue=issue,
            pr_payload=pr_payload,
            context=context,
        )

    def finalize_terminal_changeset(
        self,
        *,
        context: finalize_pipeline.FinalizePipelineContext,
        terminal_state: str,
        integrated_sha: str | None,
    ) -> FinalizeResult:
        return self.finalize_terminal_changeset_fn(
            context=context,
            terminal_state=terminal_state,
            integrated_sha=integrated_sha,
        )

    def handle_pushed_without_pr(
        self,
        *,
        issue: dict[str, object],
        context: finalize_pipeline.FinalizePipelineContext,
        create_as_draft: bool,
        create_detail_prefix: str | None = None,
    ) -> FinalizeResult:
        return self.handle_pushed_without_pr_fn(
            issue=issue,
            context=context,
            create_as_draft=create_as_draft,
            create_detail_prefix=create_detail_prefix,
        )

    def attempt_push_work_branch(self, work_branch: str) -> tuple[bool, str | None]:
        return self.attempt_push_work_branch_fn(work_branch)

    def collect_publish_signal_diagnostics(
        self,
        *,
        work_branch: str,
        context: finalize_pipeline.FinalizePipelineContext,
    ) -> PublishSignalDiagnostics:
        return self.collect_publish_signal_diagnostics_fn(
            work_branch=work_branch,
            context=context,
        )

    def format_publish_diagnostics(
        self,
        diagnostics: PublishSignalDiagnostics,
        *,
        push_detail: str | None = None,
    ) -> str:
        return self.format_publish_diagnostics_fn(
            diagnostics,
            push_detail=push_detail,
        )

    def set_changeset_review_pending_state(
        self,
        *,
        changeset_id: str,
        pr_payload: dict[str, object] | None,
        pushed: bool,
        fallback_pr_state: str | None,
    ) -> None:
        self.set_changeset_review_pending_state_fn(
            changeset_id=changeset_id,
            pr_payload=pr_payload,
            pushed=pushed,
            fallback_pr_state=fallback_pr_state,
        )


def _pipeline_context(**overrides: Any) -> finalize_pipeline.FinalizePipelineContext:
    payload: dict[str, Any] = {
        "changeset_id": "at-epic.1",
        "epic_id": "at-epic",
        "agent_id": "atelier/worker/codex/p100",
        "agent_bead_id": "at-agent",
        "started_at": dt.datetime.now(dt.timezone.utc),
        "repo_slug": None,
        "beads_root": Path("/beads"),
        "repo_root": Path("/repo"),
        "branch_pr": True,
        "branch_pr_mode": "draft",
        "branch_pr_strategy": "on-ready",
        "branch_history": "manual",
        "branch_squash_message": "deterministic",
        "project_data_dir": Path("/project"),
        "squash_message_agent_spec": None,
        "squash_message_agent_options": None,
        "squash_message_agent_home": None,
        "squash_message_agent_env": None,
        "git_path": "git",
    }
    payload.update(overrides)
    return finalize_pipeline.FinalizePipelineContext(**payload)


def test_run_finalize_pipeline_missing_changeset_id() -> None:
    service = _FinalizeServiceStub()
    result = finalize_pipeline.run_finalize_pipeline(
        context=_pipeline_context(changeset_id=""),
        service=service,
    )

    assert result.reason == "changeset_missing"
    assert result.continue_running is False


def test_run_finalize_pipeline_waiting_on_review_returns_pending(monkeypatch) -> None:
    issue = {
        "id": "at-epic.1",
        "status": "in_progress",
        "labels": [],
        "description": "changeset.work_branch: feat/root-at-epic.1\n",
    }
    monkeypatch.setattr(
        finalize_pipeline.beads,
        "run_bd_json",
        lambda *_args, **_kwargs: [issue],
    )

    service = _FinalizeServiceStub()
    service.changeset_waiting_on_review_or_signals_fn = lambda _issue, *, context: True

    result = finalize_pipeline.run_finalize_pipeline(
        context=_pipeline_context(),
        service=service,
    )

    assert result.reason == "changeset_review_pending"
    assert result.continue_running is True


def test_run_finalize_pipeline_waiting_on_review_uses_in_progress_status(monkeypatch) -> None:
    issue = {
        "id": "at-epic.1",
        "status": "in_progress",
        "labels": [],
        "description": "changeset.work_branch: feat/root-at-epic.1\n",
    }
    monkeypatch.setattr(
        finalize_pipeline.beads,
        "run_bd_json",
        lambda *_args, **_kwargs: [issue],
    )

    service = _FinalizeServiceStub()
    service.changeset_waiting_on_review_or_signals_fn = lambda _issue, *, context: True

    result = finalize_pipeline.run_finalize_pipeline(
        context=_pipeline_context(),
        service=service,
    )

    assert result.reason == "changeset_review_pending"
    assert result.continue_running is True


def test_run_finalize_pipeline_blocks_merged_pr_without_integration_proof(monkeypatch) -> None:
    issue = {
        "id": "at-epic.1",
        "status": "in_progress",
        "labels": [],
        "description": "changeset.work_branch: feat/root-at-epic.1\n",
    }
    monkeypatch.setattr(
        finalize_pipeline.beads,
        "run_bd_json",
        lambda *_args, **_kwargs: [issue],
    )
    monkeypatch.setattr(
        finalize_pipeline.git,
        "git_ref_exists",
        lambda *_args, **_kwargs: True,
    )

    service = _FinalizeServiceStub()
    service.lookup_pr_payload_fn = lambda _repo_slug, _branch: {
        "number": 88,
        "state": "MERGED",
        "mergedAt": "2026-02-28T00:00:00Z",
        "isDraft": False,
    }
    service.changeset_integration_signal_fn = lambda _issue, *, repo_slug, git_path: (False, None)
    blocked_reasons: list[str] = []
    notifications: list[str] = []
    service.mark_changeset_blocked_fn = lambda _changeset_id, *, reason: blocked_reasons.append(
        reason
    )
    service.send_planner_notification_fn = lambda **kwargs: notifications.append(
        str(kwargs.get("subject"))
    )
    service.finalize_terminal_changeset_fn = lambda **_kwargs: (_ for _ in ()).throw(
        AssertionError("terminal finalize must not run without integration proof")
    )

    result = finalize_pipeline.run_finalize_pipeline(
        context=_pipeline_context(repo_slug="org/repo"),
        service=service,
    )

    assert result.reason == "changeset_blocked_missing_integration"
    assert result.continue_running is False
    assert blocked_reasons == ["missing integration signal for merged terminal state"]
    assert notifications == ["NEEDS-DECISION: Missing integration signal (at-epic.1)"]


def test_run_finalize_pipeline_blocks_on_stack_integrity_preflight(monkeypatch) -> None:
    issue = {
        "id": "at-epic.1",
        "labels": [],
        "description": "changeset.work_branch: feat/root-at-epic.1\n",
    }
    monkeypatch.setattr(
        finalize_pipeline.beads,
        "run_bd_json",
        lambda *_args, **_kwargs: [issue],
    )

    service = _FinalizeServiceStub()
    blocked_reasons: list[str] = []
    notifications: list[str] = []
    service.stack_integrity_preflight_fn = lambda _issue, *, context: (
        finalize_pipeline.StackIntegrityCheck(
            ok=False,
            reason="dependency-parent-pr-closed",
            edge="at-epic.1 -> at-epic.0 (feat/parent)",
            detail="dependency parent PR is closed",
            remediation="Reopen or recreate the dependency parent PR.",
        )
    )
    service.mark_changeset_blocked_fn = lambda _changeset_id, *, reason: blocked_reasons.append(
        reason
    )
    service.send_planner_notification_fn = lambda **kwargs: notifications.append(
        str(kwargs.get("subject"))
    )

    result = finalize_pipeline.run_finalize_pipeline(
        context=_pipeline_context(),
        service=service,
    )

    assert result.reason == "changeset_stack_integrity_failed"
    assert result.continue_running is False
    assert blocked_reasons == ["sequential stack integrity failed: dependency-parent-pr-closed"]
    assert notifications == ["NEEDS-DECISION: Stack integrity failed (at-epic.1)"]


def test_run_finalize_pipeline_blocks_when_dependency_not_integrated(monkeypatch) -> None:
    issue = {
        "id": "at-epic.1",
        "labels": [],
        "description": "changeset.work_branch: feat/root-at-epic.1\n",
    }
    monkeypatch.setattr(
        finalize_pipeline.beads,
        "run_bd_json",
        lambda *_args, **_kwargs: [issue],
    )

    service = _FinalizeServiceStub()
    blocked_reasons: list[str] = []
    planner_messages: list[tuple[str, str]] = []
    service.stack_integrity_preflight_fn = lambda _issue, *, context: (
        finalize_pipeline.StackIntegrityCheck(
            ok=False,
            reason="dependency-not-integrated",
            edge="at-epic.1 -> at-epic.0 (feat/parent)",
            detail="dependencies missing integrated evidence: at-epic.0",
            remediation="Wait until every declared dependency shows integrated evidence.",
        )
    )
    service.mark_changeset_blocked_fn = lambda _changeset_id, *, reason: blocked_reasons.append(
        reason
    )
    service.send_planner_notification_fn = lambda **kwargs: planner_messages.append(
        (str(kwargs.get("subject")), str(kwargs.get("body")))
    )

    result = finalize_pipeline.run_finalize_pipeline(
        context=_pipeline_context(),
        service=service,
    )

    assert result.reason == "changeset_stack_integrity_failed"
    assert result.continue_running is False
    assert blocked_reasons == ["sequential stack integrity failed: dependency-not-integrated"]
    assert planner_messages
    subject, body = planner_messages[0]
    assert subject == "NEEDS-DECISION: Stack integrity failed (at-epic.1)"
    assert "dependencies missing integrated evidence: at-epic.0" in body


def test_run_finalize_pipeline_blocks_closed_changeset_while_pr_active(
    monkeypatch,
) -> None:
    issue = {
        "id": "at-epic.1",
        "status": "closed",
        "labels": ["cs:merged"],
        "description": "changeset.work_branch: feat/root-at-epic.1\n",
    }
    monkeypatch.setattr(
        finalize_pipeline.beads,
        "run_bd_json",
        lambda *_args, **_kwargs: [issue],
    )

    service = _FinalizeServiceStub()
    reopened: list[str] = []
    notifications: list[str] = []
    service.changeset_waiting_on_review_or_signals_fn = lambda _issue, *, context: True
    service.mark_changeset_in_progress_fn = lambda changeset_id: reopened.append(changeset_id)
    service.send_planner_notification_fn = lambda **kwargs: notifications.append(
        str(kwargs.get("subject"))
    )

    result = finalize_pipeline.run_finalize_pipeline(
        context=_pipeline_context(),
        service=service,
    )

    assert result.reason == "changeset_closed_pr_lifecycle_active"
    assert result.continue_running is False
    assert reopened == ["at-epic.1"]
    assert notifications == ["NEEDS-DECISION: Closed changeset has active PR lifecycle (at-epic.1)"]


def test_run_finalize_pipeline_blocks_closed_changeset_when_pr_lookup_is_ambiguous(
    monkeypatch,
) -> None:
    issue = {
        "id": "at-epic.1",
        "status": "closed",
        "labels": [],
        "description": "changeset.work_branch: feat/root-at-epic.1\n",
    }
    monkeypatch.setattr(
        finalize_pipeline.beads,
        "run_bd_json",
        lambda *_args, **_kwargs: [issue],
    )

    service = _FinalizeServiceStub()
    blocked_reasons: list[str] = []
    notifications: list[str] = []
    service.lookup_pr_payload_fn = lambda _repo_slug, _branch: None
    service.lookup_pr_payload_diagnostic_fn = lambda _repo_slug, _branch: (
        None,
        "ambiguous PR lookup for head branch 'feat/root-at-epic.1': multiple open PRs (#228, #244)",
    )
    service.mark_changeset_blocked_fn = lambda _changeset_id, *, reason: blocked_reasons.append(
        reason
    )
    service.send_planner_notification_fn = lambda **kwargs: notifications.append(
        str(kwargs.get("subject"))
    )

    result = finalize_pipeline.run_finalize_pipeline(
        context=_pipeline_context(repo_slug="org/repo"),
        service=service,
    )

    assert result.reason == "changeset_pr_status_query_failed"
    assert result.continue_running is False
    assert blocked_reasons == ["closed changeset PR lifecycle query failed"]
    assert notifications == ["NEEDS-DECISION: PR status query failed (at-epic.1)"]


def test_run_finalize_pipeline_treats_closed_status_as_terminal_without_labels(monkeypatch) -> None:
    issue = {
        "id": "at-epic.1",
        "status": "closed",
        "labels": [],
        "description": "changeset.work_branch: feat/root-at-epic.1\n",
    }
    monkeypatch.setattr(
        finalize_pipeline.beads,
        "run_bd_json",
        lambda *_args, **_kwargs: [issue],
    )

    service = _FinalizeServiceStub()
    closed: list[str] = []
    finalized: list[tuple[str, str | None]] = []
    service.mark_changeset_closed_fn = lambda changeset_id: closed.append(changeset_id)
    service.finalize_terminal_changeset_fn = lambda *, context, terminal_state, integrated_sha: (
        finalized.append((terminal_state, integrated_sha))
        or FinalizeResult(continue_running=True, reason="changeset_complete")
    )

    result = finalize_pipeline.run_finalize_pipeline(
        context=_pipeline_context(),
        service=service,
    )

    assert result.reason == "changeset_complete"
    assert result.continue_running is True
    assert closed == []
    assert finalized == [("abandoned", None)]


def test_run_finalize_pipeline_closed_status_checks_integration_before_abandon(monkeypatch) -> None:
    issue = {
        "id": "at-epic.1",
        "status": "closed",
        "labels": [],
        "description": "changeset.work_branch: feat/root-at-epic.1\n",
    }
    monkeypatch.setattr(
        finalize_pipeline.beads,
        "run_bd_json",
        lambda *_args, **_kwargs: [issue],
    )

    service = _FinalizeServiceStub()
    service.changeset_integration_signal_fn = lambda _issue, *, repo_slug, git_path: (
        True,
        "abc1234",
    )
    closed: list[str] = []
    finalized: list[tuple[str, str | None]] = []
    updates: list[tuple[str, str]] = []
    service.mark_changeset_closed_fn = lambda changeset_id: closed.append(changeset_id)
    service.finalize_terminal_changeset_fn = lambda *, context, terminal_state, integrated_sha: (
        finalized.append((terminal_state, integrated_sha))
        or FinalizeResult(continue_running=True, reason="changeset_complete")
    )
    monkeypatch.setattr(
        finalize_pipeline.beads,
        "update_changeset_integrated_sha",
        lambda changeset_id, integrated_sha, **_kwargs: updates.append(
            (changeset_id, integrated_sha)
        ),
    )

    result = finalize_pipeline.run_finalize_pipeline(
        context=_pipeline_context(),
        service=service,
    )

    assert result.reason == "changeset_complete"
    assert result.continue_running is True
    assert closed == []
    assert finalized == [("merged", None)]
    assert updates == [("at-epic.1", "abc1234")]


def test_run_finalize_pipeline_updates_missing_integrated_sha(monkeypatch) -> None:
    issue = {
        "id": "at-epic.1",
        "status": "closed",
        "labels": ["cs:merged"],
        "description": "changeset.work_branch: feat/root-at-epic.1\n",
    }
    monkeypatch.setattr(
        finalize_pipeline.beads,
        "run_bd_json",
        lambda *_args, **_kwargs: [issue],
    )

    service = _FinalizeServiceStub()
    service.changeset_integration_signal_fn = lambda _issue, *, repo_slug, git_path: (
        True,
        "abc1234",
    )
    finalized: list[tuple[str, str | None]] = []
    service.finalize_terminal_changeset_fn = lambda *, context, terminal_state, integrated_sha: (
        finalized.append((terminal_state, integrated_sha))
        or FinalizeResult(continue_running=True, reason="changeset_complete")
    )

    updates: list[tuple[str, str]] = []
    monkeypatch.setattr(
        finalize_pipeline.beads,
        "update_changeset_integrated_sha",
        lambda changeset_id, integrated_sha, **_kwargs: updates.append(
            (changeset_id, integrated_sha)
        ),
    )

    result = finalize_pipeline.run_finalize_pipeline(
        context=_pipeline_context(),
        service=service,
    )

    assert result.reason == "changeset_complete"
    assert result.continue_running is True
    assert finalized == [("merged", None)]
    assert updates == [("at-epic.1", "abc1234")]


def test_run_finalize_pipeline_preserves_recorded_integrated_sha(monkeypatch) -> None:
    issue = {
        "id": "at-epic.1",
        "status": "closed",
        "labels": ["cs:merged"],
        "description": (
            "changeset.work_branch: feat/root-at-epic.1\nchangeset.integrated_sha: 1111111\n"
        ),
    }
    monkeypatch.setattr(
        finalize_pipeline.beads,
        "run_bd_json",
        lambda *_args, **_kwargs: [issue],
    )

    service = _FinalizeServiceStub()
    service.changeset_integration_signal_fn = lambda _issue, *, repo_slug, git_path: (
        True,
        "2222222",
    )
    finalized: list[tuple[str, str | None]] = []
    service.finalize_terminal_changeset_fn = lambda *, context, terminal_state, integrated_sha: (
        finalized.append((terminal_state, integrated_sha))
        or FinalizeResult(continue_running=True, reason="changeset_complete")
    )

    updates: list[tuple[str, str]] = []
    monkeypatch.setattr(
        finalize_pipeline.beads,
        "update_changeset_integrated_sha",
        lambda changeset_id, integrated_sha, **_kwargs: updates.append(
            (changeset_id, integrated_sha)
        ),
    )

    warnings: list[str] = []
    monkeypatch.setattr(finalize_pipeline.atelier_log, "warning", warnings.append)

    result = finalize_pipeline.run_finalize_pipeline(
        context=_pipeline_context(),
        service=service,
    )

    assert result.reason == "changeset_complete"
    assert result.continue_running is True
    assert finalized == [("merged", None)]
    assert updates == []
    assert warnings == [
        "changeset=at-epic.1 finalize integrated SHA mismatch "
        "recorded=1111111 observed=2222222; preserving recorded value"
    ]


def test_run_finalize_pipeline_passes_ready_mode_to_pr_gate(monkeypatch) -> None:
    issue = {
        "id": "at-epic.1",
        "labels": [],
        "description": "changeset.work_branch: feat/root-at-epic.1\n",
    }
    monkeypatch.setattr(
        finalize_pipeline.beads,
        "run_bd_json",
        lambda *_args, **_kwargs: [issue],
    )
    monkeypatch.setattr(
        finalize_pipeline.git,
        "git_ref_exists",
        lambda *_args, **_kwargs: True,
    )

    service = _FinalizeServiceStub()
    observed: list[bool] = []
    service.handle_pushed_without_pr_fn = (
        lambda *, issue, context, create_as_draft, create_detail_prefix=None: (
            observed.append(create_as_draft)
            or FinalizeResult(continue_running=True, reason="changeset_review_pending")
        )
    )

    result = finalize_pipeline.run_finalize_pipeline(
        context=_pipeline_context(branch_pr_mode="ready"),
        service=service,
    )

    assert result.reason == "changeset_review_pending"
    assert result.continue_running is True
    assert observed == [False]


def test_run_finalize_pipeline_uses_diagnostic_pr_payload_before_create(monkeypatch) -> None:
    issue = {
        "id": "at-epic.1",
        "labels": [],
        "description": (
            "changeset.work_branch: feat/root-at-epic.1\n"
            "changeset.parent_branch: feat/parent\n"
            "changeset.root_branch: feat/root\n"
        ),
    }
    monkeypatch.setattr(
        finalize_pipeline.beads,
        "run_bd_json",
        lambda *_args, **_kwargs: [issue],
    )
    monkeypatch.setattr(
        finalize_pipeline.git,
        "git_ref_exists",
        lambda *_args, **_kwargs: True,
    )

    service = _FinalizeServiceStub()
    service.lookup_pr_payload_fn = lambda _repo_slug, _branch: None
    service.lookup_pr_payload_diagnostic_fn = lambda _repo_slug, _branch: (
        {"number": 165, "baseRefName": "main", "state": "OPEN", "isDraft": False},
        None,
    )
    aligned: list[str] = []
    pending: list[str] = []
    service.align_existing_pr_base_fn = lambda *, issue, pr_payload, context: (
        aligned.append(str(pr_payload.get("baseRefName"))) or True,
        "retargeted",
    )
    service.set_changeset_review_pending_state_fn = (
        lambda *, changeset_id, pr_payload, pushed, fallback_pr_state: pending.append(changeset_id)
    )
    service.handle_pushed_without_pr_fn = lambda **_kwargs: (_ for _ in ()).throw(
        AssertionError("PR creation path must not run when diagnostic lookup finds a PR")
    )

    result = finalize_pipeline.run_finalize_pipeline(
        context=_pipeline_context(repo_slug="org/repo"),
        service=service,
    )

    assert result.reason == "changeset_review_pending"
    assert result.continue_running is True
    assert aligned == ["main"]
    assert pending == ["at-epic.1"]


def test_run_finalize_pipeline_blocks_when_pr_base_alignment_fails(monkeypatch) -> None:
    issue = {
        "id": "at-epic.1",
        "labels": [],
        "description": "changeset.work_branch: feat/root-at-epic.1\n",
    }
    monkeypatch.setattr(
        finalize_pipeline.beads,
        "run_bd_json",
        lambda *_args, **_kwargs: [issue],
    )

    service = _FinalizeServiceStub()
    service.lookup_pr_payload_fn = lambda _repo_slug, _branch: {
        "number": 101,
        "baseRefName": "feat",
    }
    service.align_existing_pr_base_fn = lambda *, issue, pr_payload, context: (
        False,
        "expected=main actual=feat; failed to restack work branch",
    )
    marked: list[str] = []
    notifications: list[str] = []
    service.mark_changeset_in_progress_fn = lambda _changeset_id: marked.append("in_progress")
    service.send_planner_notification_fn = lambda **kwargs: notifications.append(
        str(kwargs.get("subject"))
    )

    result = finalize_pipeline.run_finalize_pipeline(
        context=_pipeline_context(repo_slug="org/repo"),
        service=service,
    )

    assert result.reason == "changeset_pr_base_alignment_failed"
    assert result.continue_running is False
    assert marked == ["in_progress"]
    assert notifications == ["NEEDS-DECISION: PR base mismatch (at-epic.1)"]


def test_run_finalize_pipeline_aligns_pr_base_before_pending(monkeypatch) -> None:
    issue = {
        "id": "at-epic.1",
        "labels": [],
        "description": "changeset.work_branch: feat/root-at-epic.1\n",
    }
    monkeypatch.setattr(
        finalize_pipeline.beads,
        "run_bd_json",
        lambda *_args, **_kwargs: [issue],
    )

    service = _FinalizeServiceStub()
    service.lookup_pr_payload_fn = lambda _repo_slug, _branch: {
        "number": 101,
        "baseRefName": "main",
    }
    aligned: list[str] = []
    pending: list[str] = []
    service.align_existing_pr_base_fn = lambda *, issue, pr_payload, context: (
        aligned.append(str(pr_payload.get("baseRefName"))) or True,
        "retargeted",
    )
    service.set_changeset_review_pending_state_fn = (
        lambda *, changeset_id, pr_payload, pushed, fallback_pr_state: pending.append(changeset_id)
    )

    result = finalize_pipeline.run_finalize_pipeline(
        context=_pipeline_context(repo_slug="org/repo"),
        service=service,
    )

    assert result.reason == "changeset_review_pending"
    assert result.continue_running is True
    assert aligned == ["main"]
    assert pending == ["at-epic.1"]

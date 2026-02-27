from __future__ import annotations

import datetime as dt
from pathlib import Path
from unittest.mock import patch

import pytest

from atelier import config, lifecycle, planner_overview
from atelier.worker import finalize_pipeline, reconcile, selection
from atelier.worker.session import startup


class _NextChangesetMatrixService(startup.NextChangesetService):
    def __init__(self, issue: dict[str, object]) -> None:
        self._issue = issue

    def show_issue(self, issue_id: str) -> dict[str, object] | None:
        if issue_id == "at-epic":
            return self._issue
        return None

    def changeset_waiting_on_review_or_signals(
        self,
        issue: dict[str, object],
        *,
        repo_slug: str | None,
        branch_pr: bool,
        branch_pr_strategy: object,
        git_path: str | None,
    ) -> bool:
        del issue, repo_slug, branch_pr, branch_pr_strategy, git_path
        return False

    def is_changeset_recovery_candidate(
        self,
        issue: dict[str, object],
        *,
        repo_slug: str | None,
        branch_pr: bool,
        git_path: str | None,
    ) -> bool:
        del issue, repo_slug, branch_pr, git_path
        return False

    def changeset_has_review_handoff_signal(
        self,
        issue: dict[str, object],
        *,
        repo_slug: str | None,
        branch_pr: bool,
        git_path: str | None,
    ) -> bool:
        del issue, repo_slug, branch_pr, git_path
        return False

    def has_open_descendant_changesets(self, changeset_id: str) -> bool:
        del changeset_id
        return False

    def list_descendant_changesets(
        self,
        parent_id: str,
        *,
        include_closed: bool,
    ) -> list[dict[str, object]]:
        del parent_id, include_closed
        return []

    def is_changeset_in_progress(self, issue: dict[str, object]) -> bool:
        return lifecycle.canonical_lifecycle_status(issue.get("status")) == "in_progress"


class _FinalizeMatrixService(finalize_pipeline.FinalizePipelineService):
    def __init__(self) -> None:
        self.closed_ids: list[str] = []

    def issue_labels(self, issue: dict[str, object]) -> set[str]:
        return {str(label) for label in issue.get("labels", [])}

    def has_open_descendant_changesets(self, changeset_id: str) -> bool:
        del changeset_id
        return False

    def has_blocking_messages(self, *, thread_ids: set[str], started_at: dt.datetime) -> bool:
        del thread_ids, started_at
        return False

    def mark_changeset_children_in_progress(self, changeset_id: str) -> None:
        del changeset_id

    def close_completed_container_changesets(self, epic_id: str) -> list[str]:
        del epic_id
        return []

    def promote_planned_descendant_changesets(self, changeset_id: str) -> None:
        del changeset_id

    def changeset_integration_signal(
        self, issue: dict[str, object], *, repo_slug: str | None, git_path: str | None
    ) -> tuple[bool, str | None]:
        del issue, repo_slug, git_path
        return False, None

    def recover_premature_merged_changeset(
        self,
        *,
        issue: dict[str, object],
        context: finalize_pipeline.FinalizePipelineContext,
    ):
        del issue, context
        return None

    def mark_changeset_blocked(self, changeset_id: str, *, reason: str) -> None:
        del changeset_id, reason

    def send_planner_notification(
        self, *, subject: str, body: str, agent_id: str, thread_id: str | None
    ) -> None:
        del subject, body, agent_id, thread_id

    def mark_changeset_closed(self, changeset_id: str) -> None:
        self.closed_ids.append(changeset_id)

    def finalize_epic_if_complete(self, *, context: finalize_pipeline.FinalizePipelineContext):
        del context
        return finalize_pipeline.FinalizeResult(continue_running=True, reason="changeset_complete")

    def mark_changeset_in_progress(self, changeset_id: str) -> None:
        del changeset_id

    def stack_integrity_preflight(
        self,
        issue: dict[str, object],
        *,
        context: finalize_pipeline.FinalizePipelineContext,
    ) -> finalize_pipeline.StackIntegrityCheck:
        del issue, context
        return finalize_pipeline.StackIntegrityCheck(ok=True)

    def changeset_waiting_on_review_or_signals(
        self,
        issue: dict[str, object],
        *,
        context: finalize_pipeline.FinalizePipelineContext,
    ) -> bool:
        del issue, context
        return True

    def lookup_pr_payload(self, repo_slug: str | None, branch: str) -> dict[str, object] | None:
        del repo_slug, branch
        return None

    def lookup_pr_payload_diagnostic(
        self, repo_slug: str | None, branch: str
    ) -> tuple[dict[str, object] | None, str | None]:
        del repo_slug, branch
        return None, None

    def align_existing_pr_base(
        self,
        *,
        issue: dict[str, object],
        pr_payload: dict[str, object],
        context: finalize_pipeline.FinalizePipelineContext,
    ) -> tuple[bool, str | None]:
        del issue, pr_payload, context
        return True, None

    def update_changeset_review_from_pr(
        self,
        changeset_id: str,
        *,
        pr_payload: dict[str, object] | None,
        pushed: bool,
    ) -> None:
        del changeset_id, pr_payload, pushed

    def finalize_terminal_changeset(
        self,
        *,
        context: finalize_pipeline.FinalizePipelineContext,
        terminal_state: str,
        integrated_sha: str | None,
    ):
        del context, terminal_state, integrated_sha
        return finalize_pipeline.FinalizeResult(continue_running=True, reason="changeset_terminal")

    def handle_pushed_without_pr(
        self,
        *,
        issue: dict[str, object],
        context: finalize_pipeline.FinalizePipelineContext,
        create_as_draft: bool,
        create_detail_prefix: str | None = None,
    ):
        del issue, context, create_as_draft, create_detail_prefix
        return finalize_pipeline.FinalizeResult(
            continue_running=True,
            reason="changeset_review_pending",
        )

    def attempt_push_work_branch(self, work_branch: str) -> tuple[bool, str | None]:
        del work_branch
        return False, None

    def collect_publish_signal_diagnostics(
        self,
        *,
        work_branch: str,
        context: finalize_pipeline.FinalizePipelineContext,
    ):
        del work_branch, context
        return finalize_pipeline.PublishSignalDiagnostics(
            local_branch_exists=False,
            remote_branch_exists=False,
            worktree_path=None,
            dirty_entries=(),
        )

    def format_publish_diagnostics(
        self,
        diagnostics: finalize_pipeline.PublishSignalDiagnostics,
        *,
        push_detail: str | None = None,
    ) -> str:
        del diagnostics, push_detail
        return "diag"

    def set_changeset_review_pending_state(
        self,
        *,
        changeset_id: str,
        pr_payload: dict[str, object] | None,
        pushed: bool,
        fallback_pr_state: str | None,
    ) -> None:
        del changeset_id, pr_payload, pushed, fallback_pr_state


@pytest.mark.parametrize(
    ("status", "executable"),
    [
        ("open", True),
        ("in_progress", True),
        ("closed", False),
    ],
)
def test_lifecycle_matrix_claim_selection_startup_and_overview(
    status: str, executable: bool
) -> None:
    issue = {
        "id": "at-epic",
        "status": status,
        "labels": ["at:epic", "at:ready", "at:draft", "cs:planned"],
        "assignee": None,
    }
    planner_issue = dict(issue)
    planner_issue["assignee"] = "atelier/planner/codex/p3"

    claimability = selection.evaluate_epic_claimability(issue)
    assert claimability.claimable is executable

    filtered = selection.filter_epics(
        [issue],
        require_unassigned=True,
        allow_hooked=True,
        skip_draft=True,
    )
    assert bool(filtered) is executable

    startup_context = startup.NextChangesetContext(
        epic_id="at-epic",
        repo_slug=None,
        branch_pr=False,
        branch_pr_strategy="on-ready",
        git_path=None,
    )
    selected = startup.next_changeset_service(
        context=startup_context,
        service=_NextChangesetMatrixService(issue),
    )
    assert (selected is not None) is executable

    # Planner overview uses this predicate for ownership-policy diagnostics.
    assert selection.has_planner_executable_assignee(planner_issue) is executable

    rendered = planner_overview.render_epics([planner_issue], show_drafts=True)
    assert (f"- {planner_issue['id']} [" in rendered) is executable


def test_lifecycle_matrix_finalize_ignores_terminal_labels_when_status_active(monkeypatch) -> None:
    issue = {
        "id": "at-epic.1",
        "status": "in_progress",
        "labels": ["cs:abandoned", "cs:merged"],
        "description": "changeset.work_branch: feat/root-at-epic.1\n",
    }
    monkeypatch.setattr(
        finalize_pipeline.beads,
        "run_bd_json",
        lambda *_args, **_kwargs: [issue],
    )

    service = _FinalizeMatrixService()
    result = finalize_pipeline.run_finalize_pipeline(
        context=finalize_pipeline.FinalizePipelineContext(
            changeset_id="at-epic.1",
            epic_id="at-epic",
            agent_id="atelier/worker/codex/p100",
            agent_bead_id="at-agent",
            started_at=dt.datetime.now(dt.timezone.utc),
            repo_slug=None,
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            branch_pr=False,
            branch_pr_mode="draft",
            branch_pr_strategy="on-ready",
            branch_history="manual",
            branch_squash_message="deterministic",
            project_data_dir=Path("/project"),
            squash_message_agent_spec=None,
            squash_message_agent_options=None,
            squash_message_agent_home=None,
            squash_message_agent_env=None,
            git_path="git",
        ),
        service=service,
    )

    assert result.reason == "changeset_review_pending"
    assert service.closed_ids == []


def test_lifecycle_matrix_reconcile_ignores_terminal_labels_on_active_status() -> None:
    issues = [{"id": "at-1.7", "status": "open", "labels": ["cs:abandoned"]}]
    with patch("atelier.worker.reconcile.beads.list_all_changesets", return_value=issues):
        candidates = reconcile.list_reconcile_epic_candidates(
            project_config=config.ProjectConfig(
                project=config.ProjectSection(origin="https://github.com/org/repo"),
                branch=config.BranchConfig(),
            ),
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            changeset_integration_signal=lambda *_args, **_kwargs: (True, "abc1234"),
            resolve_epic_id_for_changeset=lambda *_args, **_kwargs: "at-1",
            is_closed_status=lambda _status: False,
            epic_root_integrated_into_parent=lambda *_args, **_kwargs: False,
        )

    assert candidates == {"at-1": ["at-1.7"]}

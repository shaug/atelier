"""Finalize decision pipeline for worker changesets."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .. import beads, git, prs
from .. import log as atelier_log
from ..agents import AgentSpec
from ..models import BranchPrMode
from ..pr_strategy import PrStrategy
from .models import FinalizeResult, PublishSignalDiagnostics

Issue = dict[str, object]


def _normalized_sha(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized or normalized.lower() == "null":
        return None
    return normalized


def _recorded_integrated_sha(issue: Issue) -> str | None:
    description = issue.get("description")
    description_text = description if isinstance(description, str) else ""
    fields = beads.parse_description_fields(description_text)
    return _normalized_sha(fields.get("changeset.integrated_sha"))


def _persist_integrated_sha(
    *,
    issue: Issue,
    changeset_id: str,
    integrated_sha: str | None,
    beads_root: Path,
    repo_root: Path,
) -> None:
    normalized_candidate = _normalized_sha(integrated_sha)
    if not normalized_candidate:
        return
    recorded_sha = _recorded_integrated_sha(issue)
    if recorded_sha:
        if recorded_sha != normalized_candidate:
            atelier_log.warning(
                "changeset="
                f"{changeset_id} finalize integrated SHA mismatch "
                f"recorded={recorded_sha} observed={normalized_candidate}; "
                "preserving recorded value"
            )
        return
    beads.update_changeset_integrated_sha(
        changeset_id,
        normalized_candidate,
        beads_root=beads_root,
        cwd=repo_root,
    )


@dataclass(frozen=True)
class FinalizePipelineContext:
    changeset_id: str
    epic_id: str
    agent_id: str
    agent_bead_id: str
    started_at: dt.datetime
    repo_slug: str | None
    beads_root: Path
    repo_root: Path
    branch_pr: bool
    branch_pr_mode: BranchPrMode
    branch_pr_strategy: PrStrategy
    branch_history: str
    branch_squash_message: str
    project_data_dir: Path | None
    squash_message_agent_spec: AgentSpec | None
    squash_message_agent_options: list[str] | None
    squash_message_agent_home: Path | None
    squash_message_agent_env: dict[str, str] | None
    git_path: str | None


@dataclass(frozen=True)
class StackIntegrityCheck:
    ok: bool
    reason: str | None = None
    edge: str | None = None
    detail: str | None = None
    remediation: str | None = None


class FinalizePipelineService(Protocol):
    def issue_labels(self, issue: Issue) -> set[str]: ...

    def find_invalid_changeset_labels(self, epic_id: str) -> list[str]: ...

    def send_invalid_changeset_labels_notification(
        self, *, epic_id: str, invalid_changesets: list[str], agent_id: str
    ) -> str: ...

    def has_open_descendant_changesets(self, changeset_id: str) -> bool: ...

    def has_blocking_messages(self, *, thread_ids: set[str], started_at: dt.datetime) -> bool: ...

    def mark_changeset_children_in_progress(self, changeset_id: str) -> None: ...

    def close_completed_container_changesets(self, epic_id: str) -> list[str]: ...

    def promote_planned_descendant_changesets(self, changeset_id: str) -> None: ...

    def changeset_integration_signal(
        self, issue: Issue, *, repo_slug: str | None, git_path: str | None
    ) -> tuple[bool, str | None]: ...

    def recover_premature_merged_changeset(
        self, *, issue: Issue, context: FinalizePipelineContext
    ) -> FinalizeResult | None: ...

    def mark_changeset_blocked(self, changeset_id: str, *, reason: str) -> None: ...

    def send_planner_notification(
        self, *, subject: str, body: str, agent_id: str, thread_id: str | None
    ) -> None: ...

    def mark_changeset_closed(self, changeset_id: str) -> None: ...

    def finalize_epic_if_complete(self, *, context: FinalizePipelineContext) -> FinalizeResult: ...

    def mark_changeset_in_progress(self, changeset_id: str) -> None: ...

    def stack_integrity_preflight(
        self, issue: Issue, *, context: FinalizePipelineContext
    ) -> StackIntegrityCheck: ...

    def changeset_waiting_on_review_or_signals(
        self, issue: Issue, *, context: FinalizePipelineContext
    ) -> bool: ...

    def lookup_pr_payload(self, repo_slug: str | None, branch: str) -> Issue | None: ...

    def lookup_pr_payload_diagnostic(
        self, repo_slug: str | None, branch: str
    ) -> tuple[Issue | None, str | None]: ...

    def align_existing_pr_base(
        self,
        *,
        issue: Issue,
        pr_payload: Issue,
        context: FinalizePipelineContext,
    ) -> tuple[bool, str | None]: ...

    def update_changeset_review_from_pr(
        self,
        changeset_id: str,
        *,
        pr_payload: Issue | None,
        pushed: bool,
    ) -> None: ...

    def finalize_terminal_changeset(
        self,
        *,
        context: FinalizePipelineContext,
        terminal_state: str,
        integrated_sha: str | None,
    ) -> FinalizeResult: ...

    def handle_pushed_without_pr(
        self,
        *,
        issue: Issue,
        context: FinalizePipelineContext,
        create_as_draft: bool,
        create_detail_prefix: str | None = None,
    ) -> FinalizeResult: ...

    def attempt_push_work_branch(self, work_branch: str) -> tuple[bool, str | None]: ...

    def collect_publish_signal_diagnostics(
        self, *, work_branch: str, context: FinalizePipelineContext
    ) -> PublishSignalDiagnostics: ...

    def format_publish_diagnostics(
        self, diagnostics: PublishSignalDiagnostics, *, push_detail: str | None = None
    ) -> str: ...

    def set_changeset_review_pending_state(
        self,
        *,
        changeset_id: str,
        pr_payload: Issue | None,
        pushed: bool,
        fallback_pr_state: str | None,
    ) -> None: ...


def run_finalize_pipeline(
    *,
    context: FinalizePipelineContext,
    service: FinalizePipelineService,
) -> FinalizeResult:
    changeset_id = context.changeset_id
    epic_id = context.epic_id
    agent_id = context.agent_id
    started_at = context.started_at
    repo_slug = context.repo_slug
    beads_root = context.beads_root
    repo_root = context.repo_root
    branch_pr = context.branch_pr
    branch_pr_mode = context.branch_pr_mode
    git_path = context.git_path
    if not changeset_id:
        return FinalizeResult(continue_running=False, reason="changeset_missing")
    issues = beads.run_bd_json(["show", changeset_id], beads_root=beads_root, cwd=repo_root)
    if not issues:
        return FinalizeResult(continue_running=False, reason="changeset_not_found")
    issue = issues[0]
    labels = service.issue_labels(issue)
    invalid_changesets = service.find_invalid_changeset_labels(epic_id)
    if invalid_changesets:
        service.send_invalid_changeset_labels_notification(
            epic_id=epic_id,
            invalid_changesets=invalid_changesets,
            agent_id=agent_id,
        )
        return FinalizeResult(continue_running=False, reason="changeset_label_violation")
    if "cs:merged" in labels or "cs:abandoned" in labels:
        if service.has_open_descendant_changesets(changeset_id):
            descendants = beads.list_descendant_changesets(
                changeset_id,
                beads_root=beads_root,
                cwd=repo_root,
                include_closed=False,
            )
            planned_ids = {
                issue_id
                for descendant in descendants
                if isinstance((issue_id := descendant.get("id")), str)
                and issue_id
                and "cs:planned" in service.issue_labels(descendant)
            }
            if planned_ids and service.has_blocking_messages(
                thread_ids={changeset_id, epic_id, *planned_ids},
                started_at=started_at,
            ):
                service.mark_changeset_children_in_progress(changeset_id)
                service.close_completed_container_changesets(epic_id)
                return FinalizeResult(
                    continue_running=False, reason="changeset_children_planning_blocked"
                )
            service.promote_planned_descendant_changesets(changeset_id)
            service.mark_changeset_children_in_progress(changeset_id)
            service.close_completed_container_changesets(epic_id)
            return FinalizeResult(continue_running=True, reason="changeset_children_pending")
        if "cs:merged" in labels:
            integration_proven, integrated_sha = service.changeset_integration_signal(
                issue, repo_slug=repo_slug, git_path=git_path
            )
            if not integration_proven:
                recovered = service.recover_premature_merged_changeset(
                    issue=issue,
                    context=context,
                )
                if recovered is not None:
                    return recovered
                service.mark_changeset_blocked(
                    changeset_id, reason="missing integration signal for cs:merged"
                )
                service.send_planner_notification(
                    subject=(f"NEEDS-DECISION: Missing integration signal ({changeset_id})"),
                    body="Changeset is labeled cs:merged but no integration signal "
                    "(changeset.integrated_sha or merged PR) was found.",
                    agent_id=agent_id,
                    thread_id=changeset_id,
                )
                return FinalizeResult(
                    continue_running=False,
                    reason="changeset_blocked_missing_integration",
                )
            _persist_integrated_sha(
                issue=issue,
                changeset_id=changeset_id,
                integrated_sha=integrated_sha,
                beads_root=beads_root,
                repo_root=repo_root,
            )
        service.mark_changeset_closed(changeset_id)
        service.close_completed_container_changesets(epic_id)
        return service.finalize_epic_if_complete(context=context)
    if branch_pr:
        integrity = service.stack_integrity_preflight(issue, context=context)
        if not integrity.ok:
            reason = integrity.reason or "dependency-parent-unresolved"
            service.mark_changeset_blocked(
                changeset_id, reason=f"sequential stack integrity failed: {reason}"
            )
            body_lines = ["Sequential dependency stack-integrity preflight failed during finalize."]
            if integrity.edge:
                body_lines.append(f"Failing edge: {integrity.edge}")
            if integrity.detail:
                body_lines.append(f"Detail: {integrity.detail}")
            if integrity.remediation:
                body_lines.append(f"Action: {integrity.remediation}")
            service.send_planner_notification(
                subject=f"NEEDS-DECISION: Stack integrity failed ({changeset_id})",
                body="\n".join(body_lines),
                agent_id=agent_id,
                thread_id=changeset_id,
            )
            return FinalizeResult(
                continue_running=False,
                reason="changeset_stack_integrity_failed",
            )
    if service.has_blocking_messages(
        thread_ids={changeset_id, epic_id},
        started_at=started_at,
    ):
        service.mark_changeset_blocked(changeset_id, reason="message requires planner decision")
        return FinalizeResult(continue_running=False, reason="changeset_blocked_message")
    if "cs:in_progress" in labels:
        if service.changeset_waiting_on_review_or_signals(issue, context=context):
            return FinalizeResult(continue_running=True, reason="changeset_review_pending")

    description = issue.get("description")
    fields = beads.parse_description_fields(description if isinstance(description, str) else "")
    work_branch = fields.get("changeset.work_branch")
    if not work_branch or work_branch.strip().lower() == "null":
        service.mark_changeset_blocked(
            changeset_id, reason="missing changeset.work_branch metadata"
        )
        service.send_planner_notification(
            subject=f"NEEDS-DECISION: Missing changeset metadata ({changeset_id})",
            body="Missing changeset.work_branch metadata needed to validate publish.",
            agent_id=agent_id,
            thread_id=changeset_id,
        )
        return FinalizeResult(continue_running=False, reason="changeset_blocked_missing_metadata")
    work_branch = work_branch.strip()
    pushed = git.git_ref_exists(repo_root, f"refs/remotes/origin/{work_branch}", git_path=git_path)
    pr_payload = None
    pr_lookup_error: str | None = None
    if repo_slug:
        pr_payload = service.lookup_pr_payload(repo_slug, work_branch)
        if pr_payload is None:
            payload_check, pr_lookup_error = service.lookup_pr_payload_diagnostic(
                repo_slug, work_branch
            )
            if payload_check is not None:
                pr_payload = payload_check
                pr_lookup_error = None
    if branch_pr and pr_lookup_error:
        atelier_log.warning(
            "changeset="
            f"{changeset_id} finalize PR status lookup failed branch={work_branch}: "
            f"{pr_lookup_error}"
        )
        service.mark_changeset_in_progress(changeset_id)
        service.send_planner_notification(
            subject=f"NEEDS-DECISION: PR status query failed ({changeset_id})",
            body=(
                "Unable to evaluate PR lifecycle during finalize because GitHub "
                f"status lookup failed for branch `{work_branch}`.\n"
                f"Error: {pr_lookup_error}\n"
                "Action: resolve GitHub access/query issues and rerun worker finalize."
            ),
            agent_id=agent_id,
            thread_id=changeset_id,
        )
        return FinalizeResult(continue_running=False, reason="changeset_pr_status_query_failed")
    lifecycle: str | None = None
    if branch_pr:
        review_requested = prs.has_review_requests(pr_payload)
        lifecycle = prs.lifecycle_state(
            pr_payload, pushed=pushed, review_requested=review_requested
        )
    if lifecycle == "merged":
        atelier_log.debug(f"changeset={changeset_id} finalize lifecycle=merged")
        service.update_changeset_review_from_pr(
            changeset_id,
            pr_payload=pr_payload,
            pushed=pushed,
        )
        _integration_ok, integrated_sha = service.changeset_integration_signal(
            issue, repo_slug=None, git_path=git_path
        )
        return service.finalize_terminal_changeset(
            context=context,
            terminal_state="merged",
            integrated_sha=integrated_sha,
        )
    if lifecycle == "closed":
        atelier_log.debug(f"changeset={changeset_id} finalize lifecycle=closed")
        service.update_changeset_review_from_pr(
            changeset_id,
            pr_payload=pr_payload,
            pushed=pushed,
        )
        integration_ok, integrated_sha = service.changeset_integration_signal(
            issue, repo_slug=repo_slug, git_path=git_path
        )
        return service.finalize_terminal_changeset(
            context=context,
            terminal_state="merged" if integration_ok else "abandoned",
            integrated_sha=integrated_sha if integration_ok else None,
        )
    if branch_pr and pushed and not pr_payload:
        integration_ok, integrated_sha = service.changeset_integration_signal(
            issue, repo_slug=repo_slug, git_path=git_path
        )
        if integration_ok:
            return service.finalize_terminal_changeset(
                context=context,
                terminal_state="merged",
                integrated_sha=integrated_sha,
            )
    if branch_pr and pushed and not pr_payload:
        return service.handle_pushed_without_pr(
            issue=issue,
            context=context,
            create_as_draft=branch_pr_mode == "draft",
        )
    if not pushed and not pr_payload:
        push_detail: str | None = None
        if branch_pr:
            pushed, push_detail = service.attempt_push_work_branch(work_branch)
            if pushed:
                if repo_slug:
                    pr_payload = service.lookup_pr_payload(repo_slug, work_branch)
                    if pr_payload is None:
                        payload_check, pr_lookup_error = service.lookup_pr_payload_diagnostic(
                            repo_slug, work_branch
                        )
                        if payload_check is not None:
                            pr_payload = payload_check
                            pr_lookup_error = None
                    if pr_lookup_error:
                        atelier_log.warning(
                            "changeset="
                            f"{changeset_id} push succeeded but PR status lookup "
                            f"failed branch={work_branch}: {pr_lookup_error}"
                        )
                        service.mark_changeset_in_progress(changeset_id)
                        service.send_planner_notification(
                            subject=(f"NEEDS-DECISION: PR status query failed ({changeset_id})"),
                            body=(
                                "Branch push succeeded but GitHub PR status lookup "
                                f"failed for `{work_branch}`.\n"
                                f"Error: {pr_lookup_error}\n"
                                "Action: resolve GitHub access/query issues and "
                                "rerun worker finalize."
                            ),
                            agent_id=agent_id,
                            thread_id=changeset_id,
                        )
                        return FinalizeResult(
                            continue_running=False,
                            reason="changeset_pr_status_query_failed",
                        )
                if branch_pr and not pr_payload:
                    return service.handle_pushed_without_pr(
                        issue=issue,
                        context=context,
                        create_as_draft=branch_pr_mode == "draft",
                        create_detail_prefix=push_detail,
                    )
                service.set_changeset_review_pending_state(
                    changeset_id=changeset_id,
                    pr_payload=pr_payload,
                    pushed=True,
                    fallback_pr_state=None,
                )
                return FinalizeResult(continue_running=True, reason="changeset_review_pending")

        diagnostics = service.collect_publish_signal_diagnostics(
            work_branch=work_branch,
            context=context,
        )
        diagnostics_text = service.format_publish_diagnostics(diagnostics, push_detail=push_detail)
        if diagnostics.has_recoverable_local_state:
            service.mark_changeset_in_progress(changeset_id)
            beads.run_bd_command(
                [
                    "update",
                    changeset_id,
                    "--append-notes",
                    "publish_pending: no push/PR signal after worker completion; "
                    "kept changeset in-progress for retry.",
                ],
                beads_root=beads_root,
                cwd=repo_root,
                allow_failure=True,
            )
            service.send_planner_notification(
                subject=f"NEEDS-DECISION: Publish incomplete ({changeset_id})",
                body=(
                    "No push or PR detected after worker completion. "
                    "Recovered to in_progress for retry.\n"
                    f"{diagnostics_text}"
                ),
                agent_id=agent_id,
                thread_id=changeset_id,
            )
            return FinalizeResult(continue_running=False, reason="changeset_publish_pending")

        service.mark_changeset_blocked(changeset_id, reason="publish/checks signals missing")
        service.send_planner_notification(
            subject=f"NEEDS-DECISION: Publish/checks missing ({changeset_id})",
            body=(
                "No push or PR detected after worker completion and no local "
                "recoverable state found.\n"
                f"{diagnostics_text}"
            ),
            agent_id=agent_id,
            thread_id=changeset_id,
        )
        return FinalizeResult(continue_running=False, reason="changeset_blocked_publish_missing")
    if branch_pr and pr_payload:
        aligned, alignment_detail = service.align_existing_pr_base(
            issue=issue,
            pr_payload=pr_payload,
            context=context,
        )
        if not aligned:
            service.mark_changeset_in_progress(changeset_id)
            body = (
                "Detected a PR base mismatch but automatic base correction "
                "failed during finalize.\n"
            )
            if alignment_detail:
                body = f"{body}Detail: {alignment_detail}\n"
            body = (
                f"{body}Action: resolve PR base mismatch (expected base for "
                f"`{work_branch}`) and rerun worker finalize."
            )
            service.send_planner_notification(
                subject=f"NEEDS-DECISION: PR base mismatch ({changeset_id})",
                body=body,
                agent_id=agent_id,
                thread_id=changeset_id,
            )
            return FinalizeResult(
                continue_running=False,
                reason="changeset_pr_base_alignment_failed",
            )
        if alignment_detail:
            atelier_log.info(
                f"changeset={changeset_id} PR base alignment applied: {alignment_detail}"
            )
            refreshed_payload = service.lookup_pr_payload(repo_slug, work_branch)
            if refreshed_payload is not None:
                pr_payload = refreshed_payload
        service.set_changeset_review_pending_state(
            changeset_id=changeset_id,
            pr_payload=pr_payload,
            pushed=pushed,
            fallback_pr_state=None,
        )
        return FinalizeResult(continue_running=True, reason="changeset_review_pending")
    return FinalizeResult(continue_running=True, reason="changeset_published")

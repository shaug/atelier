"""Finalize decision pipeline for worker changesets."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .. import beads, git, lifecycle, prs
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


def _normalized_branch(value: object) -> str | None:
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


def _stored_review_state(issue: Issue) -> str | None:
    description = issue.get("description")
    description_text = description if isinstance(description, str) else ""
    fields = beads.parse_description_fields(description_text)
    return lifecycle.normalize_review_state(fields.get("pr_state"))


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


def _block_missing_merged_integration(
    *,
    issue: Issue,
    changeset_id: str,
    work_branch: str,
    agent_id: str,
    repo_slug: str | None,
    repo_root: Path,
    git_path: str | None,
    service: "FinalizePipelineService",
) -> FinalizeResult:
    description = issue.get("description")
    fields = beads.parse_description_fields(description if isinstance(description, str) else "")
    root_branch = _normalized_branch(fields.get("changeset.root_branch"))
    workspace_parent = _normalized_branch(fields.get("workspace.parent_branch"))
    default_branch = _normalized_branch(git.git_default_branch(repo_root, git_path=git_path))
    expected_mainline = (
        workspace_parent if workspace_parent and workspace_parent != root_branch else default_branch
    )
    if expected_mainline and expected_mainline == root_branch:
        expected_mainline = None

    service.mark_changeset_in_progress(changeset_id)
    body_lines = [
        "Changeset resolved to merged PR lifecycle but no mainline integration proof was found.",
        "Required proof: `changeset.integrated_sha` reachable from the canonical "
        "mainline target, or branch ancestry/patch-equivalence into that target.",
        f"Work branch: `{work_branch}`",
    ]
    if expected_mainline:
        body_lines.append(f"Expected mainline branch: `{expected_mainline}`")
    body_lines.append("Deterministic recovery for affected open child PRs:")
    if repo_slug:
        body_lines.append(f"- `gh pr list --repo {repo_slug} --state open --base {work_branch}`")
    body_lines.append("- `git fetch --prune origin`")
    if expected_mainline:
        body_lines.extend(
            [
                (f"- `git rebase --onto {expected_mainline} {work_branch} <child-work-branch>`"),
                "- `git push --force-with-lease origin <child-work-branch>`",
            ]
        )
        if repo_slug:
            body_lines.append(
                f"- `gh pr edit <child-pr-number> --repo {repo_slug} --base {expected_mainline}`"
            )
    else:
        body_lines.append(
            "- `bd show <changeset-id>` and verify workspace/default parent branch metadata"
        )
        body_lines.append("- Rerun finalize after parent metadata is repaired")
    body_lines.append("Action: rerun worker finalize after restack/retarget completes.")
    service.send_planner_notification(
        subject=f"NEEDS-DECISION: Missing integration signal ({changeset_id})",
        body="\n".join(body_lines),
        agent_id=agent_id,
        thread_id=changeset_id,
    )
    return FinalizeResult(
        continue_running=False,
        reason="changeset_in_progress_missing_integration",
    )


def _finalize_from_pr_lifecycle(
    *,
    lifecycle_state: str | None,
    issue: Issue,
    changeset_id: str,
    work_branch: str,
    repo_slug: str | None,
    git_path: str | None,
    pr_payload: Issue | None,
    pushed: bool,
    context: "FinalizePipelineContext",
    agent_id: str,
    service: "FinalizePipelineService",
) -> FinalizeResult | None:
    """Finalize immediately for terminal PR lifecycle states when available."""
    if lifecycle_state == "merged":
        atelier_log.debug(f"changeset={changeset_id} finalize lifecycle=merged")
        service.update_changeset_review_from_pr(
            changeset_id,
            pr_payload=pr_payload,
            pushed=pushed,
        )
        integration_ok, integrated_sha = service.changeset_integration_signal(
            issue,
            repo_slug=repo_slug,
            git_path=git_path,
            require_target_branch_proof=True,
        )
        if not integration_ok:
            return _block_missing_merged_integration(
                issue=issue,
                changeset_id=changeset_id,
                work_branch=work_branch,
                agent_id=agent_id,
                repo_slug=repo_slug,
                repo_root=context.repo_root,
                git_path=git_path,
                service=service,
            )
        return service.finalize_terminal_changeset(
            context=context,
            terminal_state="merged",
            integrated_sha=integrated_sha,
        )
    if lifecycle_state == "closed":
        atelier_log.debug(f"changeset={changeset_id} finalize lifecycle=closed")
        service.update_changeset_review_from_pr(
            changeset_id,
            pr_payload=pr_payload,
            pushed=pushed,
        )
        integration_ok, integrated_sha = service.changeset_integration_signal(
            issue,
            repo_slug=repo_slug,
            git_path=git_path,
            require_target_branch_proof=True,
        )
        return service.finalize_terminal_changeset(
            context=context,
            terminal_state="merged" if integration_ok else "abandoned",
            integrated_sha=integrated_sha if integration_ok else None,
        )
    return None


def _with_stale_signal_recovery_reason(result: FinalizeResult) -> FinalizeResult:
    """Annotate successful finalize results when stale closed-state signals recover."""
    if not result.continue_running:
        return result
    return FinalizeResult(
        continue_running=True,
        reason="changeset_closed_pr_lifecycle_stale_recovered",
    )


def _refresh_closed_active_pr_lifecycle(
    *,
    issue: Issue,
    context: "FinalizePipelineContext",
    changeset_id: str,
    work_branch: str,
    repo_slug: str | None,
    git_path: str | None,
    service: "FinalizePipelineService",
) -> tuple[bool, FinalizeResult | None]:
    """Refresh closed-state active PR lifecycle before escalation.

    Returns:
        Tuple of (active lifecycle after refresh, optional finalize result when
        refresh yields a terminal/error outcome that should short-circuit).
    """
    if not (context.branch_pr and repo_slug and work_branch):
        return True, None
    pushed = git.git_ref_exists(
        context.repo_root, f"refs/remotes/origin/{work_branch}", git_path=git_path
    )
    refreshed_payload, refresh_error = service.lookup_pr_payload_diagnostic(repo_slug, work_branch)
    if refresh_error:
        atelier_log.warning(
            "changeset="
            f"{changeset_id} finalize closed-state active lifecycle refresh failed "
            f"branch={work_branch}: {refresh_error}"
        )
        service.mark_changeset_blocked(
            changeset_id, reason="closed changeset PR lifecycle refresh failed"
        )
        service.send_planner_notification(
            subject=f"NEEDS-DECISION: PR status query failed ({changeset_id})",
            body=(
                "Unable to reconcile active PR lifecycle for a closed changeset "
                "because GitHub PR status refresh failed.\n"
                f"Branch: `{work_branch}`\n"
                f"Error: {refresh_error}\n"
                "Action: resolve GitHub access/query issues and rerun worker finalize."
            ),
            agent_id=context.agent_id,
            thread_id=changeset_id,
        )
        return True, FinalizeResult(
            continue_running=False,
            reason="changeset_closed_pr_lifecycle_refresh_failed",
        )
    refreshed_lifecycle = prs.lifecycle_state(
        refreshed_payload,
        pushed=pushed,
        review_requested=prs.has_review_requests(refreshed_payload),
    )
    if refreshed_lifecycle in {"merged", "closed"}:
        atelier_log.info(
            "changeset="
            f"{changeset_id} finalize recovered stale closed-state lifecycle "
            f"via refresh ({refreshed_lifecycle})"
        )
        terminal_result = _finalize_from_pr_lifecycle(
            lifecycle_state=refreshed_lifecycle,
            issue=issue,
            changeset_id=changeset_id,
            work_branch=work_branch,
            repo_slug=repo_slug,
            git_path=git_path,
            pr_payload=refreshed_payload,
            pushed=pushed,
            context=context,
            agent_id=context.agent_id,
            service=service,
        )
        if terminal_result is not None:
            return False, _with_stale_signal_recovery_reason(terminal_result)
        return False, None
    active_lifecycles = {"pushed", "draft-pr", "pr-open", "in-review", "approved"}
    if refreshed_lifecycle in active_lifecycles:
        return True, None
    atelier_log.warning(
        "changeset="
        f"{changeset_id} finalize PR lifecycle refresh was indeterminate "
        f"(state={refreshed_lifecycle or 'none'}); preserving active lifecycle guard"
    )
    return True, None


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

    def has_open_descendant_changesets(self, changeset_id: str) -> bool: ...

    def has_blocking_messages(self, *, thread_ids: set[str], started_at: dt.datetime) -> bool: ...

    def mark_changeset_children_in_progress(self, changeset_id: str) -> None: ...

    def changeset_integration_signal(
        self,
        issue: Issue,
        *,
        repo_slug: str | None,
        git_path: str | None,
        require_target_branch_proof: bool = False,
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
    canonical_status = lifecycle.canonical_lifecycle_status(issue.get("status"))
    review_state = _stored_review_state(issue)
    description = issue.get("description")
    fields = beads.parse_description_fields(description if isinstance(description, str) else "")
    raw_work_branch = fields.get("changeset.work_branch")
    work_branch = raw_work_branch.strip() if isinstance(raw_work_branch, str) else ""
    if work_branch.lower() == "null":
        work_branch = ""
    terminal_state: str | None = None
    if terminal_state is None and canonical_status == "closed":
        if review_state == "merged":
            terminal_state = "merged"
    stale_signal_recovered = False
    if canonical_status == "closed" and branch_pr and repo_slug and work_branch:
        closed_pr_lookup_error: str | None = None
        if service.lookup_pr_payload(repo_slug, work_branch) is None:
            payload_check, closed_pr_lookup_error = service.lookup_pr_payload_diagnostic(
                repo_slug, work_branch
            )
            if payload_check is not None:
                closed_pr_lookup_error = None
        if closed_pr_lookup_error:
            atelier_log.warning(
                "changeset="
                f"{changeset_id} finalize closed-state PR status lookup failed "
                f"branch={work_branch}: {closed_pr_lookup_error}"
            )
            service.mark_changeset_blocked(
                changeset_id, reason="closed changeset PR lifecycle query failed"
            )
            service.send_planner_notification(
                subject=f"NEEDS-DECISION: PR status query failed ({changeset_id})",
                body=(
                    "Unable to validate lifecycle for a closed changeset because "
                    f"GitHub PR status lookup failed for branch `{work_branch}`.\n"
                    f"Error: {closed_pr_lookup_error}\n"
                    "Action: resolve GitHub access/query issues and rerun worker finalize."
                ),
                agent_id=agent_id,
                thread_id=changeset_id,
            )
            return FinalizeResult(continue_running=False, reason="changeset_pr_status_query_failed")
    if terminal_state is not None or canonical_status == "closed":
        active_pr_lifecycle = service.changeset_waiting_on_review_or_signals(issue, context=context)
        if active_pr_lifecycle:
            active_pr_lifecycle, refreshed_result = _refresh_closed_active_pr_lifecycle(
                issue=issue,
                context=context,
                changeset_id=changeset_id,
                work_branch=work_branch,
                repo_slug=repo_slug,
                git_path=git_path,
                service=service,
            )
            if refreshed_result is not None:
                return refreshed_result
            stale_signal_recovered = not active_pr_lifecycle
        if beads.close_transition_has_active_pr_lifecycle(
            issue,
            active_pr_lifecycle=active_pr_lifecycle,
        ):
            atelier_log.warning(
                "changeset="
                f"{changeset_id} finalize suppressed terminal close while PR lifecycle "
                "remains active"
            )
            service.mark_changeset_in_progress(changeset_id)
            service.send_planner_notification(
                subject=f"NEEDS-DECISION: Closed changeset has active PR lifecycle ({changeset_id})",
                body=(
                    "Changeset status is closed but live PR lifecycle is still active "
                    "(draft/open/in-review/approved or gated pushed).\n"
                    "Automatic recovery set status back to `in_progress` to prevent "
                    "premature closure side effects.\n"
                    "Action: reconcile changeset lifecycle and PR state before retrying finalize."
                ),
                agent_id=agent_id,
                thread_id=changeset_id,
            )
            return FinalizeResult(
                continue_running=False, reason="changeset_closed_pr_lifecycle_active"
            )
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
                and lifecycle.canonical_lifecycle_status(descendant.get("status")) == "deferred"
            }
            if planned_ids and service.has_blocking_messages(
                thread_ids={changeset_id, epic_id, *planned_ids},
                started_at=started_at,
            ):
                service.mark_changeset_children_in_progress(changeset_id)
                return FinalizeResult(
                    continue_running=False, reason="changeset_children_planning_blocked"
                )
            if planned_ids:
                service.mark_changeset_children_in_progress(changeset_id)
                service.send_planner_notification(
                    subject=f"NEEDS-DECISION: Descendant promotion required ({changeset_id})",
                    body=(
                        "Worker finalize detected deferred child changesets under the claimed "
                        "changeset.\n"
                        "Planner owns deferred->open promotion and sequencing decisions.\n"
                        f"Deferred descendants: {', '.join(sorted(planned_ids))}\n"
                        "Action: planner should review scope split, promote the next child "
                        "changeset, then dispatch a new worker run."
                    ),
                    agent_id=agent_id,
                    thread_id=changeset_id,
                )
                return FinalizeResult(
                    continue_running=False,
                    reason="changeset_children_require_planner_promotion",
                )
            service.mark_changeset_children_in_progress(changeset_id)
            return FinalizeResult(continue_running=False, reason="changeset_children_pending")
        if terminal_state == "merged":
            integration_proven, integrated_sha = service.changeset_integration_signal(
                issue,
                repo_slug=repo_slug,
                git_path=git_path,
                require_target_branch_proof=True,
            )
            if not integration_proven:
                recovered = service.recover_premature_merged_changeset(
                    issue=issue,
                    context=context,
                )
                if recovered is not None:
                    return recovered
                return _block_missing_merged_integration(
                    issue=issue,
                    changeset_id=changeset_id,
                    work_branch=work_branch,
                    agent_id=agent_id,
                    repo_slug=repo_slug,
                    repo_root=repo_root,
                    git_path=git_path,
                    service=service,
                )
            _persist_integrated_sha(
                issue=issue,
                changeset_id=changeset_id,
                integrated_sha=integrated_sha,
                beads_root=beads_root,
                repo_root=repo_root,
            )
        if terminal_state is None:
            integration_proven, integrated_sha = service.changeset_integration_signal(
                issue,
                repo_slug=repo_slug,
                git_path=git_path,
                require_target_branch_proof=True,
            )
            if integration_proven:
                _persist_integrated_sha(
                    issue=issue,
                    changeset_id=changeset_id,
                    integrated_sha=integrated_sha,
                    beads_root=beads_root,
                    repo_root=repo_root,
                )
                terminal_state = "merged"
            else:
                terminal_state = "abandoned"
        final_result = service.finalize_terminal_changeset(
            context=context,
            terminal_state=terminal_state,
            integrated_sha=None,
        )
        if stale_signal_recovered:
            return _with_stale_signal_recovery_reason(final_result)
        return final_result
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
    if canonical_status == "in_progress" and service.changeset_waiting_on_review_or_signals(
        issue, context=context
    ):
        return FinalizeResult(continue_running=True, reason="changeset_review_pending")

    if not work_branch:
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
    lifecycle_state: str | None = None
    if branch_pr:
        review_requested = prs.has_review_requests(pr_payload)
        lifecycle_state = prs.lifecycle_state(
            pr_payload, pushed=pushed, review_requested=review_requested
        )
    terminal_result = _finalize_from_pr_lifecycle(
        lifecycle_state=lifecycle_state,
        issue=issue,
        changeset_id=changeset_id,
        work_branch=work_branch,
        repo_slug=repo_slug,
        git_path=git_path,
        pr_payload=pr_payload,
        pushed=pushed,
        context=context,
        agent_id=agent_id,
        service=service,
    )
    if terminal_result is not None:
        return terminal_result
    if branch_pr and pushed and not pr_payload:
        integration_ok, integrated_sha = service.changeset_integration_signal(
            issue,
            repo_slug=repo_slug,
            git_path=git_path,
            require_target_branch_proof=True,
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
            refreshed_payload, _refreshed_lookup_error = service.lookup_pr_payload_diagnostic(
                repo_slug, work_branch
            )
            refreshed_lifecycle: str | None = None
            if refreshed_payload is not None:
                refreshed_lifecycle = prs.lifecycle_state(
                    refreshed_payload,
                    pushed=pushed,
                    review_requested=prs.has_review_requests(refreshed_payload),
                )
            refreshed_terminal_result = _finalize_from_pr_lifecycle(
                lifecycle_state=refreshed_lifecycle,
                issue=issue,
                changeset_id=changeset_id,
                work_branch=work_branch,
                repo_slug=repo_slug,
                git_path=git_path,
                pr_payload=refreshed_payload,
                pushed=pushed,
                context=context,
                agent_id=agent_id,
                service=service,
            )
            if refreshed_terminal_result is not None:
                atelier_log.info(
                    "changeset="
                    f"{changeset_id} finalize bypassed PR base mismatch resolution after "
                    f"terminal refresh ({refreshed_lifecycle})"
                )
                return refreshed_terminal_result
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

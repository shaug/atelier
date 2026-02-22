"""PR gate helpers used during changeset finalization."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ... import beads, changesets, dependency_lineage, exec, git, pr_strategy, prs
from ... import log as atelier_log
from ..models import FinalizeResult


@dataclass(frozen=True)
class PrGateResult:
    """Typed PR gate result for pushed-without-pr handling."""

    finalize_result: FinalizeResult
    detail: str | None = None


def changeset_parent_lifecycle_state(
    issue: dict[str, object],
    *,
    repo_slug: str | None,
    repo_root: Path,
    git_path: str | None,
    beads_root: Path | None = None,
    lookup_pr_payload: Callable[..., dict[str, object] | None],
) -> str | None:
    description = issue.get("description")
    fields = beads.parse_description_fields(description if isinstance(description, str) else "")
    issue_cache: dict[str, dict[str, object] | None] = {}

    def lookup_dependency_issue(issue_id: str) -> dict[str, object] | None:
        if beads_root is None:
            return None
        if issue_id in issue_cache:
            return issue_cache[issue_id]
        issues = beads.run_bd_json(["show", issue_id], beads_root=beads_root, cwd=repo_root)
        issue_cache[issue_id] = issues[0] if issues else None
        return issue_cache[issue_id]

    lineage = dependency_lineage.resolve_parent_lineage(
        issue,
        root_branch=fields.get("changeset.root_branch"),
        lookup_issue=lookup_dependency_issue,
    )
    normalized = lineage.effective_parent_branch
    if normalized is None:
        return None
    normalized_root = lineage.root_branch
    if normalized_root and normalized == normalized_root and not lineage.used_dependency_parent:
        # True top-level changesets use root==parent; treat as no-parent so
        # strategies do not self-deadlock.
        return None
    if not repo_slug:
        return None
    pushed = git.git_ref_exists(repo_root, f"refs/remotes/origin/{normalized}", git_path=git_path)
    payload = lookup_pr_payload(repo_slug, normalized)
    review_requested = prs.has_review_requests(payload)
    return prs.lifecycle_state(payload, pushed=pushed, review_requested=review_requested)


def changeset_pr_creation_decision(
    issue: dict[str, object],
    *,
    repo_slug: str | None,
    repo_root: Path,
    git_path: str | None,
    branch_pr_strategy: object,
    beads_root: Path | None = None,
    lookup_pr_payload: Callable[..., dict[str, object] | None],
) -> pr_strategy.PrStrategyDecision:
    normalized_strategy = pr_strategy.normalize_pr_strategy(branch_pr_strategy)
    description = issue.get("description")
    fields = beads.parse_description_fields(description if isinstance(description, str) else "")
    issue_cache: dict[str, dict[str, object] | None] = {}

    def lookup_dependency_issue(issue_id: str) -> dict[str, object] | None:
        if beads_root is None:
            return None
        if issue_id in issue_cache:
            return issue_cache[issue_id]
        issues = beads.run_bd_json(["show", issue_id], beads_root=beads_root, cwd=repo_root)
        issue_cache[issue_id] = issues[0] if issues else None
        return issue_cache[issue_id]

    lineage = dependency_lineage.resolve_parent_lineage(
        issue,
        root_branch=fields.get("changeset.root_branch"),
        lookup_issue=lookup_dependency_issue,
    )
    if normalized_strategy == "sequential" and lineage.blocked:
        reason_suffix = lineage.blocker_reason or "dependency-parent-unresolved"
        if lineage.diagnostics:
            reason_suffix = f"{reason_suffix} ({lineage.diagnostics[0]})"
        return pr_strategy.PrStrategyDecision(
            strategy=normalized_strategy,
            parent_state=None,
            allow_pr=False,
            reason=f"blocked:{reason_suffix}",
        )

    parent_state = changeset_parent_lifecycle_state(
        issue,
        repo_slug=repo_slug,
        repo_root=repo_root,
        git_path=git_path,
        beads_root=beads_root,
        lookup_pr_payload=lookup_pr_payload,
    )
    if (
        normalized_strategy == "sequential"
        and lineage.used_dependency_parent
        and parent_state is None
    ):
        return pr_strategy.PrStrategyDecision(
            strategy=normalized_strategy,
            parent_state=None,
            allow_pr=False,
            reason="blocked:dependency-parent-state-unavailable",
        )
    return pr_strategy.pr_strategy_decision(normalized_strategy, parent_state=parent_state)


def set_changeset_review_pending_state(
    *,
    changeset_id: str,
    pr_payload: dict[str, object] | None,
    pushed: bool,
    fallback_pr_state: str | None,
    beads_root: Path,
    repo_root: Path,
    mark_changeset_in_progress: Callable[..., None],
    update_changeset_review_from_pr: Callable[..., None],
) -> None:
    mark_changeset_in_progress(changeset_id, beads_root=beads_root, repo_root=repo_root)
    if pr_payload:
        update_changeset_review_from_pr(
            changeset_id,
            pr_payload=pr_payload,
            pushed=pushed,
            beads_root=beads_root,
            repo_root=repo_root,
        )
        return
    if fallback_pr_state:
        beads.update_changeset_review(
            changeset_id,
            changesets.ReviewMetadata(pr_state=fallback_pr_state),
            beads_root=beads_root,
            cwd=repo_root,
        )


def attempt_create_draft_pr(
    *,
    repo_slug: str,
    issue: dict[str, object],
    work_branch: str,
    beads_root: Path,
    repo_root: Path,
    git_path: str | None,
    changeset_base_branch: Callable[..., str | None],
    render_changeset_pr_body: Callable[[dict[str, object]], str],
) -> tuple[bool, str]:
    base_branch = changeset_base_branch(
        issue, beads_root=beads_root, repo_root=repo_root, git_path=git_path
    )
    if not base_branch:
        return False, "missing PR base branch metadata"
    title = str(issue.get("title") or "").strip() or work_branch
    body = render_changeset_pr_body(issue)
    result = exec.try_run_command(
        [
            "gh",
            "pr",
            "create",
            "--repo",
            repo_slug,
            "--base",
            base_branch,
            "--head",
            work_branch,
            "--title",
            title,
            "--body",
            body,
            "--draft",
        ]
    )
    if result is None:
        return False, "missing required command: gh"
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        return False, detail or "gh pr create failed"
    detail = (result.stdout or "").strip()
    return True, detail or "created draft PR"


def handle_pushed_without_pr(
    *,
    issue: dict[str, object],
    changeset_id: str,
    agent_id: str,
    repo_slug: str | None,
    repo_root: Path,
    beads_root: Path,
    branch_pr_strategy: object,
    git_path: str | None,
    create_detail_prefix: str | None = None,
    changeset_base_branch: Callable[..., str | None],
    changeset_work_branch: Callable[[dict[str, object]], str | None],
    render_changeset_pr_body: Callable[[dict[str, object]], str],
    lookup_pr_payload: Callable[..., dict[str, object] | None],
    lookup_pr_payload_diagnostic: Callable[..., tuple[dict[str, object] | None, str | None]],
    mark_changeset_in_progress: Callable[..., None],
    send_planner_notification: Callable[..., None],
    update_changeset_review_from_pr: Callable[..., None],
    emit: Callable[[str], None],
    attempt_create_draft_pr_fn: Callable[..., tuple[bool, str]] | None = None,
) -> PrGateResult:
    decision = changeset_pr_creation_decision(
        issue,
        repo_slug=repo_slug,
        repo_root=repo_root,
        git_path=git_path,
        branch_pr_strategy=branch_pr_strategy,
        beads_root=beads_root,
        lookup_pr_payload=lookup_pr_payload,
    )
    if not decision.allow_pr:
        set_changeset_review_pending_state(
            changeset_id=changeset_id,
            pr_payload=None,
            pushed=True,
            fallback_pr_state="pushed",
            beads_root=beads_root,
            repo_root=repo_root,
            mark_changeset_in_progress=mark_changeset_in_progress,
            update_changeset_review_from_pr=update_changeset_review_from_pr,
        )
        return PrGateResult(
            finalize_result=FinalizeResult(
                continue_running=True, reason="changeset_review_pending"
            ),
            detail=decision.reason,
        )

    failure_reason = "changeset_pr_create_failed"
    failure_subject = "NEEDS-DECISION: PR creation failed"
    create_detail = create_detail_prefix or ""
    if not repo_slug:
        failure_reason = "changeset_pr_missing_repo_slug"
        failure_subject = "NEEDS-DECISION: PR provider config missing"
        create_detail = "missing GitHub repo slug for PR creation"
    else:
        work_branch = changeset_work_branch(issue)
        if not work_branch:
            create_detail = "missing changeset.work_branch metadata for PR creation"
        else:
            create_fn = attempt_create_draft_pr_fn or attempt_create_draft_pr
            created, detail = create_fn(
                repo_slug=repo_slug,
                issue=issue,
                work_branch=work_branch,
                beads_root=beads_root,
                repo_root=repo_root,
                git_path=git_path,
                changeset_base_branch=changeset_base_branch,
                render_changeset_pr_body=render_changeset_pr_body,
            )
            create_detail = detail
            if created:
                pr_payload = lookup_pr_payload(repo_slug, work_branch)
                lookup_error = None
                if pr_payload is None:
                    _payload_check, lookup_error = lookup_pr_payload_diagnostic(
                        repo_slug, work_branch
                    )
                if pr_payload:
                    set_changeset_review_pending_state(
                        changeset_id=changeset_id,
                        pr_payload=pr_payload,
                        pushed=True,
                        fallback_pr_state=None,
                        beads_root=beads_root,
                        repo_root=repo_root,
                        mark_changeset_in_progress=mark_changeset_in_progress,
                        update_changeset_review_from_pr=update_changeset_review_from_pr,
                    )
                else:
                    set_changeset_review_pending_state(
                        changeset_id=changeset_id,
                        pr_payload=None,
                        pushed=True,
                        fallback_pr_state="draft-pr",
                        beads_root=beads_root,
                        repo_root=repo_root,
                        mark_changeset_in_progress=mark_changeset_in_progress,
                        update_changeset_review_from_pr=update_changeset_review_from_pr,
                    )
                if lookup_error:
                    create_detail = f"{create_detail}; unable to verify created PR: {lookup_error}"
                return PrGateResult(
                    finalize_result=FinalizeResult(
                        continue_running=True, reason="changeset_review_pending"
                    ),
                    detail=create_detail or None,
                )
            # Recover from duplicate/race failures by checking live PR state.
            pr_payload = lookup_pr_payload(repo_slug, work_branch)
            lookup_error = None
            if pr_payload is None:
                _payload_check, lookup_error = lookup_pr_payload_diagnostic(repo_slug, work_branch)
            if pr_payload:
                set_changeset_review_pending_state(
                    changeset_id=changeset_id,
                    pr_payload=pr_payload,
                    pushed=True,
                    fallback_pr_state=None,
                    beads_root=beads_root,
                    repo_root=repo_root,
                    mark_changeset_in_progress=mark_changeset_in_progress,
                    update_changeset_review_from_pr=update_changeset_review_from_pr,
                )
                return PrGateResult(
                    finalize_result=FinalizeResult(
                        continue_running=True, reason="changeset_review_pending"
                    ),
                    detail="existing PR found after create failure",
                )
            if lookup_error:
                failure_reason = "changeset_pr_status_query_failed"
                failure_subject = "NEEDS-DECISION: PR status query failed"
                create_detail = f"{create_detail}; unable to verify existing PR: {lookup_error}"
                atelier_log.warning(
                    "changeset="
                    f"{changeset_id} PR status lookup failed after create attempt: "
                    f"{lookup_error}"
                )

    mark_changeset_in_progress(changeset_id, beads_root=beads_root, repo_root=repo_root)
    note = (
        "publish_pending: branch pushed but PR missing where "
        f"strategy allows PR ({decision.reason})"
    )
    if create_detail:
        note = f"{note}; PR creation attempt failed: {create_detail}"
    beads.run_bd_command(
        [
            "update",
            changeset_id,
            "--append-notes",
            note,
        ],
        beads_root=beads_root,
        cwd=repo_root,
        allow_failure=True,
    )
    body = (
        "Changeset branch is pushed but no PR exists where policy allows PR "
        f"creation (strategy={decision.strategy}, reason={decision.reason})."
    )
    if create_detail:
        body = f"{body}\nPR creation attempt failed: {create_detail}"
        emit(f"PR creation failed for {changeset_id}: {create_detail}")
    if failure_reason == "changeset_pr_missing_repo_slug":
        body = (
            f"{body}\nAction: configure GitHub provider metadata so finalize can "
            "create PRs automatically."
        )
    else:
        body = f"{body}\nAction: resolve `gh pr create` failure and rerun worker finalize."
    send_planner_notification(
        subject=f"{failure_subject} ({changeset_id})",
        body=body,
        agent_id=agent_id,
        thread_id=changeset_id,
        beads_root=beads_root,
        repo_root=repo_root,
        dry_run=False,
    )
    atelier_log.warning(
        "changeset="
        f"{changeset_id} finalize stopped reason={failure_reason} "
        f"strategy={decision.strategy} detail={create_detail or 'n/a'}"
    )
    return PrGateResult(
        finalize_result=FinalizeResult(continue_running=False, reason=failure_reason),
        detail=create_detail or None,
    )

"""Worker startup contract and changeset selection pipeline."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from pathlib import Path

from ..models import StartupContractResult
from ..review import ReviewFeedbackSelection


def next_changeset(
    *,
    epic_id: str,
    beads_root: Path,
    repo_root: Path,
    repo_slug: str | None,
    branch_pr: bool,
    branch_pr_strategy: object,
    git_path: str | None,
    issue_labels: Callable[[dict[str, object]], set[str]],
    is_changeset_ready: Callable[[dict[str, object]], bool],
    changeset_waiting_on_review_or_signals: Callable[..., bool],
    is_changeset_recovery_candidate: Callable[..., bool],
    has_open_descendant_changesets: Callable[..., bool],
    run_bd_json: Callable[..., list[dict[str, object]]],
    list_descendant_changesets: Callable[..., list[dict[str, object]]],
    is_changeset_in_progress: Callable[[dict[str, object]], bool],
) -> dict[str, object] | None:
    target = run_bd_json(["show", epic_id], beads_root=beads_root, cwd=repo_root)
    if target:
        issue = target[0]
        issue_id = issue.get("id")
        labels = issue_labels(issue)
        if "at:draft" in labels:
            return None
        if (
            isinstance(issue_id, str)
            and issue_id == epic_id
            and "at:changeset" in labels
            and "cs:merged" not in labels
            and "cs:abandoned" not in labels
            and (
                (
                    is_changeset_ready(issue)
                    and not changeset_waiting_on_review_or_signals(
                        issue,
                        repo_slug=repo_slug,
                        repo_root=repo_root,
                        branch_pr=branch_pr,
                        branch_pr_strategy=branch_pr_strategy,
                        git_path=git_path,
                    )
                )
                or is_changeset_recovery_candidate(
                    issue,
                    repo_slug=repo_slug,
                    repo_root=repo_root,
                    branch_pr=branch_pr,
                    git_path=git_path,
                )
            )
        ):
            if not has_open_descendant_changesets(
                epic_id, beads_root=beads_root, repo_root=repo_root
            ):
                return issue
        status = str(issue.get("status") or "").strip().lower()
        if (
            isinstance(issue_id, str)
            and issue_id == epic_id
            and "at:epic" in labels
            and "at:ready" in labels
            and status not in {"closed", "done"}
        ):
            descendants = list_descendant_changesets(
                epic_id,
                beads_root=beads_root,
                cwd=repo_root,
                include_closed=True,
            )
            if not descendants:
                return issue

    changesets = run_bd_json(
        ["ready", "--parent", epic_id, "--label", "at:changeset"],
        beads_root=beads_root,
        cwd=repo_root,
    )
    if not changesets:
        return None
    actionable = [
        issue
        for issue in changesets
        if is_changeset_ready(issue)
        and not changeset_waiting_on_review_or_signals(
            issue,
            repo_slug=repo_slug,
            repo_root=repo_root,
            branch_pr=branch_pr,
            branch_pr_strategy=branch_pr_strategy,
            git_path=git_path,
        )
    ]
    prioritized = sorted(
        actionable,
        key=lambda issue: (
            0 if is_changeset_in_progress(issue) else 1,
            str(issue.get("id") or ""),
        ),
    )
    for issue in prioritized:
        issue_id = issue.get("id")
        if isinstance(issue_id, str) and issue_id:
            if not has_open_descendant_changesets(
                issue_id, beads_root=beads_root, repo_root=repo_root
            ):
                return issue
    return None


def run_startup_contract(
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
    worker_queue_name: str,
    handle_queue_before_claim: Callable[..., bool],
    list_epics: Callable[..., list[dict[str, object]]],
    next_changeset_fn: Callable[..., dict[str, object] | None],
    resolve_hooked_epic: Callable[..., str | None],
    filter_epics: Callable[..., list[dict[str, object]]],
    sort_by_created_at: Callable[..., list[dict[str, object]]],
    stale_family_assigned_epics: Callable[..., list[dict[str, object]]],
    select_review_feedback_changeset: Callable[..., ReviewFeedbackSelection | None],
    parse_issue_time: Callable[[object], dt.datetime | None],
    select_global_review_feedback_changeset: Callable[
        ..., ReviewFeedbackSelection | None
    ],
    is_feedback_eligible_epic_status: Callable[[object], bool],
    issue_labels: Callable[[dict[str, object]], set[str]],
    check_inbox_before_claim: Callable[..., bool],
    select_epic_auto: Callable[..., str | None],
    select_epic_prompt: Callable[..., str | None],
    select_epic_from_ready_changesets: Callable[..., str | None],
    send_needs_decision: Callable[..., None],
    log_debug: Callable[[str], None],
    log_warning: Callable[[str], None],
    dry_run_log: Callable[[str], None],
    emit: Callable[[str], None],
    run_bd_json: Callable[..., list[dict[str, object]]],
    agent_family_id: Callable[[str], str],
    is_agent_session_active: Callable[[str], bool],
    die_fn: Callable[[str], None],
) -> StartupContractResult:
    """Apply startup_contract skill ordering to select the next epic."""
    if explicit_epic_id is not None:
        selected_epic = str(explicit_epic_id).strip()
        if not selected_epic:
            die_fn("epic id must not be empty")
        return StartupContractResult(
            epic_id=selected_epic,
            changeset_id=None,
            should_exit=False,
            reason="explicit_epic",
        )

    if queue_only:
        handle_queue_before_claim(
            agent_id,
            beads_root=beads_root,
            repo_root=repo_root,
            queue_name=worker_queue_name,
            force_prompt=True,
            dry_run=dry_run,
            assume_yes=assume_yes,
        )
        if dry_run:
            dry_run_log("Queue-only run would exit after handling queue.")
        return StartupContractResult(
            epic_id=None, changeset_id=None, should_exit=True, reason="queue_only"
        )

    issues = list_epics(beads_root=beads_root, repo_root=repo_root)
    actionable_cache: dict[str, bool] = {}

    def epic_has_actionable_changeset(epic_id: str) -> bool:
        cached = actionable_cache.get(epic_id)
        if cached is not None:
            return cached
        actionable = (
            next_changeset_fn(
                epic_id=epic_id,
                beads_root=beads_root,
                repo_root=repo_root,
                repo_slug=repo_slug,
                branch_pr=branch_pr,
                branch_pr_strategy=branch_pr_strategy,
                git_path=git_path,
            )
            is not None
        )
        actionable_cache[epic_id] = actionable
        return actionable

    hooked_epic = None
    if agent_bead_id:
        hooked_epic = resolve_hooked_epic(
            agent_bead_id, agent_id, beads_root=beads_root, repo_root=repo_root
        )
    elif dry_run:
        dry_run_log("Would create agent bead before checking for hooks.")
    assigned = filter_epics(issues, assignee=agent_id)
    assigned = sort_by_created_at(assigned)

    stale_assigned = stale_family_assigned_epics(issues, agent_id=agent_id)
    stale_assignee_by_epic = {
        str(issue.get("id")): str(issue.get("assignee"))
        for issue in stale_assigned
        if isinstance(issue.get("id"), str)
        and issue.get("id")
        and isinstance(issue.get("assignee"), str)
        and issue.get("assignee")
    }

    def stale_reassign_for_epic(epic_id: str) -> str | None:
        assignee = stale_assignee_by_epic.get(epic_id)
        if assignee:
            return assignee
        loaded = run_bd_json(["show", epic_id], beads_root=beads_root, cwd=repo_root)
        if not loaded:
            return None
        issue = loaded[0]
        existing_assignee = issue.get("assignee")
        if not isinstance(existing_assignee, str) or not existing_assignee:
            return None
        if existing_assignee == agent_id:
            return None
        if agent_family_id(existing_assignee) != agent_family_id(agent_id):
            return None
        if is_agent_session_active(existing_assignee):
            return None
        return existing_assignee

    def select_feedback_candidate(
        epic_ids: list[str],
    ) -> ReviewFeedbackSelection | None:
        feedback_candidates: list[ReviewFeedbackSelection] = []
        seen_epics: set[str] = set()
        for epic_id in epic_ids:
            if epic_id in seen_epics:
                continue
            seen_epics.add(epic_id)
            feedback_selection = select_review_feedback_changeset(
                epic_id=epic_id,
                repo_slug=repo_slug,
                beads_root=beads_root,
                repo_root=repo_root,
            )
            if feedback_selection is not None:
                feedback_candidates.append(feedback_selection)
        if not feedback_candidates:
            return None
        feedback_candidates.sort(
            key=lambda item: (
                parse_issue_time(item.feedback_at)
                or dt.datetime.max.replace(tzinfo=dt.timezone.utc)
            )
        )
        return feedback_candidates[0]

    def resume_feedback(selection: ReviewFeedbackSelection) -> StartupContractResult:
        emit(
            "Prioritizing review feedback: "
            f"{selection.changeset_id} ({selection.epic_id})"
        )
        log_debug(
            "startup selected review-feedback "
            f"changeset={selection.changeset_id} epic={selection.epic_id}"
        )
        if dry_run:
            dry_run_log(
                f"Would select review-feedback changeset {selection.changeset_id}."
            )
        return StartupContractResult(
            epic_id=selection.epic_id,
            changeset_id=selection.changeset_id,
            should_exit=False,
            reason="review_feedback",
            reassign_from=stale_reassign_for_epic(selection.epic_id),
        )

    if branch_pr and repo_slug and hooked_epic:
        hooked_feedback = select_feedback_candidate([hooked_epic])
        if hooked_feedback is not None:
            return resume_feedback(hooked_feedback)

    if hooked_epic and epic_has_actionable_changeset(hooked_epic):
        emit(f"Resuming hooked epic: {hooked_epic}")
        log_debug(f"startup resuming hooked epic={hooked_epic}")
        return StartupContractResult(
            epic_id=hooked_epic,
            changeset_id=None,
            should_exit=False,
            reason="hooked_epic",
        )
    if hooked_epic:
        emit(f"Hooked epic has no ready changesets: {hooked_epic}")
        log_debug(
            f"startup hooked epic has no actionable changesets epic={hooked_epic}"
        )

    if branch_pr and repo_slug:
        unhooked_epics: list[str] = []
        for issue in sort_by_created_at(issues):
            issue_id = issue.get("id")
            if not isinstance(issue_id, str) or not issue_id:
                continue
            if issue_id == hooked_epic:
                continue
            status = str(issue.get("status") or "")
            if not is_feedback_eligible_epic_status(status):
                continue
            labels = issue_labels(issue)
            if "at:draft" in labels:
                continue
            unhooked_epics.append(issue_id)
        feedback = select_feedback_candidate(unhooked_epics)
        if feedback is not None:
            return resume_feedback(feedback)
        global_feedback = select_global_review_feedback_changeset(
            repo_slug=repo_slug,
            beads_root=beads_root,
            repo_root=repo_root,
        )
        if global_feedback is not None:
            return resume_feedback(global_feedback)

    for issue in assigned:
        candidate = issue.get("id")
        if candidate and epic_has_actionable_changeset(str(candidate)):
            selected_epic = str(candidate)
            emit(f"Resuming assigned epic: {selected_epic}")
            log_debug(f"startup resuming assigned epic={selected_epic}")
            return StartupContractResult(
                epic_id=selected_epic,
                changeset_id=None,
                should_exit=False,
                reason="assigned_epic",
            )

    for issue in stale_assigned:
        candidate = issue.get("id")
        previous_assignee = issue.get("assignee")
        if (
            candidate
            and isinstance(previous_assignee, str)
            and previous_assignee
            and epic_has_actionable_changeset(str(candidate))
        ):
            selected_epic = str(candidate)
            emit(
                "Reclaiming stale epic assignment: "
                f"{selected_epic} (from {previous_assignee})"
            )
            log_warning(
                "startup reclaiming stale assignment "
                f"epic={selected_epic} previous_assignee={previous_assignee}"
            )
            return StartupContractResult(
                epic_id=selected_epic,
                changeset_id=None,
                should_exit=False,
                reason="stale_assignee_epic",
                reassign_from=previous_assignee,
            )

    if check_inbox_before_claim(agent_id, beads_root=beads_root, repo_root=repo_root):
        if dry_run:
            dry_run_log("Inbox has unread messages; would exit before claiming work.")
        return StartupContractResult(
            epic_id=None, changeset_id=None, should_exit=True, reason="inbox_blocked"
        )
    if handle_queue_before_claim(
        agent_id,
        beads_root=beads_root,
        repo_root=repo_root,
        queue_name=worker_queue_name,
        dry_run=dry_run,
        assume_yes=assume_yes,
    ):
        if dry_run:
            dry_run_log("Queue messages available; would exit before claiming work.")
        return StartupContractResult(
            epic_id=None, changeset_id=None, should_exit=True, reason="queue_blocked"
        )

    if mode == "auto":
        selected_epic = select_epic_auto(
            issues, agent_id=agent_id, is_actionable=epic_has_actionable_changeset
        )
    else:
        selected_epic = select_epic_prompt(
            issues,
            agent_id=agent_id,
            is_actionable=epic_has_actionable_changeset,
            assume_yes=assume_yes,
        )
    if selected_epic is None:
        selected_epic = select_epic_from_ready_changesets(
            issues=issues,
            is_actionable=epic_has_actionable_changeset,
            beads_root=beads_root,
            repo_root=repo_root,
        )
        if selected_epic:
            return StartupContractResult(
                epic_id=selected_epic,
                changeset_id=None,
                should_exit=False,
                reason="selected_ready_changeset",
            )

    if selected_epic is None:
        log_warning("startup found no eligible epics")
        send_needs_decision(
            agent_id=agent_id,
            mode=mode,
            issues=issues,
            beads_root=beads_root,
            repo_root=repo_root,
            dry_run=dry_run,
        )
        return StartupContractResult(
            epic_id=None,
            changeset_id=None,
            should_exit=True,
            reason="no_eligible_epics",
        )

    return StartupContractResult(
        epic_id=selected_epic,
        changeset_id=None,
        should_exit=False,
        reason="selected_auto" if mode == "auto" else "selected_prompt",
    )

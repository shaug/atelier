"""Worker startup contract and changeset selection pipeline."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ... import log as atelier_log
from .. import selection as worker_selection
from ..models import StartupContractResult
from ..review import ReviewFeedbackSelection


@dataclass(frozen=True)
class NextChangesetContext:
    epic_id: str
    repo_slug: str | None
    branch_pr: bool
    branch_pr_strategy: object
    git_path: str | None


class NextChangesetService(Protocol):
    """Typed next-changeset service boundary."""

    def show_issue(self, issue_id: str) -> dict[str, object] | None: ...

    def ready_changesets(self, *, epic_id: str) -> list[dict[str, object]]: ...

    def issue_labels(self, issue: dict[str, object]) -> set[str]: ...

    def is_changeset_ready(self, issue: dict[str, object]) -> bool: ...

    def changeset_waiting_on_review_or_signals(
        self,
        issue: dict[str, object],
        *,
        repo_slug: str | None,
        branch_pr: bool,
        branch_pr_strategy: object,
        git_path: str | None,
    ) -> bool: ...

    def is_changeset_recovery_candidate(
        self,
        issue: dict[str, object],
        *,
        repo_slug: str | None,
        branch_pr: bool,
        git_path: str | None,
    ) -> bool: ...

    def has_open_descendant_changesets(self, changeset_id: str) -> bool: ...

    def list_descendant_changesets(
        self,
        parent_id: str,
        *,
        include_closed: bool,
    ) -> list[dict[str, object]]: ...

    def is_changeset_in_progress(self, issue: dict[str, object]) -> bool: ...


def next_changeset_service(
    *, context: NextChangesetContext, service: NextChangesetService
) -> dict[str, object] | None:
    target = service.show_issue(context.epic_id)
    if target:
        issue = target
        issue_id = issue.get("id")
        labels = service.issue_labels(issue)
        if "at:draft" in labels:
            return None
        if (
            isinstance(issue_id, str)
            and issue_id == context.epic_id
            and "at:changeset" in labels
            and "cs:merged" not in labels
            and "cs:abandoned" not in labels
            and (
                (
                    service.is_changeset_ready(issue)
                    and not service.changeset_waiting_on_review_or_signals(
                        issue,
                        repo_slug=context.repo_slug,
                        branch_pr=context.branch_pr,
                        branch_pr_strategy=context.branch_pr_strategy,
                        git_path=context.git_path,
                    )
                )
                or service.is_changeset_recovery_candidate(
                    issue,
                    repo_slug=context.repo_slug,
                    branch_pr=context.branch_pr,
                    git_path=context.git_path,
                )
            )
        ):
            if not service.has_open_descendant_changesets(context.epic_id):
                return issue
        status = str(issue.get("status") or "").strip().lower()
        if (
            isinstance(issue_id, str)
            and issue_id == context.epic_id
            and "at:epic" in labels
            and "at:ready" in labels
            and status not in {"closed", "done"}
        ):
            descendants = service.list_descendant_changesets(
                context.epic_id,
                include_closed=True,
            )
            if not descendants:
                return issue

    changesets = service.ready_changesets(epic_id=context.epic_id)
    if not changesets:
        return None
    actionable = [
        issue
        for issue in changesets
        if service.is_changeset_ready(issue)
        and not service.changeset_waiting_on_review_or_signals(
            issue,
            repo_slug=context.repo_slug,
            branch_pr=context.branch_pr,
            branch_pr_strategy=context.branch_pr_strategy,
            git_path=context.git_path,
        )
    ]
    prioritized = sorted(
        actionable,
        key=lambda issue: (
            0 if service.is_changeset_in_progress(issue) else 1,
            str(issue.get("id") or ""),
        ),
    )
    for issue in prioritized:
        issue_id = issue.get("id")
        if isinstance(issue_id, str) and issue_id:
            if not service.has_open_descendant_changesets(issue_id):
                return issue
    return None


@dataclass(frozen=True)
class StartupContractContext:
    agent_id: str
    agent_bead_id: str | None
    beads_root: Path
    repo_root: Path
    mode: str
    explicit_epic_id: str | None
    queue_only: bool
    dry_run: bool
    assume_yes: bool
    repo_slug: str | None
    branch_pr: bool
    branch_pr_strategy: object
    git_path: str | None
    worker_queue_name: str
    excluded_epic_ids: tuple[str, ...] = ()


class StartupContractService(Protocol):
    """Typed startup-contract service dependency graph."""

    def handle_queue_before_claim(
        self,
        agent_id: str,
        *,
        queue_name: str,
        force_prompt: bool = False,
        dry_run: bool = False,
        assume_yes: bool = False,
    ) -> bool: ...

    def list_epics(self) -> list[dict[str, object]]: ...

    def next_changeset(
        self,
        *,
        epic_id: str,
        repo_slug: str | None,
        branch_pr: bool,
        branch_pr_strategy: object,
        git_path: str | None,
    ) -> dict[str, object] | None: ...

    def resolve_hooked_epic(self, agent_bead_id: str, agent_id: str) -> str | None: ...

    def stale_family_assigned_epics(
        self,
        issues: list[dict[str, object]],
        *,
        agent_id: str,
    ) -> list[dict[str, object]]: ...

    def select_review_feedback_changeset(
        self,
        *,
        epic_id: str,
        repo_slug: str | None,
    ) -> ReviewFeedbackSelection | None: ...

    def select_global_review_feedback_changeset(
        self,
        *,
        repo_slug: str | None,
    ) -> ReviewFeedbackSelection | None: ...

    def check_inbox_before_claim(self, agent_id: str) -> bool: ...

    def ready_changesets_global(self) -> list[dict[str, object]]: ...

    def select_epic_prompt(
        self,
        issues: list[dict[str, object]],
        *,
        agent_id: str,
        is_actionable: Callable[[str], bool],
        assume_yes: bool,
    ) -> str | None: ...

    def send_needs_decision(
        self,
        *,
        agent_id: str,
        mode: str,
        issues: list[dict[str, object]],
        dry_run: bool,
    ) -> None: ...

    def dry_run_log(self, message: str) -> None: ...

    def emit(self, message: str) -> None: ...

    def die(self, message: str) -> None: ...


def run_startup_contract_service(
    *, context: StartupContractContext, service: StartupContractService
) -> StartupContractResult:
    """Typed startup contract service entrypoint."""
    agent_id = context.agent_id
    agent_bead_id = context.agent_bead_id
    mode = context.mode
    explicit_epic_id = context.explicit_epic_id
    queue_only = context.queue_only
    dry_run = context.dry_run
    assume_yes = context.assume_yes
    repo_slug = context.repo_slug
    branch_pr = context.branch_pr
    branch_pr_strategy = context.branch_pr_strategy
    git_path = context.git_path
    worker_queue_name = context.worker_queue_name
    excluded_epics = {
        str(epic_id).strip() for epic_id in context.excluded_epic_ids if str(epic_id).strip()
    }

    """Apply startup_contract skill ordering to select the next epic."""
    if explicit_epic_id is not None:
        selected_epic = str(explicit_epic_id).strip()
        if not selected_epic:
            service.die("epic id must not be empty")
        return StartupContractResult(
            epic_id=selected_epic,
            changeset_id=None,
            should_exit=False,
            reason="explicit_epic",
        )

    if queue_only:
        service.handle_queue_before_claim(
            agent_id,
            queue_name=worker_queue_name,
            force_prompt=True,
            dry_run=dry_run,
            assume_yes=assume_yes,
        )
        if dry_run:
            service.dry_run_log("Queue-only run would exit after handling queue.")
        return StartupContractResult(
            epic_id=None, changeset_id=None, should_exit=True, reason="queue_only"
        )

    issues = service.list_epics()
    actionable_cache: dict[str, bool] = {}

    def epic_has_actionable_changeset(epic_id: str) -> bool:
        cached = actionable_cache.get(epic_id)
        if cached is not None:
            return cached
        actionable = (
            service.next_changeset(
                epic_id=epic_id,
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
        hooked_epic = service.resolve_hooked_epic(agent_bead_id, agent_id)
    elif dry_run:
        service.dry_run_log("Would create agent bead before checking for hooks.")
    assigned = worker_selection.filter_epics(
        issues, assignee=agent_id, allow_hooked=True, skip_draft=True
    )
    assigned = worker_selection.sort_by_created_at(assigned)

    stale_assigned = service.stale_family_assigned_epics(issues, agent_id=agent_id)
    stale_assignee_by_epic = {
        str(issue.get("id")): str(issue.get("assignee"))
        for issue in stale_assigned
        if isinstance(issue.get("id"), str)
        and issue.get("id")
        and isinstance(issue.get("assignee"), str)
        and issue.get("assignee")
    }

    def stale_reassign_for_epic(epic_id: str) -> str | None:
        return stale_assignee_by_epic.get(epic_id)

    issues_by_id = {
        str(issue.get("id")): issue
        for issue in issues
        if isinstance(issue.get("id"), str) and issue.get("id")
    }

    def is_excluded(epic_id: str, *, stage: str) -> bool:
        if epic_id in excluded_epics:
            atelier_log.debug(
                f"startup skipping {stage} epic={epic_id} reason=claim_conflict_excluded"
            )
            return True
        return False

    def is_claimable(epic_id: str, *, stage: str) -> bool:
        issue = issues_by_id.get(epic_id)
        if issue is None:
            atelier_log.debug(f"startup skipping {stage} epic={epic_id} reason=unknown_epic")
            return False
        labels = worker_selection.issue_labels(issue)
        if "at:draft" in labels:
            atelier_log.debug(f"startup skipping {stage} epic={epic_id} reason=draft")
            return False
        status = str(issue.get("status") or "")
        if status and not worker_selection.is_eligible_status(status, allow_hooked=True):
            atelier_log.debug(
                f"startup skipping {stage} epic={epic_id} reason=ineligible_status status={status}"
            )
            return False
        assignee = issue.get("assignee")
        if isinstance(assignee, str) and assignee.strip():
            if assignee == agent_id:
                return True
            if stale_reassign_for_epic(epic_id):
                return True
            atelier_log.debug(
                "startup skipping "
                f"{stage} epic={epic_id} reason=active_assignee assignee={assignee}"
            )
            return False
        return True

    def select_feedback_candidate(
        epic_ids: list[str],
    ) -> ReviewFeedbackSelection | None:
        feedback_candidates: list[ReviewFeedbackSelection] = []
        seen_epics: set[str] = set()
        for epic_id in epic_ids:
            if epic_id in seen_epics:
                continue
            seen_epics.add(epic_id)
            if is_excluded(epic_id, stage="review-feedback"):
                continue
            if not is_claimable(epic_id, stage="review-feedback"):
                continue
            feedback_selection = service.select_review_feedback_changeset(
                epic_id=epic_id,
                repo_slug=repo_slug,
            )
            if feedback_selection is not None:
                feedback_candidates.append(feedback_selection)
        if not feedback_candidates:
            return None
        feedback_candidates.sort(
            key=lambda item: (
                worker_selection.parse_issue_time(item.feedback_at)
                or dt.datetime.max.replace(tzinfo=dt.timezone.utc)
            )
        )
        return feedback_candidates[0]

    def resume_feedback(selection: ReviewFeedbackSelection) -> StartupContractResult:
        service.emit(
            f"Prioritizing review feedback: {selection.changeset_id} ({selection.epic_id})"
        )
        atelier_log.debug(
            "startup selected review-feedback "
            f"changeset={selection.changeset_id} epic={selection.epic_id}"
        )
        if dry_run:
            service.dry_run_log(f"Would select review-feedback changeset {selection.changeset_id}.")
        return StartupContractResult(
            epic_id=selection.epic_id,
            changeset_id=selection.changeset_id,
            should_exit=False,
            reason="review_feedback",
            reassign_from=stale_reassign_for_epic(selection.epic_id),
        )

    if branch_pr and repo_slug and hooked_epic:
        if is_excluded(hooked_epic, stage="hooked"):
            hooked_epic = None
        if hooked_epic:
            hooked_feedback = select_feedback_candidate([hooked_epic])
            if hooked_feedback is not None:
                return resume_feedback(hooked_feedback)

    if (
        hooked_epic
        and not is_excluded(hooked_epic, stage="hooked")
        and epic_has_actionable_changeset(hooked_epic)
    ):
        service.emit(f"Resuming hooked epic: {hooked_epic}")
        atelier_log.debug(f"startup resuming hooked epic={hooked_epic}")
        return StartupContractResult(
            epic_id=hooked_epic,
            changeset_id=None,
            should_exit=False,
            reason="hooked_epic",
        )
    if hooked_epic:
        service.emit(f"Hooked epic has no ready changesets: {hooked_epic}")
        atelier_log.debug(f"startup hooked epic has no actionable changesets epic={hooked_epic}")

    if branch_pr and repo_slug:
        unhooked_epics: list[str] = []
        for issue in worker_selection.sort_by_created_at(issues):
            issue_id = issue.get("id")
            if not isinstance(issue_id, str) or not issue_id:
                continue
            if issue_id == hooked_epic:
                continue
            if is_excluded(issue_id, stage="review-feedback"):
                continue
            status = str(issue.get("status") or "")
            if str(status).strip().lower() not in {"open", "ready", "in_progress"}:
                continue
            labels = worker_selection.issue_labels(issue)
            if "at:draft" in labels:
                continue
            if not is_claimable(issue_id, stage="review-feedback"):
                continue
            unhooked_epics.append(issue_id)
        feedback = select_feedback_candidate(unhooked_epics)
        if feedback is not None:
            return resume_feedback(feedback)
        global_feedback = service.select_global_review_feedback_changeset(repo_slug=repo_slug)
        if global_feedback is not None and not is_excluded(
            global_feedback.epic_id, stage="global-review-feedback"
        ):
            if not is_claimable(global_feedback.epic_id, stage="global-review-feedback"):
                global_feedback = None
        if global_feedback is not None:
            return resume_feedback(global_feedback)

    for issue in assigned:
        candidate = issue.get("id")
        if (
            candidate
            and not is_excluded(str(candidate), stage="assigned")
            and epic_has_actionable_changeset(str(candidate))
        ):
            selected_epic = str(candidate)
            service.emit(f"Resuming assigned epic: {selected_epic}")
            atelier_log.debug(f"startup resuming assigned epic={selected_epic}")
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
            and not is_excluded(str(candidate), stage="stale")
            and epic_has_actionable_changeset(str(candidate))
        ):
            selected_epic = str(candidate)
            service.emit(
                f"Reclaiming stale epic assignment: {selected_epic} (from {previous_assignee})"
            )
            atelier_log.warning(
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

    if service.check_inbox_before_claim(agent_id):
        if dry_run:
            service.dry_run_log("Inbox has unread messages; would exit before claiming work.")
        return StartupContractResult(
            epic_id=None, changeset_id=None, should_exit=True, reason="inbox_blocked"
        )
    if service.handle_queue_before_claim(
        agent_id,
        queue_name=worker_queue_name,
        dry_run=dry_run,
        assume_yes=assume_yes,
    ):
        if dry_run:
            service.dry_run_log("Queue messages available; would exit before claiming work.")
        return StartupContractResult(
            epic_id=None, changeset_id=None, should_exit=True, reason="queue_blocked"
        )

    if mode == "auto":
        selected_epic = worker_selection.select_epic_auto(
            [
                issue
                for issue in issues
                if not is_excluded(str(issue.get("id") or ""), stage="auto")
            ],
            agent_id=agent_id,
            is_actionable=epic_has_actionable_changeset,
        )
    else:
        selected_epic = service.select_epic_prompt(
            [
                issue
                for issue in issues
                if not is_excluded(str(issue.get("id") or ""), stage="prompt")
            ],
            agent_id=agent_id,
            is_actionable=epic_has_actionable_changeset,
            assume_yes=assume_yes,
        )
    if selected_epic is None:
        selected_epic = worker_selection.select_epic_from_ready_changesets(
            issues=issues,
            ready_changesets=service.ready_changesets_global(),
            is_actionable=epic_has_actionable_changeset,
        )
        if selected_epic:
            return StartupContractResult(
                epic_id=selected_epic,
                changeset_id=None,
                should_exit=False,
                reason="selected_ready_changeset",
            )

    if selected_epic is None:
        atelier_log.warning("startup found no eligible epics")
        service.send_needs_decision(
            agent_id=agent_id,
            mode=mode,
            issues=issues,
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

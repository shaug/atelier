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
from ..models_boundary import parse_issue_boundary
from ..review import MergeConflictSelection, ReviewFeedbackSelection

_TERMINAL_STATUSES = {"closed", "done"}
_TERMINAL_CHANGESET_LABELS = {"cs:merged", "cs:abandoned"}


@dataclass(frozen=True)
class NextChangesetContext:
    epic_id: str
    repo_slug: str | None
    branch_pr: bool
    branch_pr_strategy: object
    git_path: str | None
    resume_review: bool = False


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

    def changeset_has_review_handoff_signal(
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


def _issue_id(issue: dict[str, object]) -> str | None:
    issue_id = issue.get("id")
    if not isinstance(issue_id, str):
        return None
    cleaned = issue_id.strip()
    return cleaned or None


def _issue_parent_id(issue: dict[str, object]) -> str | None:
    try:
        boundary = parse_issue_boundary(issue, source="startup_contract:issue_parent_id")
    except ValueError:
        return None
    return boundary.parent_id


def _is_standalone_changeset_identity(issue: dict[str, object]) -> bool:
    labels = worker_selection.issue_labels(issue)
    if "at:changeset" not in labels or "at:epic" in labels:
        return False
    return _issue_parent_id(issue) is None


def _is_executable_epic_identity(issue: dict[str, object]) -> bool:
    labels = worker_selection.issue_labels(issue)
    return "at:epic" in labels or _is_standalone_changeset_identity(issue)


def _is_terminal(issue: dict[str, object]) -> bool:
    status = str(issue.get("status") or "").strip().lower()
    return status in _TERMINAL_STATUSES


def _is_terminal_explicit_issue(issue: dict[str, object]) -> bool:
    status = str(issue.get("status") or "").strip().lower()
    if status in _TERMINAL_STATUSES:
        return True
    labels = worker_selection.issue_labels(issue)
    return bool(_TERMINAL_CHANGESET_LABELS.intersection(labels))


def _dependency_ids(issue: dict[str, object]) -> tuple[str, ...] | None:
    try:
        boundary = parse_issue_boundary(issue, source="next_changeset_service:dependency_ids")
    except ValueError:
        return None
    return boundary.dependency_ids


def _dependencies_satisfied(
    *,
    issue: dict[str, object],
    epic_changesets_by_id: dict[str, dict[str, object]],
    dependency_cache: dict[str, dict[str, object] | None],
    context: NextChangesetContext,
    service: NextChangesetService,
) -> bool:
    del context
    dependency_ids = _dependency_ids(issue)
    if dependency_ids is None:
        return False
    for dependency_id in dependency_ids:
        blocker_issue = epic_changesets_by_id.get(dependency_id)
        if blocker_issue is None:
            blocker_issue = dependency_cache.get(dependency_id)
            if blocker_issue is None and dependency_id not in dependency_cache:
                blocker_issue = service.show_issue(dependency_id)
                dependency_cache[dependency_id] = blocker_issue
        if blocker_issue is None:
            return False
        if _is_terminal(blocker_issue):
            continue
        return False
    return True


def next_changeset_service(
    *, context: NextChangesetContext, service: NextChangesetService
) -> dict[str, object] | None:
    def review_waiting(issue: dict[str, object]) -> bool:
        return service.changeset_waiting_on_review_or_signals(
            issue,
            repo_slug=context.repo_slug,
            branch_pr=context.branch_pr,
            branch_pr_strategy=context.branch_pr_strategy,
            git_path=context.git_path,
        )

    def review_resume_allowed(issue: dict[str, object]) -> bool:
        if not context.resume_review:
            return False
        return service.changeset_has_review_handoff_signal(
            issue,
            repo_slug=context.repo_slug,
            branch_pr=context.branch_pr,
            git_path=context.git_path,
        )

    target = service.show_issue(context.epic_id)
    if target:
        issue = target
        issue_id = issue.get("id")
        labels = service.issue_labels(issue)
        if "at:draft" in labels or "at:ready" not in labels:
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
                    and (not review_waiting(issue) or review_resume_allowed(issue))
                )
                or service.is_changeset_recovery_candidate(
                    issue,
                    repo_slug=context.repo_slug,
                    branch_pr=context.branch_pr,
                    git_path=context.git_path,
                )
            )
        ):
            descendants = service.list_descendant_changesets(
                context.epic_id,
                include_closed=True,
            )
            descendants_by_id = {
                descendant_id: descendant
                for descendant in descendants
                if (descendant_id := _issue_id(descendant)) is not None
            }
            if not _dependencies_satisfied(
                issue=issue,
                epic_changesets_by_id=descendants_by_id,
                dependency_cache={},
                context=context,
                service=service,
            ):
                return None
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

    descendants = service.list_descendant_changesets(context.epic_id, include_closed=False)
    descendants_by_id = {
        issue_id: issue for issue in descendants if (issue_id := _issue_id(issue)) is not None
    }
    changesets: list[dict[str, object]] = []
    changeset_ids: set[str] = set()
    for issue in service.ready_changesets(epic_id=context.epic_id):
        issue_id = _issue_id(issue)
        if issue_id is None or issue_id in changeset_ids:
            continue
        canonical_issue = descendants_by_id.get(issue_id)
        if canonical_issue is None:
            loaded_issue = service.show_issue(issue_id)
            if loaded_issue is not None and _issue_id(loaded_issue) == issue_id:
                canonical_issue = loaded_issue
        if canonical_issue is None:
            canonical_issue = issue
        changesets.append(canonical_issue)
        changeset_ids.add(issue_id)
    dependency_cache: dict[str, dict[str, object] | None] = {}
    for issue in descendants:
        issue_id = _issue_id(issue)
        if issue_id is None or issue_id in changeset_ids:
            continue
        if not service.is_changeset_ready(issue):
            continue
        if not _dependencies_satisfied(
            issue=issue,
            epic_changesets_by_id=descendants_by_id,
            dependency_cache=dependency_cache,
            context=context,
            service=service,
        ):
            continue
        changesets.append(issue)
        changeset_ids.add(issue_id)
    if not changesets:
        return None
    actionable = [
        issue
        for issue in changesets
        if service.is_changeset_ready(issue)
        and _dependencies_satisfied(
            issue=issue,
            epic_changesets_by_id=descendants_by_id,
            dependency_cache=dependency_cache,
            context=context,
            service=service,
        )
        and (not review_waiting(issue) or review_resume_allowed(issue))
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
    resume_review: bool = False
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

    def show_issue(self, issue_id: str) -> dict[str, object] | None: ...

    def next_changeset(
        self,
        *,
        epic_id: str,
        repo_slug: str | None,
        branch_pr: bool,
        branch_pr_strategy: object,
        git_path: str | None,
        resume_review: bool,
    ) -> dict[str, object] | None: ...

    def resolve_hooked_epic(self, agent_bead_id: str, agent_id: str) -> str | None: ...

    def stale_family_assigned_epics(
        self,
        issues: list[dict[str, object]],
        *,
        agent_id: str,
    ) -> list[dict[str, object]]: ...

    def select_conflicted_changeset(
        self,
        *,
        epic_id: str,
        repo_slug: str | None,
    ) -> MergeConflictSelection | None: ...

    def select_global_conflicted_changeset(
        self,
        *,
        repo_slug: str | None,
    ) -> MergeConflictSelection | None: ...

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
    resume_review = context.resume_review
    excluded_epics = {
        str(epic_id).strip() for epic_id in context.excluded_epic_ids if str(epic_id).strip()
    }

    """Apply startup-contract skill ordering to select the next epic."""
    selected_epic: str | None = None
    if explicit_epic_id is not None:
        selected_epic = str(explicit_epic_id).strip()
        if not selected_epic:
            service.die("epic id must not be empty")
        explicit_issue = service.show_issue(selected_epic)
        if explicit_issue is None:
            service.emit(
                f"Explicit epic {selected_epic} was not found; run without an epic id to "
                "select ready work."
            )
            return StartupContractResult(
                epic_id=selected_epic,
                changeset_id=None,
                should_exit=True,
                reason="explicit_epic_not_found",
            )
        if not _is_executable_epic_identity(explicit_issue):
            service.emit(
                f"Explicit epic {selected_epic} is not executable work; run without an epic id "
                "to select a ready epic."
            )
            return StartupContractResult(
                epic_id=selected_epic,
                changeset_id=None,
                should_exit=True,
                reason="explicit_epic_not_executable",
            )
        labels = worker_selection.issue_labels(explicit_issue)
        status = str(explicit_issue.get("status") or "").strip().lower()
        if _is_terminal_explicit_issue(explicit_issue):
            service.emit(
                f"Explicit epic {selected_epic} is completed; run without an epic id to "
                "select new ready work."
            )
            return StartupContractResult(
                epic_id=selected_epic,
                changeset_id=None,
                should_exit=True,
                reason="explicit_epic_completed",
            )
        if "at:draft" in labels or "at:ready" not in labels:
            service.emit(
                f"Explicit epic {selected_epic} is not ready; mark it at:ready or run "
                "without an epic id."
            )
            return StartupContractResult(
                epic_id=selected_epic,
                changeset_id=None,
                should_exit=True,
                reason="explicit_epic_not_ready",
            )
        assignee = explicit_issue.get("assignee")
        if isinstance(assignee, str):
            assignee = assignee.strip()
        else:
            assignee = ""
        if assignee and assignee != agent_id:
            service.emit(
                f"Explicit epic {selected_epic} is already assigned/hooked by {assignee}; "
                "release the stale lock or rerun without an epic id."
            )
            return StartupContractResult(
                epic_id=selected_epic,
                changeset_id=None,
                should_exit=True,
                reason="explicit_epic_assigned",
            )
        if branch_pr and repo_slug:
            explicit_conflict = service.select_conflicted_changeset(
                epic_id=selected_epic,
                repo_slug=repo_slug,
            )
            if explicit_conflict is not None:
                return StartupContractResult(
                    epic_id=explicit_conflict.epic_id,
                    changeset_id=explicit_conflict.changeset_id,
                    should_exit=False,
                    reason="merge_conflict",
                )
            explicit_feedback = service.select_review_feedback_changeset(
                epic_id=selected_epic,
                repo_slug=repo_slug,
            )
            if explicit_feedback is not None:
                return StartupContractResult(
                    epic_id=explicit_feedback.epic_id,
                    changeset_id=explicit_feedback.changeset_id,
                    should_exit=False,
                    reason="review_feedback",
                )
        explicit_next_changeset = service.next_changeset(
            epic_id=selected_epic,
            repo_slug=repo_slug,
            branch_pr=branch_pr,
            branch_pr_strategy=branch_pr_strategy,
            git_path=git_path,
            resume_review=resume_review,
        )
        if explicit_next_changeset is None:
            if status in {"in_progress", "hooked"}:
                service.emit(
                    f"Explicit epic {selected_epic} is in progress and waiting on review; "
                    "resume review feedback and rerun without an epic id."
                )
                return StartupContractResult(
                    epic_id=selected_epic,
                    changeset_id=None,
                    should_exit=True,
                    reason="explicit_epic_review_pending",
                )
            service.emit(
                f"Explicit epic {selected_epic} has no actionable ready changesets; run "
                "without an epic id to select available work."
            )
            return StartupContractResult(
                epic_id=selected_epic,
                changeset_id=None,
                should_exit=True,
                reason="explicit_epic_not_actionable",
            )
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
    review_feedback_ownership_blockers: set[str] = set()

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
                resume_review=resume_review and explicit_epic_id is not None,
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

    def load_claimable_issue(epic_id: str, *, stage: str) -> dict[str, object] | None:
        issue = issues_by_id.get(epic_id)
        if issue is None:
            issue = service.show_issue(epic_id)
            if issue is None:
                atelier_log.debug(f"startup skipping {stage} epic={epic_id} reason=unknown_epic")
                return None
            loaded_id = _issue_id(issue)
            if loaded_id != epic_id:
                atelier_log.debug(
                    "startup skipping "
                    f"{stage} epic={epic_id} reason=identity_mismatch loaded={loaded_id}"
                )
                return None
            if not _is_executable_epic_identity(issue):
                atelier_log.debug(
                    f"startup skipping {stage} epic={epic_id} reason=non_executable_identity"
                )
                return None
            issues_by_id[epic_id] = issue
        return issue

    def is_excluded(epic_id: str, *, stage: str) -> bool:
        if epic_id in excluded_epics:
            atelier_log.debug(
                f"startup skipping {stage} epic={epic_id} reason=claim_conflict_excluded"
            )
            return True
        return False

    def is_claimable(epic_id: str, *, stage: str) -> bool:
        issue = load_claimable_issue(epic_id, stage=stage)
        if issue is None:
            return False
        labels = worker_selection.issue_labels(issue)
        if "at:draft" in labels:
            atelier_log.debug(f"startup skipping {stage} epic={epic_id} reason=draft")
            return False
        if "at:ready" not in labels:
            atelier_log.debug(f"startup skipping {stage} epic={epic_id} reason=not_ready")
            return False
        status = str(issue.get("status") or "")
        if status and not worker_selection.is_eligible_status(status, allow_hooked=True):
            atelier_log.debug(
                f"startup skipping {stage} epic={epic_id} reason=ineligible_status status={status}"
            )
            return False
        assignee = issue.get("assignee")
        if isinstance(assignee, str) and assignee.strip():
            if (
                "review-feedback" in stage
                and worker_selection.is_planner_agent_id(assignee)
                and epic_id not in review_feedback_ownership_blockers
            ):
                review_feedback_ownership_blockers.add(epic_id)
                service.emit(
                    "Skipping review-feedback candidate due to ownership policy: "
                    f"{epic_id} is assigned to planner ({assignee}). "
                    "Reassign to a worker and rerun startup."
                )
                atelier_log.warning(
                    "startup review-feedback blocker "
                    f"epic={epic_id} reason=planner_owned assignee={assignee}"
                )
                return False
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

    def select_conflict_candidate(
        epic_ids: list[str],
    ) -> MergeConflictSelection | None:
        conflict_candidates: list[MergeConflictSelection] = []
        seen_epics: set[str] = set()
        for epic_id in epic_ids:
            if epic_id in seen_epics:
                continue
            seen_epics.add(epic_id)
            if is_excluded(epic_id, stage="merge-conflict"):
                continue
            selection = service.select_conflicted_changeset(
                epic_id=epic_id,
                repo_slug=repo_slug,
            )
            if selection is not None:
                conflict_candidates.append(selection)
        if not conflict_candidates:
            return None
        conflict_candidates.sort(
            key=lambda item: (
                worker_selection.parse_issue_time(item.observed_at)
                or dt.datetime.max.replace(tzinfo=dt.timezone.utc)
            )
        )
        return conflict_candidates[0]

    def resume_conflict(selection: MergeConflictSelection) -> StartupContractResult:
        service.emit(
            "Prioritizing merge-conflict resolution: "
            f"{selection.changeset_id} ({selection.epic_id})"
        )
        atelier_log.debug(
            "startup selected merge-conflict "
            f"changeset={selection.changeset_id} epic={selection.epic_id}"
        )
        if dry_run:
            service.dry_run_log(f"Would select merge-conflict changeset {selection.changeset_id}.")
        return StartupContractResult(
            epic_id=selection.epic_id,
            changeset_id=selection.changeset_id,
            should_exit=False,
            reason="merge_conflict",
            reassign_from=stale_reassign_for_epic(selection.epic_id),
        )

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
            hooked_conflict = select_conflict_candidate([hooked_epic])
            if hooked_conflict is not None:
                return resume_conflict(hooked_conflict)
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
            if worker_selection.has_planner_executable_assignee(issue):
                assignee = str(issue.get("assignee") or "").strip() or "planner"
                if issue_id not in review_feedback_ownership_blockers:
                    review_feedback_ownership_blockers.add(issue_id)
                    service.emit(
                        "Skipping review-feedback candidate due to ownership policy: "
                        f"{issue_id} is assigned to planner ({assignee}). "
                        "Reassign to a worker and rerun startup."
                    )
                    atelier_log.warning(
                        "startup review-feedback blocker "
                        f"epic={issue_id} reason=planner_owned assignee={assignee}"
                    )
                continue
            if is_excluded(issue_id, stage="review-feedback"):
                continue
            status = str(issue.get("status") or "")
            if str(status).strip().lower() not in {"open", "ready", "in_progress"}:
                continue
            labels = worker_selection.issue_labels(issue)
            if "at:draft" in labels or "at:ready" not in labels:
                continue
            if not is_claimable(issue_id, stage="review-feedback"):
                continue
            unhooked_epics.append(issue_id)
        conflict = select_conflict_candidate(unhooked_epics)
        if conflict is not None:
            return resume_conflict(conflict)
        global_conflict = service.select_global_conflicted_changeset(repo_slug=repo_slug)
        if global_conflict is not None and is_excluded(
            global_conflict.epic_id, stage="global-merge-conflict"
        ):
            global_conflict = None
        if global_conflict is not None:
            return resume_conflict(global_conflict)
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
        if review_feedback_ownership_blockers:
            blocked = ", ".join(sorted(review_feedback_ownership_blockers))
            service.emit(f"Review-feedback ownership-policy blockers: {blocked}")
            service.emit(
                "Remediation: reassign blocked epic(s) from planner to a worker, "
                "then rerun startup."
            )
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

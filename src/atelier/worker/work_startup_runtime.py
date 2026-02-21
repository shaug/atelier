"""Worker startup and prompt helper functions for `atelier work`."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from .. import agent_home, beads, pr_strategy, work_feedback
from ..io import die, prompt, say, select
from ..work_feedback import ReviewFeedbackSnapshot
from ..worker import prompts as worker_prompts
from ..worker import queueing as worker_queueing
from ..worker import review as worker_review
from ..worker import selection as worker_selection
from ..worker.models import StartupContractResult
from ..worker.session import startup as worker_startup
from . import work_finalization_runtime as _work_finalization_runtime
from . import work_runtime_common as _work_runtime_common
from .work_finalization_runtime import (
    _changeset_waiting_on_review_or_signals,
    _has_open_descendant_changesets,
    _is_changeset_in_progress,
    _is_changeset_ready,
    _is_changeset_recovery_candidate,
    _resolve_epic_id_for_changeset,
)
from .work_runtime_common import (
    _dry_run_log,
    _filter_epics,
    _issue_labels,
)

ReviewFeedbackSelection = worker_review.ReviewFeedbackSelection

_WORKER_QUEUE_NAME = "worker"


def __getattr__(name: str) -> object:
    """Compatibility fallback for legacy callers importing this module directly.

    Worker runtime internals were split across startup/finalization/common
    modules. Some clients still resolve helpers from this module; forward
    unknown attributes to newer modules to avoid runtime AttributeError.
    """
    for module in (_work_finalization_runtime, _work_runtime_common):
        if hasattr(module, name):
            return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


class _NextChangesetService(worker_startup.NextChangesetService):
    """Concrete next-changeset service implementation for worker startup."""

    def __init__(self, *, beads_root: Path, repo_root: Path) -> None:
        self._beads_root = beads_root
        self._repo_root = repo_root

    def show_issue(self, issue_id: str) -> dict[str, object] | None:
        issues = beads.run_bd_json(
            ["show", issue_id], beads_root=self._beads_root, cwd=self._repo_root
        )
        return issues[0] if issues else None

    def ready_changesets(self, *, epic_id: str) -> list[dict[str, object]]:
        return beads.run_bd_json(
            ["ready", "--parent", epic_id, "--label", "at:changeset"],
            beads_root=self._beads_root,
            cwd=self._repo_root,
        )

    def issue_labels(self, issue: dict[str, object]) -> set[str]:
        return _issue_labels(issue)

    def is_changeset_ready(self, issue: dict[str, object]) -> bool:
        return _is_changeset_ready(issue)

    def changeset_waiting_on_review_or_signals(
        self,
        issue: dict[str, object],
        *,
        repo_slug: str | None,
        branch_pr: bool,
        branch_pr_strategy: object,
        git_path: str | None,
    ) -> bool:
        return _changeset_waiting_on_review_or_signals(
            issue,
            repo_slug=repo_slug,
            repo_root=self._repo_root,
            branch_pr=branch_pr,
            branch_pr_strategy=branch_pr_strategy,
            git_path=git_path,
        )

    def is_changeset_recovery_candidate(
        self,
        issue: dict[str, object],
        *,
        repo_slug: str | None,
        branch_pr: bool,
        git_path: str | None,
    ) -> bool:
        return _is_changeset_recovery_candidate(
            issue,
            repo_slug=repo_slug,
            repo_root=self._repo_root,
            branch_pr=branch_pr,
            git_path=git_path,
        )

    def has_open_descendant_changesets(self, changeset_id: str) -> bool:
        return _has_open_descendant_changesets(
            changeset_id, beads_root=self._beads_root, repo_root=self._repo_root
        )

    def list_descendant_changesets(
        self,
        parent_id: str,
        *,
        include_closed: bool,
    ) -> list[dict[str, object]]:
        return beads.list_descendant_changesets(
            parent_id,
            beads_root=self._beads_root,
            cwd=self._repo_root,
            include_closed=include_closed,
        )

    def is_changeset_in_progress(self, issue: dict[str, object]) -> bool:
        return _is_changeset_in_progress(issue)


def _next_changeset(
    *,
    epic_id: str,
    beads_root: Path,
    repo_root: Path,
    repo_slug: str | None = None,
    branch_pr: bool = True,
    branch_pr_strategy: object = pr_strategy.PR_STRATEGY_DEFAULT,
    git_path: str | None = None,
) -> dict[str, object] | None:
    context = worker_startup.NextChangesetContext(
        epic_id=epic_id,
        repo_slug=repo_slug,
        branch_pr=branch_pr,
        branch_pr_strategy=branch_pr_strategy,
        git_path=git_path,
    )
    service = _NextChangesetService(beads_root=beads_root, repo_root=repo_root)
    return worker_startup.next_changeset_service(context=context, service=service)


def _persist_review_feedback_cursor(
    *,
    changeset_id: str,
    issue: dict[str, object],
    repo_slug: str | None,
    beads_root: Path,
    repo_root: Path,
) -> None:
    work_feedback.persist_review_feedback_cursor(
        changeset_id=changeset_id,
        issue=issue,
        repo_slug=repo_slug,
        beads_root=beads_root,
        repo_root=repo_root,
    )


def _capture_review_feedback_snapshot(
    *,
    issue: dict[str, object],
    repo_slug: str | None,
    repo_root: Path,
    git_path: str | None,
) -> ReviewFeedbackSnapshot:
    return work_feedback.capture_review_feedback_snapshot(
        issue=issue,
        repo_slug=repo_slug,
        repo_root=repo_root,
        git_path=git_path,
    )


def _review_feedback_progressed(
    before: ReviewFeedbackSnapshot, after: ReviewFeedbackSnapshot
) -> bool:
    return work_feedback.review_feedback_progressed(before, after)


def _select_review_feedback_changeset(
    *,
    epic_id: str,
    repo_slug: str | None,
    beads_root: Path,
    repo_root: Path,
) -> ReviewFeedbackSelection | None:
    return worker_review.select_review_feedback_changeset(
        epic_id=epic_id,
        repo_slug=repo_slug,
        beads_root=beads_root,
        repo_root=repo_root,
    )


def _select_global_review_feedback_changeset(
    *,
    repo_slug: str | None,
    beads_root: Path,
    repo_root: Path,
) -> ReviewFeedbackSelection | None:
    return worker_review.select_global_review_feedback_changeset(
        repo_slug=repo_slug,
        beads_root=beads_root,
        repo_root=repo_root,
        resolve_epic_id_for_changeset=(
            lambda issue: (
                _resolve_epic_id_for_changeset(issue, beads_root=beads_root, repo_root=repo_root)
                or str(issue.get("id") or "")
                or None
            )
        ),
    )


def _resolve_hooked_epic(
    agent_bead_id: str,
    agent_id: str,
    *,
    beads_root: Path,
    repo_root: Path,
) -> str | None:
    hook_id = beads.get_agent_hook(agent_bead_id, beads_root=beads_root, cwd=repo_root)
    if not hook_id:
        return None
    issues = beads.run_bd_json(["show", hook_id], beads_root=beads_root, cwd=repo_root)
    if not issues:
        return None
    epic = issues[0]
    status = str(epic.get("status") or "").lower()
    if status in {"closed", "done"}:
        return None
    assignee = epic.get("assignee")
    if assignee and assignee != agent_id:
        return None
    if assignee != agent_id:
        return None
    return hook_id


def _worker_opening_prompt(
    *,
    project_enlistment: str,
    workspace_branch: str,
    epic_id: str,
    changeset_id: str,
    changeset_title: str,
    review_feedback: bool = False,
    review_pr_url: str | None = None,
) -> str:
    return worker_prompts.worker_opening_prompt(
        project_enlistment=project_enlistment,
        workspace_branch=workspace_branch,
        epic_id=epic_id,
        changeset_id=changeset_id,
        changeset_title=changeset_title,
        review_feedback=review_feedback,
        review_pr_url=review_pr_url,
    )


def _check_inbox_before_claim(agent_id: str, *, beads_root: Path, repo_root: Path) -> bool:
    return worker_queueing.check_inbox_before_claim(
        agent_id,
        beads_root=beads_root,
        repo_root=repo_root,
        emit=say,
    )


def _handle_queue_before_claim(
    agent_id: str,
    *,
    beads_root: Path,
    repo_root: Path,
    queue_name: str | None = _WORKER_QUEUE_NAME,
    force_prompt: bool = False,
    dry_run: bool = False,
    assume_yes: bool = False,
) -> bool:
    return worker_queueing.handle_queue_before_claim(
        agent_id,
        beads_root=beads_root,
        repo_root=repo_root,
        queue_name=queue_name,
        force_prompt=force_prompt,
        dry_run=dry_run,
        assume_yes=assume_yes,
        emit=say,
        prompt_fn=prompt,
        die_fn=die,
        dry_run_log=_dry_run_log,
    )


class _StartupContractService(worker_startup.StartupContractService):
    """Concrete startup-contract service implementation for worker runtime."""

    def __init__(self, *, beads_root: Path, repo_root: Path) -> None:
        self._beads_root = beads_root
        self._repo_root = repo_root

    def handle_queue_before_claim(
        self,
        agent_id: str,
        *,
        queue_name: str,
        force_prompt: bool = False,
        dry_run: bool = False,
        assume_yes: bool = False,
    ) -> bool:
        return _handle_queue_before_claim(
            agent_id,
            beads_root=self._beads_root,
            repo_root=self._repo_root,
            queue_name=queue_name,
            force_prompt=force_prompt,
            dry_run=dry_run,
            assume_yes=assume_yes,
        )

    def list_epics(self) -> list[dict[str, object]]:
        return beads.run_bd_json(
            ["list", "--label", "at:epic"],
            beads_root=self._beads_root,
            cwd=self._repo_root,
        )

    def next_changeset(
        self,
        *,
        epic_id: str,
        repo_slug: str | None,
        branch_pr: bool,
        branch_pr_strategy: object,
        git_path: str | None,
    ) -> dict[str, object] | None:
        return _next_changeset(
            epic_id=epic_id,
            beads_root=self._beads_root,
            repo_root=self._repo_root,
            repo_slug=repo_slug,
            branch_pr=branch_pr,
            branch_pr_strategy=branch_pr_strategy,
            git_path=git_path,
        )

    def resolve_hooked_epic(self, agent_bead_id: str, agent_id: str) -> str | None:
        return _resolve_hooked_epic(
            agent_bead_id,
            agent_id,
            beads_root=self._beads_root,
            repo_root=self._repo_root,
        )

    def stale_family_assigned_epics(
        self, issues: list[dict[str, object]], *, agent_id: str
    ) -> list[dict[str, object]]:
        return worker_selection.stale_family_assigned_epics(
            issues,
            agent_id=agent_id,
            is_session_active=agent_home.is_session_agent_active,
        )

    def select_review_feedback_changeset(
        self, *, epic_id: str, repo_slug: str | None
    ) -> ReviewFeedbackSelection | None:
        return _select_review_feedback_changeset(
            epic_id=epic_id,
            repo_slug=repo_slug,
            beads_root=self._beads_root,
            repo_root=self._repo_root,
        )

    def select_global_review_feedback_changeset(
        self, *, repo_slug: str | None
    ) -> ReviewFeedbackSelection | None:
        return _select_global_review_feedback_changeset(
            repo_slug=repo_slug,
            beads_root=self._beads_root,
            repo_root=self._repo_root,
        )

    def check_inbox_before_claim(self, agent_id: str) -> bool:
        return _check_inbox_before_claim(
            agent_id, beads_root=self._beads_root, repo_root=self._repo_root
        )

    def ready_changesets_global(self) -> list[dict[str, object]]:
        return beads.run_bd_json(
            ["ready", "--label", "at:changeset"],
            beads_root=self._beads_root,
            cwd=self._repo_root,
        )

    def select_epic_prompt(
        self,
        issues: list[dict[str, object]],
        *,
        agent_id: str,
        is_actionable: Callable[[str], bool],
        assume_yes: bool,
    ) -> str | None:
        return worker_selection.select_epic_prompt(
            issues,
            agent_id=agent_id,
            is_actionable=is_actionable,
            extract_root_branch=beads.extract_workspace_root_branch,
            select_fn=lambda title, options: select(title, options),
            assume_yes=assume_yes,
        )

    def send_needs_decision(
        self,
        *,
        agent_id: str,
        mode: str,
        issues: list[dict[str, object]],
        dry_run: bool,
    ) -> None:
        worker_queueing.send_needs_decision(
            agent_id=agent_id,
            mode=mode,
            issues=issues,
            beads_root=self._beads_root,
            repo_root=self._repo_root,
            dry_run=dry_run,
            filter_epics=_filter_epics,
            dry_run_log=_dry_run_log,
        )

    def dry_run_log(self, message: str) -> None:
        _dry_run_log(message)

    def emit(self, message: str) -> None:
        say(message)

    def die(self, message: str) -> None:
        die(message)


def _run_startup_contract(
    *,
    context: worker_startup.StartupContractContext,
) -> StartupContractResult:
    service = _StartupContractService(beads_root=context.beads_root, repo_root=context.repo_root)
    return worker_startup.run_startup_contract_service(context=context, service=service)


__all__ = [name for name in globals() if name.startswith("_")]

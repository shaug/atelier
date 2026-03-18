"""Worker-owned epic-close flow built on store-backed mutations."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .. import changesets, lifecycle
from . import store_adapter as worker_store


@dataclass(frozen=True)
class EpicCloseSummary:
    """Summary of descendant changeset terminal state for epic closure."""

    total: int
    ready: int
    merged: int
    abandoned: int
    remaining: int

    @property
    def ready_to_close(self) -> bool:
        """Return whether no remaining descendant changesets are active."""

        return self.total > 0 and self.remaining == 0


def _close_transition_has_active_pr_lifecycle(issue_payload: dict[str, object]) -> bool:
    description = issue_payload.get("description")
    review = changesets.parse_review_metadata(description if isinstance(description, str) else "")
    review_state = lifecycle.normalize_review_state(review.pr_state)
    if review_state == "pushed":
        return lifecycle.canonical_lifecycle_status(issue_payload.get("status")) == "closed"
    return lifecycle.is_active_pr_lifecycle_state(review_state)


def _summarize_changesets(changeset_issues: list[dict[str, object]]) -> EpicCloseSummary:
    merged = 0
    abandoned = 0
    remaining = 0
    for issue in changeset_issues:
        canonical_status = lifecycle.canonical_lifecycle_status(issue.get("status"))
        if canonical_status != "closed":
            remaining += 1
            continue
        description = issue.get("description")
        review = changesets.parse_review_metadata(
            description if isinstance(description, str) else ""
        )
        review_state = lifecycle.normalize_review_state(review.pr_state)
        if review_state == "merged":
            merged += 1
        elif review_state in {"closed", "abandoned"}:
            abandoned += 1
    total = len(changeset_issues)
    return EpicCloseSummary(
        total=total,
        ready=0,
        merged=merged,
        abandoned=abandoned,
        remaining=remaining,
    )


def close_epic_if_complete(
    epic_id: str,
    agent_bead_id: str | None,
    *,
    beads_root: Path,
    repo_root: Path,
    confirm: Callable[[EpicCloseSummary], bool] | None = None,
    dry_run: bool = False,
    dry_run_log: Callable[[str], None] | None = None,
) -> bool:
    """Close one epic when its descendant changesets are terminal."""

    issue = worker_store.show_issue(
        epic_id,
        beads_root=beads_root,
        repo_root=repo_root,
    )
    if issue is None:
        return False
    work_children = worker_store.list_work_children(
        epic_id,
        beads_root=beads_root,
        repo_root=repo_root,
        include_closed=True,
    )
    changeset_candidates = worker_store.list_descendant_changesets(
        epic_id,
        beads_root=beads_root,
        repo_root=repo_root,
        include_closed=True,
    )
    if not changeset_candidates and not work_children:
        changeset_candidates = [issue]

    active_lifecycle_detected = False
    for candidate in changeset_candidates:
        if lifecycle.canonical_lifecycle_status(candidate.get("status")) != "closed":
            continue
        if not _close_transition_has_active_pr_lifecycle(candidate):
            continue
        candidate_id = candidate.get("id")
        if not dry_run and isinstance(candidate_id, str) and candidate_id.strip():
            worker_store.mark_issue_in_progress(
                candidate_id.strip(),
                beads_root=beads_root,
                repo_root=repo_root,
            )
        active_lifecycle_detected = True
    if active_lifecycle_detected:
        return False

    is_standalone_changeset = not work_children and lifecycle.is_closed_status(issue.get("status"))
    summary = _summarize_changesets(changeset_candidates)
    if not is_standalone_changeset and not summary.ready_to_close:
        return False
    if confirm is not None and not confirm(summary):
        return False
    if dry_run:
        if dry_run_log is not None:
            if agent_bead_id:
                dry_run_log(f"Would close epic {epic_id} and clear hook {agent_bead_id}.")
            else:
                dry_run_log(f"Would close epic {epic_id}.")
        return False

    worker_store.transition_lifecycle(
        epic_id,
        target_status="closed",
        beads_root=beads_root,
        repo_root=repo_root,
    )
    if agent_bead_id:
        worker_store.clear_agent_hook(
            agent_bead_id,
            beads_root=beads_root,
            repo_root=repo_root,
            expected_hook=epic_id,
        )
    return True


def direct_close_epic(
    epic_id: str,
    agent_bead_id: str,
    *,
    beads_root: Path,
    repo_root: Path,
) -> None:
    """Close one epic immediately and clear the current worker hook."""

    worker_store.transition_lifecycle(
        epic_id,
        target_status="closed",
        beads_root=beads_root,
        repo_root=repo_root,
    )
    worker_store.clear_agent_hook(
        agent_bead_id,
        beads_root=beads_root,
        repo_root=repo_root,
        expected_hook=epic_id,
    )


__all__ = ["EpicCloseSummary", "close_epic_if_complete", "direct_close_epic"]

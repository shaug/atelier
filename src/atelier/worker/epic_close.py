"""Worker-owned epic-close flow built on store-backed mutations."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from .. import beads, lifecycle
from . import store_adapter as worker_store


def _close_transition_has_active_pr_lifecycle(
    candidate: worker_store.EpicCloseCandidate,
) -> bool:
    review_state = (
        candidate.review.pr_state.value if candidate.review.pr_state is not None else None
    )
    if review_state == "pushed":
        return candidate.lifecycle.value == "closed"
    return lifecycle.is_active_pr_lifecycle_state(review_state)


def close_epic_if_complete(
    epic_id: str,
    agent_bead_id: str | None,
    *,
    beads_root: Path,
    repo_root: Path,
    confirm: Callable[[beads.ChangesetSummary], bool] | None = None,
    dry_run: bool = False,
    dry_run_log: Callable[[str], None] | None = None,
) -> bool:
    """Close one epic when its descendant changesets are terminal."""

    issue_lifecycle = worker_store.show_issue_lifecycle(
        epic_id,
        beads_root=beads_root,
        repo_root=repo_root,
    )
    if issue_lifecycle is None:
        return False
    has_work_children = worker_store.has_work_children(
        epic_id,
        beads_root=beads_root,
        repo_root=repo_root,
        include_closed=True,
    )
    changeset_candidates = worker_store.list_epic_close_candidates(
        epic_id,
        beads_root=beads_root,
        repo_root=repo_root,
        include_closed=True,
    )
    active_lifecycle_detected = False
    for candidate in changeset_candidates:
        if candidate.lifecycle.value != "closed":
            continue
        if not _close_transition_has_active_pr_lifecycle(candidate):
            continue
        if not dry_run:
            worker_store.mark_issue_in_progress(
                candidate.id,
                beads_root=beads_root,
                repo_root=repo_root,
            )
        active_lifecycle_detected = True
    if active_lifecycle_detected:
        return False

    is_standalone_changeset = (
        not has_work_children and issue_lifecycle is worker_store.LifecycleStatus.CLOSED
    )
    summary = worker_store.epic_changeset_summary(
        epic_id,
        beads_root=beads_root,
        repo_root=repo_root,
    )
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


__all__ = ["close_epic_if_complete", "direct_close_epic"]

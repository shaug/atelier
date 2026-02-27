"""Public facade for worker finalization/runtime helper modules."""

from __future__ import annotations

from .work_finalization_integration import (
    finalize_epic_if_complete,
    finalize_terminal_changeset,
)
from .work_finalization_pipeline import finalize_changeset
from .work_finalization_reconcile import (
    list_reconcile_epic_candidates,
    reconcile_blocked_merged_changesets,
)
from .work_finalization_state import (
    changeset_has_review_handoff_signal,
    changeset_integration_signal,
    changeset_parent_branch,
    changeset_pr_url,
    changeset_waiting_on_review_or_signals,
    changeset_work_branch,
    epic_root_integrated_into_parent,
    has_open_descendant_changesets,
    is_changeset_in_progress,
    is_changeset_ready,
    is_changeset_recovery_candidate,
    lookup_pr_payload,
    mark_changeset_blocked,
    mark_changeset_in_progress,
    release_epic_assignment,
    resolve_epic_id_for_changeset,
    send_no_ready_changesets,
    send_planner_notification,
)

__all__ = [
    "changeset_has_review_handoff_signal",
    "changeset_integration_signal",
    "changeset_parent_branch",
    "changeset_pr_url",
    "changeset_waiting_on_review_or_signals",
    "changeset_work_branch",
    "epic_root_integrated_into_parent",
    "finalize_changeset",
    "finalize_epic_if_complete",
    "finalize_terminal_changeset",
    "has_open_descendant_changesets",
    "is_changeset_in_progress",
    "is_changeset_ready",
    "is_changeset_recovery_candidate",
    "list_reconcile_epic_candidates",
    "lookup_pr_payload",
    "mark_changeset_blocked",
    "mark_changeset_in_progress",
    "reconcile_blocked_merged_changesets",
    "release_epic_assignment",
    "resolve_epic_id_for_changeset",
    "send_no_ready_changesets",
    "send_planner_notification",
]

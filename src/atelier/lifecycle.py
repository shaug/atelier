"""Pure lifecycle helpers shared across worker/planner flows."""

from __future__ import annotations

ACTIVE_REVIEW_STATES = {"draft-pr", "pr-open", "in-review", "approved"}


def normalize_review_state(value: object) -> str | None:
    """Normalize persisted PR review state values."""
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if not normalized or normalized == "null":
        return None
    return normalized


def is_closed_status(status: object) -> bool:
    """Return True when issue status is terminal/closed."""
    normalized = str(status or "").strip().lower()
    return normalized in {"closed", "done"}


def is_eligible_epic_status(status: object, *, allow_hooked: bool) -> bool:
    """Return whether an epic status is eligible for worker selection."""
    normalized = str(status or "").strip().lower()
    if not normalized:
        return True
    if normalized in {"open", "ready", "in_progress"}:
        return True
    if allow_hooked and normalized == "hooked":
        return True
    return False


def is_changeset_in_progress(status: object, labels: set[str]) -> bool:
    """Return True when a changeset should be treated as in progress."""
    normalized = str(status or "").strip().lower()
    if normalized == "in_progress":
        return True
    return "cs:in_progress" in labels


def is_changeset_ready(status: object, labels: set[str]) -> bool:
    """Return True when a changeset is runnable."""
    if "cs:ready" in labels:
        return True
    if "at:changeset" not in labels and "cs:in_progress" not in labels:
        return False
    if "cs:planned" in labels or "cs:blocked" in labels:
        return False
    if "cs:merged" in labels or "cs:abandoned" in labels:
        return False
    normalized = str(status or "").strip().lower()
    if normalized in {"closed", "done", "blocked"}:
        return False
    if normalized in {"open", "in_progress", "hooked"}:
        return True
    return "cs:in_progress" in labels


def is_changeset_in_review_candidate(
    *,
    labels: set[str],
    status: object,
    live_state: str | None = None,
    stored_review_state: str | None = None,
) -> bool:
    """Return True when feedback should be checked for a changeset."""
    if "at:changeset" not in labels:
        return False
    if "cs:merged" in labels or "cs:abandoned" in labels:
        return False
    if is_closed_status(status):
        return False
    if live_state is not None:
        return live_state in ACTIVE_REVIEW_STATES
    return normalize_review_state(stored_review_state) in ACTIVE_REVIEW_STATES

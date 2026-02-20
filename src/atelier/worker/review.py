"""Worker review-feedback selection helpers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .. import beads, changeset_fields, lifecycle, prs


@dataclass(frozen=True)
class ReviewFeedbackSelection:
    epic_id: str
    changeset_id: str
    feedback_at: str


def _issue_labels(issue: dict[str, object]) -> set[str]:
    labels = issue.get("labels")
    if not isinstance(labels, list):
        return set()
    return {str(label) for label in labels if label}


def _feedback_cursor(issue: dict[str, object]):
    fields = changeset_fields.issue_fields(issue)
    return prs.parse_timestamp(fields.get("review.last_feedback_seen_at"))


def _is_in_review_candidate(
    issue: dict[str, object], *, live_state: str | None = None
) -> bool:
    return lifecycle.is_changeset_in_review_candidate(
        labels=_issue_labels(issue),
        status=issue.get("status"),
        live_state=live_state,
        stored_review_state=changeset_fields.review_state(issue),
    )


def _selection_candidates(
    *,
    issues: list[dict[str, object]],
    repo_slug: str,
    resolve_epic_id: Callable[[dict[str, object]], str | None],
) -> list[ReviewFeedbackSelection]:
    candidates: list[ReviewFeedbackSelection] = []
    for issue in issues:
        changeset_id = issue.get("id")
        if not isinstance(changeset_id, str) or not changeset_id:
            continue
        work_branch = changeset_fields.work_branch(issue)
        if not work_branch:
            continue
        pr_payload = prs.read_github_pr_status(repo_slug, work_branch)
        live_state = None
        if pr_payload:
            live_state = prs.lifecycle_state(
                pr_payload,
                pushed=False,
                review_requested=prs.has_review_requests(pr_payload),
            )
        if not _is_in_review_candidate(issue, live_state=live_state):
            continue
        feedback_at = prs.latest_feedback_timestamp_with_inline_comments(
            pr_payload, repo=repo_slug
        )
        if not feedback_at:
            continue
        feedback_time = prs.parse_timestamp(feedback_at)
        if feedback_time is None:
            continue
        cursor = _feedback_cursor(issue)
        status = str(issue.get("status") or "").strip().lower()
        if status != "blocked" and cursor is not None and feedback_time <= cursor:
            continue
        epic_id = resolve_epic_id(issue)
        if not epic_id:
            continue
        candidates.append(
            ReviewFeedbackSelection(
                epic_id=epic_id,
                changeset_id=changeset_id,
                feedback_at=feedback_at,
            )
        )
    sentinel = datetime.max.replace(tzinfo=timezone.utc)
    candidates.sort(key=lambda item: prs.parse_timestamp(item.feedback_at) or sentinel)
    return candidates


def select_review_feedback_changeset(
    *,
    epic_id: str,
    repo_slug: str | None,
    beads_root: Path,
    repo_root: Path,
) -> ReviewFeedbackSelection | None:
    """Select the oldest unresolved review-feedback candidate under one epic."""
    if not repo_slug:
        return None
    descendants = beads.list_descendant_changesets(
        epic_id,
        beads_root=beads_root,
        cwd=repo_root,
        include_closed=False,
    )
    candidates = _selection_candidates(
        issues=descendants,
        repo_slug=repo_slug,
        resolve_epic_id=lambda _issue: epic_id,
    )
    return candidates[0] if candidates else None


def select_global_review_feedback_changeset(
    *,
    repo_slug: str | None,
    beads_root: Path,
    repo_root: Path,
    resolve_epic_id_for_changeset: Callable[[dict[str, object]], str | None],
) -> ReviewFeedbackSelection | None:
    """Select the oldest unresolved review-feedback candidate globally."""
    if not repo_slug:
        return None
    issues = beads.run_bd_json(
        ["list", "--label", "at:changeset"], beads_root=beads_root, cwd=repo_root
    )
    candidates = _selection_candidates(
        issues=issues,
        repo_slug=repo_slug,
        resolve_epic_id=resolve_epic_id_for_changeset,
    )
    return candidates[0] if candidates else None

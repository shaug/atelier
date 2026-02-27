"""Worker review-feedback selection helpers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .. import beads, changeset_fields, lifecycle, prs
from .models_boundary import BeadsIssueBoundary


@dataclass(frozen=True)
class ReviewFeedbackSelection:
    epic_id: str
    changeset_id: str
    feedback_at: str


@dataclass(frozen=True)
class MergeConflictSelection:
    epic_id: str
    changeset_id: str
    observed_at: str | None
    pr_url: str | None


def _feedback_cursor(issue: dict[str, object]):
    fields = changeset_fields.issue_fields(issue)
    return prs.parse_timestamp(fields.get("review.last_feedback_seen_at"))


def _is_in_review_candidate(
    issue: BeadsIssueBoundary,
    *,
    raw_issue: dict[str, object],
    live_state: str | None = None,
    has_work_children: bool = False,
) -> bool:
    return lifecycle.is_changeset_in_review_candidate(
        labels=set(issue.labels),
        status=issue.status,
        live_state=live_state,
        stored_review_state=changeset_fields.review_state(raw_issue),
        has_work_children=has_work_children,
        issue_type=lifecycle.issue_payload_type(raw_issue),
        parent_id=raw_issue.get("parent_id"),
    )


def _selection_candidates(
    *,
    records: list[beads.BeadsIssueRecord],
    load_record: Callable[[str], beads.BeadsIssueRecord | None],
    repo_slug: str,
    resolve_epic_id: Callable[[dict[str, object]], str | None],
) -> list[ReviewFeedbackSelection]:
    candidates: list[ReviewFeedbackSelection] = []
    for record in records:
        hydrated = load_record(record.issue.id) or record
        raw_issue = hydrated.raw
        issue = hydrated.issue
        changeset_id = issue.id
        work_branch = changeset_fields.work_branch(raw_issue)
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
        if not _is_in_review_candidate(
            issue,
            raw_issue=raw_issue,
            live_state=live_state,
            has_work_children=False,
        ):
            continue
        feedback_at = prs.latest_feedback_timestamp_with_inline_comments(pr_payload, repo=repo_slug)
        if not feedback_at:
            continue
        feedback_time = prs.parse_timestamp(feedback_at)
        if feedback_time is None:
            continue
        cursor = _feedback_cursor(raw_issue)
        status = str(issue.status or "").strip().lower()
        if status != "blocked" and cursor is not None and feedback_time <= cursor:
            continue
        if isinstance(pr_payload, dict):
            pr_boundary = prs.parse_pr_boundary(pr_payload, source="_selection_candidates:pr")
            pr_number = pr_boundary.number if pr_boundary is not None else None
            if pr_number is not None:
                unresolved_threads = prs.unresolved_review_thread_count(repo_slug, pr_number)
                if unresolved_threads == 0:
                    continue
        epic_id = resolve_epic_id(raw_issue)
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


def _records_for_epic_changesets(
    *,
    epic_id: str,
    beads_root: Path,
    repo_root: Path,
    source: str,
) -> tuple[beads.BeadsClient, list[beads.BeadsIssueRecord]]:
    descendants = beads.list_descendant_changesets(
        epic_id,
        beads_root=beads_root,
        cwd=repo_root,
        include_closed=False,
    )
    client = beads.create_client(beads_root=beads_root, cwd=repo_root)
    records = beads.parse_issue_records(descendants, source=f"{source}:descendants")
    epic_record = client.show_issue(epic_id, source=f"{source}:show_epic")
    if epic_record is not None and epic_record.issue.id == epic_id:
        if not descendants and all(record.issue.id != epic_id for record in records):
            work_children = beads.list_work_children(
                epic_id,
                beads_root=beads_root,
                cwd=repo_root,
                include_closed=False,
            )
            if not work_children:
                records = [epic_record, *records]
    return client, records


def _conflict_selection_candidates(
    *,
    records: list[beads.BeadsIssueRecord],
    load_record: Callable[[str], beads.BeadsIssueRecord | None],
    repo_slug: str,
    resolve_epic_id: Callable[[dict[str, object]], str | None],
) -> list[MergeConflictSelection]:
    candidates: list[MergeConflictSelection] = []
    for record in records:
        hydrated = load_record(record.issue.id) or record
        raw_issue = hydrated.raw
        issue = hydrated.issue
        work_branch = changeset_fields.work_branch(raw_issue)
        if not work_branch:
            continue
        pr_payload = prs.read_github_pr_status(repo_slug, work_branch)
        review_requested = prs.has_review_requests(pr_payload)
        live_state = prs.lifecycle_state(
            pr_payload,
            pushed=False,
            review_requested=review_requested,
        )
        if not _is_in_review_candidate(
            issue,
            raw_issue=raw_issue,
            live_state=live_state,
            has_work_children=False,
        ):
            continue
        if prs.default_branch_has_merge_conflict(pr_payload) is not True:
            continue
        epic_id = resolve_epic_id(raw_issue)
        if not epic_id:
            continue
        observed_at = None
        pr_url = None
        if isinstance(pr_payload, dict):
            raw_updated = pr_payload.get("updatedAt")
            if isinstance(raw_updated, str) and raw_updated.strip():
                observed_at = raw_updated.strip()
            raw_url = pr_payload.get("url")
            if isinstance(raw_url, str) and raw_url.strip():
                pr_url = raw_url.strip()
        if observed_at is None:
            issue_updated = raw_issue.get("updated_at")
            if isinstance(issue_updated, str) and issue_updated.strip():
                observed_at = issue_updated.strip()
        candidates.append(
            MergeConflictSelection(
                epic_id=epic_id,
                changeset_id=issue.id,
                observed_at=observed_at,
                pr_url=pr_url,
            )
        )
    sentinel = datetime.max.replace(tzinfo=timezone.utc)
    candidates.sort(key=lambda item: prs.parse_timestamp(item.observed_at) or sentinel)
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
    client, records = _records_for_epic_changesets(
        epic_id=epic_id,
        beads_root=beads_root,
        repo_root=repo_root,
        source="select_review_feedback_changeset",
    )
    candidates = _selection_candidates(
        records=records,
        load_record=lambda issue_id: client.show_issue(
            issue_id, source="select_review_feedback_changeset:show"
        ),
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
    client = beads.create_client(beads_root=beads_root, cwd=repo_root)
    changesets = beads.list_all_changesets(
        beads_root=beads_root,
        cwd=repo_root,
        include_closed=False,
    )
    records = beads.parse_issue_records(
        changesets,
        source="select_global_review_feedback_changeset:list_changesets",
    )
    candidates = _selection_candidates(
        records=records,
        load_record=lambda issue_id: client.show_issue(
            issue_id, source="select_global_review_feedback_changeset:show"
        ),
        repo_slug=repo_slug,
        resolve_epic_id=resolve_epic_id_for_changeset,
    )
    return candidates[0] if candidates else None


def select_conflicted_changeset(
    *,
    epic_id: str,
    repo_slug: str | None,
    beads_root: Path,
    repo_root: Path,
) -> MergeConflictSelection | None:
    """Select the oldest merge-conflicted changeset under one epic."""
    if not repo_slug:
        return None
    client, records = _records_for_epic_changesets(
        epic_id=epic_id,
        beads_root=beads_root,
        repo_root=repo_root,
        source="select_conflicted_changeset",
    )
    candidates = _conflict_selection_candidates(
        records=records,
        load_record=lambda issue_id: client.show_issue(
            issue_id, source="select_conflicted_changeset:show"
        ),
        repo_slug=repo_slug,
        resolve_epic_id=lambda _issue: epic_id,
    )
    return candidates[0] if candidates else None


def select_global_conflicted_changeset(
    *,
    repo_slug: str | None,
    beads_root: Path,
    repo_root: Path,
    resolve_epic_id_for_changeset: Callable[[dict[str, object]], str | None],
) -> MergeConflictSelection | None:
    """Select the oldest merge-conflicted changeset globally."""
    if not repo_slug:
        return None
    client = beads.create_client(beads_root=beads_root, cwd=repo_root)
    changesets = beads.list_all_changesets(
        beads_root=beads_root,
        cwd=repo_root,
        include_closed=False,
    )
    records = beads.parse_issue_records(
        changesets,
        source="select_global_conflicted_changeset:list_changesets",
    )
    candidates = _conflict_selection_candidates(
        records=records,
        load_record=lambda issue_id: client.show_issue(
            issue_id, source="select_global_conflicted_changeset:show"
        ),
        repo_slug=repo_slug,
        resolve_epic_id=resolve_epic_id_for_changeset,
    )
    return candidates[0] if candidates else None

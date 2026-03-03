"""Worker review-feedback selection helpers."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .. import beads, changeset_fields, lifecycle, prs
from .. import log as atelier_log
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


@dataclass(frozen=True)
class GlobalStartupSelections:
    conflict: MergeConflictSelection | None
    feedback: ReviewFeedbackSelection | None


_GLOBAL_SCAN_ACTIVE_STATUSES = frozenset({"open", "in_progress", "blocked"})
_GLOBAL_SCAN_QUERY_MAX_ATTEMPTS = 3
_SIGNAL_SCAN_MAX_WORKERS = 8


def _feedback_cursor(issue: dict[str, object]):
    fields = changeset_fields.issue_fields(issue)
    return prs.parse_timestamp(fields.get("review.last_feedback_seen_at"))


def _review_feedback_sort_key(item: ReviewFeedbackSelection) -> tuple[datetime, str, str]:
    sentinel = datetime.max.replace(tzinfo=timezone.utc)
    return (
        prs.parse_timestamp(item.feedback_at) or sentinel,
        item.epic_id,
        item.changeset_id,
    )


def _merge_conflict_sort_key(item: MergeConflictSelection) -> tuple[datetime, str, str]:
    sentinel = datetime.max.replace(tzinfo=timezone.utc)
    return (
        prs.parse_timestamp(item.observed_at) or sentinel,
        item.epic_id,
        item.changeset_id,
    )


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
    hydrated_records = [load_record(record.issue.id) or record for record in records]

    def evaluate_record(record: beads.BeadsIssueRecord) -> ReviewFeedbackSelection | None:
        try:
            raw_issue = record.raw
            issue = record.issue
            changeset_id = issue.id
            work_branch = changeset_fields.work_branch(raw_issue)
            if not work_branch:
                return None
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
                return None
            feedback_at = prs.latest_feedback_timestamp_with_inline_comments(
                pr_payload,
                repo=repo_slug,
            )
            if not feedback_at:
                return None
            feedback_time = prs.parse_timestamp(feedback_at)
            if feedback_time is None:
                return None
            cursor = _feedback_cursor(raw_issue)
            status = str(issue.status or "").strip().lower()
            if status != "blocked" and cursor is not None and feedback_time <= cursor:
                return None
            if isinstance(pr_payload, dict):
                pr_boundary = prs.parse_pr_boundary(pr_payload, source="_selection_candidates:pr")
                pr_number = pr_boundary.number if pr_boundary is not None else None
                if pr_number is not None:
                    unresolved_threads = prs.unresolved_review_thread_count(repo_slug, pr_number)
                    if unresolved_threads == 0:
                        return None
            epic_id = resolve_epic_id(raw_issue)
            if not epic_id:
                return None
            return ReviewFeedbackSelection(
                epic_id=epic_id,
                changeset_id=changeset_id,
                feedback_at=feedback_at,
            )
        except Exception as exc:
            atelier_log.warning(
                "startup stage=review-feedback candidate="
                f"{record.issue.id} reason=signal-check-error detail={exc}"
            )
            return None

    candidates: list[ReviewFeedbackSelection] = []
    max_workers = min(_SIGNAL_SCAN_MAX_WORKERS, len(hydrated_records))
    if max_workers <= 1:
        for record in hydrated_records:
            candidate = evaluate_record(record)
            if candidate is not None:
                candidates.append(candidate)
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(evaluate_record, record) for record in hydrated_records]
            for future in as_completed(futures):
                candidate = future.result()
                if candidate is not None:
                    candidates.append(candidate)
    candidates.sort(key=_review_feedback_sort_key)
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


def _emit_global_scan_diagnostic(
    message: str,
    *,
    emit_diagnostic: Callable[[str], None] | None,
) -> None:
    atelier_log.warning(message)
    if emit_diagnostic is not None:
        emit_diagnostic(message)


def _read_query_with_retry(
    *,
    args: list[str],
    beads_root: Path,
    repo_root: Path,
    startup_stage: str,
    subject: str,
    emit_diagnostic: Callable[[str], None] | None,
) -> list[dict[str, object]] | None:
    """Run a read-only Beads query with bounded retries.

    Command and stdout/stderr detail come from
    :func:`beads.run_bd_json_read_only`.
    """
    last_error: str | None = None
    for attempt in range(1, _GLOBAL_SCAN_QUERY_MAX_ATTEMPTS + 1):
        payload, error = beads.run_bd_json_read_only(
            args,
            beads_root=beads_root,
            cwd=repo_root,
        )
        if error is None:
            return payload
        last_error = error
        if attempt < _GLOBAL_SCAN_QUERY_MAX_ATTEMPTS:
            atelier_log.warning(
                "startup stage="
                f"{startup_stage} retry={attempt}/{_GLOBAL_SCAN_QUERY_MAX_ATTEMPTS} "
                f"subject={subject}"
            )
    detail = last_error or "unknown read failure"
    _emit_global_scan_diagnostic(
        (
            f"Startup stage {startup_stage}: skipping {subject} after "
            f"{_GLOBAL_SCAN_QUERY_MAX_ATTEMPTS} failed read-only Beads attempts.\n"
            f"{detail}"
        ),
        emit_diagnostic=emit_diagnostic,
    )
    return None


def _list_work_children_read_only(
    *,
    parent_id: str,
    beads_root: Path,
    repo_root: Path,
    startup_stage: str,
    emit_diagnostic: Callable[[str], None] | None,
) -> list[dict[str, object]] | None:
    raw = _read_query_with_retry(
        args=["list", "--parent", parent_id],
        beads_root=beads_root,
        repo_root=repo_root,
        startup_stage=startup_stage,
        subject=f"candidate family {parent_id}",
        emit_diagnostic=emit_diagnostic,
    )
    if raw is None:
        return None
    return [
        issue
        for issue in raw
        if isinstance(issue, dict)
        and lifecycle.is_work_issue(
            labels=lifecycle.normalized_labels(issue.get("labels")),
            issue_type=lifecycle.issue_payload_type(issue),
        )
    ]


def _list_descendant_changesets_read_only(
    *,
    epic_id: str,
    beads_root: Path,
    repo_root: Path,
    startup_stage: str,
    emit_diagnostic: Callable[[str], None] | None,
) -> tuple[list[dict[str, object]], bool] | None:
    descendants: list[dict[str, object]] = []
    seen: set[str] = set()
    queue: list[tuple[str, dict[str, object] | None]] = [(epic_id, None)]
    has_root_work_children = False
    while queue:
        current, current_issue = queue.pop(0)
        work_children = _list_work_children_read_only(
            parent_id=current,
            beads_root=beads_root,
            repo_root=repo_root,
            startup_stage=startup_stage,
            emit_diagnostic=emit_diagnostic,
        )
        if work_children is None:
            return None
        if current == epic_id:
            has_root_work_children = bool(work_children)
        elif not work_children and current_issue is not None:
            descendants.append(current_issue)
        for issue in work_children:
            issue_id = issue.get("id")
            if not isinstance(issue_id, str) or not issue_id.strip():
                continue
            normalized_issue_id = issue_id.strip()
            if normalized_issue_id in seen:
                continue
            seen.add(normalized_issue_id)
            queue.append((normalized_issue_id, issue))
    return descendants, has_root_work_children


def _global_changeset_records(
    *,
    beads_root: Path,
    repo_root: Path,
    startup_stage: str,
    emit_diagnostic: Callable[[str], None] | None,
) -> tuple[list[beads.BeadsIssueRecord], dict[str, str]]:
    epics: list[dict[str, object]] = []
    seen_epic_ids: set[str] = set()
    for epic_label in beads.issue_label_candidates("epic", beads_root=beads_root):
        labeled_epics = _read_query_with_retry(
            args=[
                "list",
                "--label",
                epic_label,
                "--all",
                "--limit",
                "0",
            ],
            beads_root=beads_root,
            repo_root=repo_root,
            startup_stage=startup_stage,
            subject=f"active epic index ({epic_label})",
            emit_diagnostic=emit_diagnostic,
        )
        if labeled_epics is None:
            continue
        for epic in labeled_epics:
            if not isinstance(epic, dict):
                continue
            epic_id = str(epic.get("id") or "").strip()
            if epic_id:
                if epic_id in seen_epic_ids:
                    continue
                seen_epic_ids.add(epic_id)
            epics.append(epic)
    if not epics:
        return [], {}
    active_epics = [
        issue
        for issue in epics
        if lifecycle.canonical_lifecycle_status(issue.get("status")) in _GLOBAL_SCAN_ACTIVE_STATUSES
    ]
    records: list[beads.BeadsIssueRecord] = []
    epic_by_changeset: dict[str, str] = {}
    for epic in active_epics:
        epic_id = str(epic.get("id") or "").strip()
        if not epic_id:
            continue
        descendants_result = _list_descendant_changesets_read_only(
            epic_id=epic_id,
            beads_root=beads_root,
            repo_root=repo_root,
            startup_stage=startup_stage,
            emit_diagnostic=emit_diagnostic,
        )
        if descendants_result is None:
            continue
        descendants, has_root_work_children = descendants_result
        if descendants:
            descendant_records = beads.parse_issue_records(
                descendants,
                source=f"{startup_stage}:descendants:{epic_id}",
            )
            for record in descendant_records:
                records.append(record)
                epic_by_changeset.setdefault(record.issue.id, epic_id)
            continue
        if has_root_work_children:
            continue
        epic_record = beads.parse_issue_records(
            [epic],
            source=f"{startup_stage}:standalone_epic:{epic_id}",
        )[0]
        records.append(epic_record)
        epic_by_changeset.setdefault(epic_record.issue.id, epic_id)
    return records, epic_by_changeset


def _conflict_selection_candidates(
    *,
    records: list[beads.BeadsIssueRecord],
    load_record: Callable[[str], beads.BeadsIssueRecord | None],
    repo_slug: str,
    resolve_epic_id: Callable[[dict[str, object]], str | None],
) -> list[MergeConflictSelection]:
    hydrated_records = [load_record(record.issue.id) or record for record in records]

    def evaluate_record(record: beads.BeadsIssueRecord) -> MergeConflictSelection | None:
        try:
            raw_issue = record.raw
            issue = record.issue
            work_branch = changeset_fields.work_branch(raw_issue)
            if not work_branch:
                return None
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
                return None
            if prs.default_branch_has_merge_conflict(pr_payload) is not True:
                return None
            epic_id = resolve_epic_id(raw_issue)
            if not epic_id:
                return None
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
            return MergeConflictSelection(
                epic_id=epic_id,
                changeset_id=issue.id,
                observed_at=observed_at,
                pr_url=pr_url,
            )
        except Exception as exc:
            atelier_log.warning(
                "startup stage=merge-conflict candidate="
                f"{record.issue.id} reason=signal-check-error detail={exc}"
            )
            return None

    candidates: list[MergeConflictSelection] = []
    max_workers = min(_SIGNAL_SCAN_MAX_WORKERS, len(hydrated_records))
    if max_workers <= 1:
        for record in hydrated_records:
            candidate = evaluate_record(record)
            if candidate is not None:
                candidates.append(candidate)
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(evaluate_record, record) for record in hydrated_records]
            for future in as_completed(futures):
                candidate = future.result()
                if candidate is not None:
                    candidates.append(candidate)
    candidates.sort(key=_merge_conflict_sort_key)
    return candidates


def select_global_startup_candidates(
    *,
    repo_slug: str | None,
    beads_root: Path,
    repo_root: Path,
    emit_diagnostic: Callable[[str], None] | None = None,
) -> GlobalStartupSelections:
    """Select global merge-conflict and review-feedback candidates in one scan.

    Returns both candidate types so startup can avoid repeating the global scan.
    """
    if not repo_slug:
        return GlobalStartupSelections(conflict=None, feedback=None)
    started = datetime.now(tz=timezone.utc)
    records, epic_by_changeset = _global_changeset_records(
        beads_root=beads_root,
        repo_root=repo_root,
        startup_stage="global-startup-candidates",
        emit_diagnostic=emit_diagnostic,
    )

    def resolve_epic(issue: dict[str, object]) -> str | None:
        return epic_by_changeset.get(str(issue.get("id") or "").strip())

    conflict_candidates = _conflict_selection_candidates(
        records=records,
        load_record=lambda _issue_id: None,
        repo_slug=repo_slug,
        resolve_epic_id=resolve_epic,
    )
    feedback_candidates = _selection_candidates(
        records=records,
        load_record=lambda _issue_id: None,
        repo_slug=repo_slug,
        resolve_epic_id=resolve_epic,
    )
    finished = datetime.now(tz=timezone.utc)
    atelier_log.debug(
        "startup stage=global-startup-candidates "
        f"records={len(records)} "
        f"elapsed={(finished - started).total_seconds():.4f}s"
    )
    return GlobalStartupSelections(
        conflict=conflict_candidates[0] if conflict_candidates else None,
        feedback=feedback_candidates[0] if feedback_candidates else None,
    )


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
    emit_diagnostic: Callable[[str], None] | None = None,
) -> ReviewFeedbackSelection | None:
    """Select the oldest unresolved review-feedback candidate globally."""
    if not repo_slug:
        return None
    del resolve_epic_id_for_changeset
    records, epic_by_changeset = _global_changeset_records(
        beads_root=beads_root,
        repo_root=repo_root,
        startup_stage="global-review-feedback",
        emit_diagnostic=emit_diagnostic,
    )
    candidates = _selection_candidates(
        records=records,
        load_record=lambda _issue_id: None,
        repo_slug=repo_slug,
        resolve_epic_id=lambda issue: epic_by_changeset.get(str(issue.get("id") or "").strip()),
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
    emit_diagnostic: Callable[[str], None] | None = None,
) -> MergeConflictSelection | None:
    """Select the oldest merge-conflicted changeset globally."""
    if not repo_slug:
        return None
    del resolve_epic_id_for_changeset
    records, epic_by_changeset = _global_changeset_records(
        beads_root=beads_root,
        repo_root=repo_root,
        startup_stage="global-merge-conflict",
        emit_diagnostic=emit_diagnostic,
    )
    candidates = _conflict_selection_candidates(
        records=records,
        load_record=lambda _issue_id: None,
        repo_slug=repo_slug,
        resolve_epic_id=lambda issue: epic_by_changeset.get(str(issue.get("id") or "").strip()),
    )
    return candidates[0] if candidates else None

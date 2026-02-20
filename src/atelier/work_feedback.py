"""Review-feedback helpers shared by worker runtime flows."""

from __future__ import annotations

import dataclasses
from pathlib import Path

from . import beads, git, prs


@dataclasses.dataclass(frozen=True)
class ReviewFeedbackSnapshot:
    feedback_at: str | None
    unresolved_threads: int | None
    branch_head: str | None


def _changeset_work_branch(issue: dict[str, object]) -> str | None:
    description = issue.get("description")
    fields = beads.parse_description_fields(
        description if isinstance(description, str) else ""
    )
    raw = fields.get("changeset.work_branch")
    if not isinstance(raw, str):
        return None
    normalized = raw.strip()
    if not normalized or normalized.lower() == "null":
        return None
    return normalized


def persist_review_feedback_cursor(
    *,
    changeset_id: str,
    issue: dict[str, object],
    repo_slug: str | None,
    beads_root: Path,
    repo_root: Path,
) -> None:
    if not repo_slug:
        return
    work_branch = _changeset_work_branch(issue)
    if not work_branch:
        return
    lookup = prs.lookup_github_pr_status(repo_slug, work_branch)
    pr_payload = lookup.payload if lookup.found else None
    feedback_at = prs.latest_feedback_timestamp_with_inline_comments(
        pr_payload, repo=repo_slug
    )
    if not feedback_at:
        return
    beads.update_changeset_review_feedback_cursor(
        changeset_id,
        feedback_at,
        beads_root=beads_root,
        cwd=repo_root,
    )


def capture_review_feedback_snapshot(
    *,
    issue: dict[str, object],
    repo_slug: str | None,
    repo_root: Path,
    git_path: str | None,
) -> ReviewFeedbackSnapshot:
    work_branch = _changeset_work_branch(issue)
    if not work_branch:
        return ReviewFeedbackSnapshot(
            feedback_at=None, unresolved_threads=None, branch_head=None
        )
    branch_head = git.git_rev_parse(repo_root, work_branch, git_path=git_path)
    if not repo_slug:
        return ReviewFeedbackSnapshot(
            feedback_at=None, unresolved_threads=None, branch_head=branch_head
        )
    lookup = prs.lookup_github_pr_status(repo_slug, work_branch)
    pr_payload = lookup.payload if lookup.found else None
    feedback_at = prs.latest_feedback_timestamp_with_inline_comments(
        pr_payload, repo=repo_slug
    )
    unresolved_threads = None
    if isinstance(pr_payload, dict):
        raw_number = pr_payload.get("number")
        pr_number = raw_number if isinstance(raw_number, int) else None
        if (
            pr_number is None
            and isinstance(raw_number, str)
            and raw_number.strip().isdigit()
        ):
            pr_number = int(raw_number.strip())
        if pr_number is not None:
            unresolved_threads = prs.unresolved_review_thread_count(
                repo_slug, pr_number
            )
    return ReviewFeedbackSnapshot(
        feedback_at=feedback_at,
        unresolved_threads=unresolved_threads,
        branch_head=branch_head,
    )


def review_feedback_progressed(
    before: ReviewFeedbackSnapshot, after: ReviewFeedbackSnapshot
) -> bool:
    if (
        before.unresolved_threads is not None
        and after.unresolved_threads is not None
        and after.unresolved_threads < before.unresolved_threads
    ):
        return True
    if after.feedback_at and (
        before.feedback_at is None or after.feedback_at > before.feedback_at
    ):
        return True
    if (
        before.branch_head
        and after.branch_head
        and after.branch_head.strip()
        and after.branch_head != before.branch_head
    ):
        return True
    return False

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from atelier import prs, work_feedback


def _issue(work_branch: str = "feat/test") -> dict[str, object]:
    return {
        "id": "at-123",
        "status": "in_progress",
        "labels": ["at:changeset", "cs:in_progress"],
        "description": f"changeset.work_branch: {work_branch}\n",
    }


def test_capture_review_feedback_snapshot_returns_validated_snapshot() -> None:
    with (
        patch("atelier.work_feedback.git.git_rev_parse", return_value="abc123"),
        patch(
            "atelier.work_feedback.prs.lookup_github_pr_status",
            return_value=prs.GithubPrLookup(outcome="found", payload={"number": 42}),
        ),
        patch(
            "atelier.work_feedback.prs.latest_feedback_timestamp_with_inline_comments",
            return_value="2026-02-20T12:00:00Z",
        ),
        patch(
            "atelier.work_feedback.prs.unresolved_review_thread_count",
            return_value=2,
        ),
    ):
        snapshot = work_feedback.capture_review_feedback_snapshot(
            issue=_issue(),
            repo_slug="org/repo",
            repo_root=Path("/repo"),
            git_path="git",
        )

    assert snapshot.feedback_at == "2026-02-20T12:00:00Z"
    assert snapshot.unresolved_threads == 2
    assert snapshot.branch_head == "abc123"


def test_capture_review_feedback_snapshot_rejects_negative_thread_count() -> None:
    with (
        patch("atelier.work_feedback.git.git_rev_parse", return_value="abc123"),
        patch(
            "atelier.work_feedback.prs.lookup_github_pr_status",
            return_value=prs.GithubPrLookup(outcome="found", payload={"number": 42}),
        ),
        patch(
            "atelier.work_feedback.prs.latest_feedback_timestamp_with_inline_comments",
            return_value="2026-02-20T12:00:00Z",
        ),
        patch(
            "atelier.work_feedback.prs.unresolved_review_thread_count",
            return_value=-1,
        ),
    ):
        with pytest.raises(ValueError, match="invalid review feedback payload"):
            work_feedback.capture_review_feedback_snapshot(
                issue=_issue(),
                repo_slug="org/repo",
                repo_root=Path("/repo"),
                git_path="git",
            )


def test_review_feedback_progressed_when_threads_fully_resolved() -> None:
    before = work_feedback.ReviewFeedbackSnapshot(
        feedback_at="2026-02-20T12:00:00Z",
        unresolved_threads=0,
        branch_head="abc123",
    )
    after = work_feedback.ReviewFeedbackSnapshot(
        feedback_at="2026-02-20T12:00:00Z",
        unresolved_threads=0,
        branch_head="abc123",
    )

    assert work_feedback.review_feedback_progressed(before, after) is True

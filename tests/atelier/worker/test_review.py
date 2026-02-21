from pathlib import Path
from unittest.mock import patch

import pytest

from atelier import beads, prs
from atelier.worker import review


def test_select_review_feedback_changeset_picks_oldest_unseen() -> None:
    issues = [
        {
            "id": "at-1.1",
            "labels": ["at:changeset"],
            "status": "in_progress",
            "description": (
                "changeset.work_branch: feat/a\n"
                "pr_state: in-review\n"
                "review.last_feedback_seen_at: 2026-02-20T10:00:00Z\n"
            ),
        },
        {
            "id": "at-1.2",
            "labels": ["at:changeset"],
            "status": "in_progress",
            "description": (
                "changeset.work_branch: feat/b\n"
                "pr_state: in-review\n"
                "review.last_feedback_seen_at: 2026-02-20T10:00:00Z\n"
            ),
        },
    ]

    def fake_lookup(repo: str, branch: str) -> prs.GithubPrLookup:
        number = 11 if branch == "feat/a" else 22
        return prs.GithubPrLookup(
            outcome="found",
            payload={
                "number": number,
                "state": "OPEN",
                "isDraft": False,
                "reviewDecision": None,
                "reviewRequests": [{"requestedReviewer": {"login": "alice"}}],
            },
        )

    def fake_feedback(payload: dict[str, object] | None, *, repo: str) -> str | None:
        if not payload:
            return None
        return (
            "2026-02-20T11:00:00Z"
            if payload.get("number") == 11
            else "2026-02-20T10:30:00Z"
        )

    with (
        patch(
            "atelier.worker.review.beads.list_descendant_changesets",
            return_value=issues,
        ),
        patch(
            "atelier.worker.review.prs.lookup_github_pr_status", side_effect=fake_lookup
        ),
        patch(
            "atelier.worker.review.prs.latest_feedback_timestamp_with_inline_comments",
            side_effect=fake_feedback,
        ),
    ):
        selection = review.select_review_feedback_changeset(
            epic_id="at-1",
            repo_slug="org/repo",
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
        )

    assert selection is not None
    assert selection.epic_id == "at-1"
    assert selection.changeset_id == "at-1.2"


def test_select_global_review_feedback_changeset_uses_resolver() -> None:
    issues = [
        {
            "id": "at-2.1",
            "labels": ["at:changeset"],
            "status": "in_progress",
            "description": "changeset.work_branch: feat/c\npr_state: in-review\n",
        }
    ]
    issue_records = beads.parse_issue_records(
        issues, source="test_select_global_review_feedback_changeset_uses_resolver"
    )

    with (
        patch(
            "atelier.worker.review.beads.BeadsClient.issue_records",
            return_value=issue_records,
        ),
        patch(
            "atelier.worker.review.prs.lookup_github_pr_status",
            return_value=prs.GithubPrLookup(
                outcome="found",
                payload={
                    "number": 42,
                    "state": "OPEN",
                    "isDraft": False,
                    "reviewDecision": None,
                    "reviewRequests": [{"requestedReviewer": {"login": "alice"}}],
                },
            ),
        ),
        patch(
            "atelier.worker.review.prs.latest_feedback_timestamp_with_inline_comments",
            return_value="2026-02-20T12:00:00Z",
        ),
    ):
        selection = review.select_global_review_feedback_changeset(
            repo_slug="org/repo",
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            resolve_epic_id_for_changeset=lambda issue: "at-2",
        )

    assert selection is not None
    assert selection.epic_id == "at-2"
    assert selection.changeset_id == "at-2.1"


def test_select_review_feedback_changeset_invalid_issue_payload_fails() -> None:
    issues = [{"status": "in_progress", "labels": ["at:changeset"]}]

    with patch(
        "atelier.worker.review.beads.list_descendant_changesets",
        return_value=issues,
    ):
        with pytest.raises(ValueError, match="invalid beads issue payload"):
            review.select_review_feedback_changeset(
                epic_id="at-1",
                repo_slug="org/repo",
                beads_root=Path("/beads"),
                repo_root=Path("/repo"),
            )

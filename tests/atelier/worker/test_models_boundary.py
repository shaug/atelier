from __future__ import annotations

import pytest

from atelier.worker.models_boundary import (
    parse_issue_boundary,
    parse_pr_boundary,
    parse_review_feedback_boundary,
)


def test_parse_issue_boundary_normalizes_dependency_and_parent_fields() -> None:
    issue = {
        "id": "at-123",
        "status": "open",
        "labels": ["at:changeset", "cs:ready", "cs:ready"],
        "parent": {"id": "at-1"},
        "dependencies": [
            {"id": "at-2"},
            "at-3 (open, cs:ready)",
            {"relation": "parent-child", "id": "at-parent"},
        ],
    }

    boundary = parse_issue_boundary(issue, source="test")

    assert boundary.id == "at-123"
    assert boundary.status == "open"
    assert boundary.parent_id == "at-1"
    assert boundary.dependency_ids == ("at-2", "at-3")
    assert boundary.labels == ("at:changeset", "cs:ready")


def test_parse_issue_boundary_rejects_missing_issue_id() -> None:
    with pytest.raises(ValueError, match="invalid beads issue payload"):
        parse_issue_boundary({"status": "open"}, source="test")


def test_parse_pr_boundary_normalizes_numeric_string_number() -> None:
    payload = {
        "number": "204",
        "state": "OPEN",
        "reviewRequests": [
            {"requestedReviewer": {"login": "reviewer", "isBot": False}}
        ],
    }

    boundary = parse_pr_boundary(payload, source="test")

    assert boundary is not None
    assert boundary.number == 204
    assert len(boundary.review_requests) == 1
    reviewer = boundary.review_requests[0].requested_reviewer
    assert reviewer is not None
    assert reviewer.login == "reviewer"


def test_parse_pr_boundary_rejects_invalid_number() -> None:
    with pytest.raises(ValueError, match="invalid github PR payload"):
        parse_pr_boundary({"number": "not-a-number"}, source="test")


def test_parse_review_feedback_boundary_rejects_negative_thread_count() -> None:
    with pytest.raises(ValueError, match="invalid review feedback payload"):
        parse_review_feedback_boundary(
            feedback_at="2026-02-20T00:00:00Z",
            unresolved_threads=-1,
            branch_head="abc123",
            source="test",
        )

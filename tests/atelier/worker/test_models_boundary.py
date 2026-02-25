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


def test_parse_issue_boundary_derives_parent_from_parent_child_dependency() -> None:
    issue = {
        "id": "at-123",
        "status": "open",
        "labels": ["at:changeset"],
        "parent": None,
        "dependencies": [
            {"relation": "parent-child", "id": "at-1"},
            {"id": "at-2"},
        ],
    }

    boundary = parse_issue_boundary(issue, source="test")

    assert boundary.parent_id == "at-1"
    assert boundary.dependency_ids == ("at-2",)


@pytest.mark.parametrize(
    ("dependency_entry", "expected_parent"),
    [
        ({"dependency_type": "parent-child", "id": "at-1"}, "at-1"),
        ({"type": "parent-child", "id": "at-1"}, "at-1"),
        ({"dependencyType": "parent_child", "issue": {"id": "at-1"}}, "at-1"),
        ("at-1 (open, dependency_type=parent_child)", None),
    ],
)
def test_parse_issue_boundary_handles_parent_child_dependency_variants(
    dependency_entry: object, expected_parent: str | None
) -> None:
    issue = {
        "id": "at-123",
        "status": "open",
        "labels": ["at:changeset"],
        "parent": None,
        "dependencies": [
            dependency_entry,
            {"id": "at-2"},
        ],
    }

    boundary = parse_issue_boundary(issue, source="test")

    assert boundary.parent_id == expected_parent
    assert boundary.dependency_ids == ("at-2",)


def test_parse_issue_boundary_supports_depends_on_dependency_shapes() -> None:
    issue = {
        "id": "at-123",
        "status": "open",
        "labels": ["at:changeset"],
        "parent": None,
        "dependencies": [
            {"depends_on_id": "at-1"},
            {"dependsOnId": "at-2"},
            {"depends_on": {"id": "at-3"}},
            {"dependsOn": {"id": "at-4"}},
            {"dependency_type": "parent-child", "depends_on_id": "at-parent"},
        ],
    }

    boundary = parse_issue_boundary(issue, source="test")

    assert boundary.parent_id == "at-parent"
    assert boundary.dependency_ids == ("at-1", "at-2", "at-3", "at-4")


def test_parse_issue_boundary_rejects_missing_issue_id() -> None:
    with pytest.raises(ValueError, match="invalid beads issue payload"):
        parse_issue_boundary({"status": "open"}, source="test")


def test_parse_pr_boundary_normalizes_numeric_string_number() -> None:
    payload = {
        "number": "204",
        "state": "OPEN",
        "mergeable": "MERGEABLE",
        "mergeStateStatus": "DIRTY",
        "reviewRequests": [{"requestedReviewer": {"login": "reviewer", "isBot": False}}],
    }

    boundary = parse_pr_boundary(payload, source="test")

    assert boundary is not None
    assert boundary.number == 204
    assert len(boundary.review_requests) == 1
    reviewer = boundary.review_requests[0].requested_reviewer
    assert reviewer is not None
    assert reviewer.login == "reviewer"
    assert boundary.mergeable == "MERGEABLE"
    assert boundary.merge_state_status == "DIRTY"


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

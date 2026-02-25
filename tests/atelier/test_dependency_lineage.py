from __future__ import annotations

from atelier import dependency_lineage


def test_resolve_parent_lineage_prefers_unique_transitive_frontier_dependency() -> None:
    issue = {
        "description": (
            "changeset.parent_branch: feature-root\nchangeset.root_branch: feature-root\n"
        ),
        "dependencies": ["cs-1", "cs-2"],
    }
    lookup = {
        "cs-1": {
            "id": "cs-1",
            "description": "changeset.work_branch: feature-parent-1\n",
        },
        "cs-2": {
            "id": "cs-2",
            "description": "changeset.work_branch: feature-parent-2\n",
            "dependencies": ["cs-1"],
        },
    }

    lineage = dependency_lineage.resolve_parent_lineage(
        issue,
        root_branch="feature-root",
        lookup_issue=lookup.get,
    )

    assert lineage.blocked is False
    assert lineage.dependency_parent_id == "cs-2"
    assert lineage.dependency_parent_branch == "feature-parent-2"
    assert lineage.used_dependency_parent is True
    assert lineage.effective_parent_branch == "feature-parent-2"


def test_resolve_parent_lineage_fails_closed_when_dependency_frontier_is_ambiguous() -> None:
    issue = {
        "description": (
            "changeset.parent_branch: feature-root\nchangeset.root_branch: feature-root\n"
        ),
        "dependencies": ["cs-1", "cs-2"],
    }
    lookup = {
        "cs-1": {
            "id": "cs-1",
            "description": "changeset.work_branch: feature-parent-1\n",
        },
        "cs-2": {
            "id": "cs-2",
            "description": "changeset.work_branch: feature-parent-2\n",
        },
    }

    lineage = dependency_lineage.resolve_parent_lineage(
        issue,
        root_branch="feature-root",
        lookup_issue=lookup.get,
    )

    assert lineage.blocked is True
    assert lineage.blocker_reason == "dependency-lineage-ambiguous"
    assert lineage.dependency_parent_id is None
    assert lineage.dependency_parent_branch is None
    assert lineage.diagnostics
    assert lineage.diagnostics[0].startswith("ambiguous dependency parent branches:")

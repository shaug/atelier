from __future__ import annotations

from atelier import dependency_lineage


def test_resolve_parent_lineage_uses_dependency_frontier_for_collapsed_parent() -> None:
    issue = {
        "description": (
            "changeset.root_branch: feat/at-kid\nchangeset.parent_branch: feat/at-kid\n"
        ),
        "dependencies": ["at-kid.1"],
    }

    resolution = dependency_lineage.resolve_parent_lineage(
        issue,
        root_branch="feat/at-kid",
        lookup_issue=lambda issue_id: (
            {"description": "changeset.work_branch: feat/at-kid.1\n"}
            if issue_id == "at-kid.1"
            else None
        ),
    )

    assert resolution.blocked is False
    assert resolution.used_dependency_parent is True
    assert resolution.dependency_parent_id == "at-kid.1"
    assert resolution.effective_parent_branch == "feat/at-kid.1"


def test_resolve_parent_lineage_uses_parent_child_hint_to_break_frontier_ties() -> None:
    issue = {
        "description": (
            "changeset.root_branch: feat/at-kid\nchangeset.parent_branch: feat/at-kid\n"
        ),
        "dependencies": [
            {"dependency_type": "parent-child", "id": "at-kid.2"},
            "at-kid.1",
            "at-kid.2",
        ],
    }

    resolution = dependency_lineage.resolve_parent_lineage(
        issue,
        root_branch="feat/at-kid",
        lookup_issue=lambda issue_id: {"description": f"changeset.work_branch: feat/{issue_id}\n"},
    )

    assert resolution.blocked is False
    assert resolution.used_dependency_parent is True
    assert resolution.dependency_parent_id == "at-kid.2"
    assert resolution.effective_parent_branch == "feat/at-kid.2"


def test_resolve_parent_lineage_scopes_lineage_to_epic_heritage() -> None:
    issue = {
        "id": "at-epic.3",
        "parent": "at-epic",
        "description": (
            "changeset.root_branch: feat/at-epic\nchangeset.parent_branch: feat/at-epic\n"
        ),
        "dependencies": ["at-epic.2", "at-other.9"],
    }
    lookup = {
        "at-epic.2": {
            "id": "at-epic.2",
            "parent": "at-epic",
            "description": "changeset.work_branch: feat/at-epic.2\n",
        },
        "at-other.9": {
            "id": "at-other.9",
            "parent": "at-other",
            "description": "changeset.work_branch: feat/at-other.9\n",
        },
    }

    resolution = dependency_lineage.resolve_parent_lineage(
        issue,
        root_branch="feat/at-epic",
        lookup_issue=lookup.get,
    )

    assert resolution.blocked is False
    assert resolution.dependency_ids == ("at-epic.2", "at-other.9")
    assert resolution.used_dependency_parent is True
    assert resolution.dependency_parent_id == "at-epic.2"
    assert resolution.effective_parent_branch == "feat/at-epic.2"


def test_resolve_parent_lineage_fails_closed_when_heritage_has_no_lineage_candidate() -> None:
    issue = {
        "id": "at-epic.3",
        "parent": "at-epic",
        "description": (
            "changeset.root_branch: feat/at-epic\nchangeset.parent_branch: feat/at-epic\n"
        ),
        "dependencies": ["at-other.9"],
    }

    resolution = dependency_lineage.resolve_parent_lineage(
        issue,
        root_branch="feat/at-epic",
        lookup_issue=lambda issue_id: {
            "id": issue_id,
            "parent": "at-other",
            "description": "changeset.work_branch: feat/at-other.9\n",
        },
    )

    assert resolution.blocked is True
    assert resolution.blocker_reason == "dependency-parent-unresolved"
    assert resolution.effective_parent_branch == "feat/at-epic"
    assert any(
        "epic heritage at-epic has no dependency lineage candidates" in diagnostic
        for diagnostic in resolution.diagnostics
    )


def test_resolve_parent_lineage_parent_child_hint_supports_dependency_type() -> None:
    issue = {
        "description": (
            "changeset.root_branch: feat/at-kid\nchangeset.parent_branch: feat/at-kid\n"
        ),
        "dependencies": [
            {"dependency_type": "parent_child", "issue": {"id": "at-kid.2"}},
            "at-kid.1",
            "at-kid.2",
        ],
    }

    resolution = dependency_lineage.resolve_parent_lineage(
        issue,
        root_branch="feat/at-kid",
        lookup_issue=lambda issue_id: {"description": f"changeset.work_branch: feat/{issue_id}\n"},
    )

    assert resolution.blocked is False
    assert resolution.used_dependency_parent is True
    assert resolution.dependency_parent_id == "at-kid.2"
    assert resolution.effective_parent_branch == "feat/at-kid.2"


def test_resolve_parent_lineage_ignores_parent_child_string_dependency_entries() -> None:
    issue = {
        "description": ("changeset.root_branch: feat/root\nchangeset.parent_branch: feat/root\n"),
        "dependencies": ["at-epic (open, dependency_type=parent_child)"],
    }

    resolution = dependency_lineage.resolve_parent_lineage(
        issue,
        root_branch="feat/root",
        lookup_issue=lambda _issue_id: None,
    )

    assert resolution.blocked is False
    assert resolution.dependency_ids == ()
    assert resolution.dependency_parent_id is None
    assert resolution.effective_parent_branch == "feat/root"


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


def test_resolve_parent_lineage_blocks_when_dependency_frontier_is_ambiguous() -> None:
    issue = {
        "description": (
            "changeset.root_branch: feat/at-kid\nchangeset.parent_branch: feat/at-kid\n"
        ),
        "dependencies": ["at-kid.1", "at-kid.2"],
    }

    resolution = dependency_lineage.resolve_parent_lineage(
        issue,
        root_branch="feat/at-kid",
        lookup_issue=lambda issue_id: {"description": f"changeset.work_branch: feat/{issue_id}\n"},
    )

    assert resolution.blocked is True
    assert resolution.blocker_reason == "dependency-lineage-ambiguous"
    assert resolution.used_dependency_parent is False
    assert resolution.effective_parent_branch == "feat/at-kid"
    assert "ambiguous dependency parent branches" in resolution.diagnostics[0]


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

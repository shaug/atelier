from __future__ import annotations

from atelier import dependency_lineage


def test_resolve_parent_lineage_keeps_explicit_stacked_parent() -> None:
    issue = {
        "description": ("changeset.root_branch: feat/root\nchangeset.parent_branch: feat/parent\n"),
        "dependencies": ["at-epic.1"],
    }

    resolution = dependency_lineage.resolve_parent_lineage(
        issue,
        root_branch="feat/root",
        lookup_issue=lambda _issue_id: {"description": "changeset.work_branch: feat/alt\n"},
    )

    assert resolution.blocked is False
    assert resolution.used_dependency_parent is False
    assert resolution.effective_parent_branch == "feat/parent"


def test_resolve_parent_lineage_uses_dependency_when_parent_collapses_to_root() -> None:
    issue = {
        "description": ("changeset.root_branch: feat/root\nchangeset.parent_branch: feat/root\n"),
        "dependencies": ["at-epic.1"],
    }

    resolution = dependency_lineage.resolve_parent_lineage(
        issue,
        root_branch="feat/root",
        lookup_issue=lambda _issue_id: {"description": "changeset.work_branch: feat/at-epic.1\n"},
    )

    assert resolution.blocked is False
    assert resolution.used_dependency_parent is True
    assert resolution.dependency_parent_id == "at-epic.1"
    assert resolution.effective_parent_branch == "feat/at-epic.1"


def test_resolve_parent_lineage_fails_closed_when_dependency_parent_is_ambiguous() -> None:
    issue = {
        "description": ("changeset.root_branch: feat/root\nchangeset.parent_branch: feat/root\n"),
        "dependencies": ["at-epic.1", "at-epic.2"],
    }

    def lookup(issue_id: str) -> dict[str, object]:
        return {"description": f"changeset.work_branch: feat/{issue_id}\n"}

    resolution = dependency_lineage.resolve_parent_lineage(
        issue,
        root_branch="feat/root",
        lookup_issue=lookup,
    )

    assert resolution.blocked is True
    assert resolution.blocker_reason == "dependency-lineage-ambiguous"
    assert resolution.effective_parent_branch == "feat/root"
    assert resolution.diagnostics

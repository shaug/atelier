from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from atelier.worker.context import ChangesetSelectionContext
from atelier.worker.models_boundary import parse_issue_boundary
from atelier.worker.session import runner


class _FakeSelectionService:
    def __init__(self, *, show_issue, resolve_epic, next_changeset) -> None:
        self._show_issue = show_issue
        self._resolve_epic = resolve_epic
        self._next_changeset = next_changeset

    def show_issue(self, issue_id: str):
        return self._show_issue(issue_id)

    def resolve_epic_id_for_changeset(self, issue):
        return self._resolve_epic(issue)

    def next_changeset(self, epic_id: str, *, resume_review: bool):
        return self._next_changeset(epic_id, resume_review=resume_review)


def test_select_changeset_uses_startup_override_when_epic_matches() -> None:
    override_issue = {"id": "at-epic.2"}
    service = _FakeSelectionService(
        show_issue=lambda issue_id: override_issue if issue_id == "at-epic.2" else None,
        resolve_epic=lambda _issue: "at-epic",
        next_changeset=lambda _epic_id, *, resume_review: (
            {"id": "at-epic.1"} if not resume_review else None
        ),
    )

    selected = runner.select_changeset(
        context=ChangesetSelectionContext(
            selected_epic="at-epic",
            startup_changeset_id="at-epic.2",
        ),
        service=service,
    )

    assert selected.issue == override_issue
    assert selected.selected_override == "at-epic.2"


def test_select_changeset_falls_back_to_next_ready() -> None:
    service = _FakeSelectionService(
        show_issue=lambda _issue_id: None,
        resolve_epic=lambda _issue: None,
        next_changeset=lambda _epic_id, *, resume_review: (
            {"id": "at-epic.1"} if not resume_review else None
        ),
    )

    selected = runner.select_changeset(
        context=ChangesetSelectionContext(
            selected_epic="at-epic",
            startup_changeset_id="at-epic.2",
        ),
        service=service,
    )

    assert selected.issue == {"id": "at-epic.1"}
    assert selected.selected_override == "at-epic.2"


def test_select_changeset_passes_resume_review_flag() -> None:
    observed: list[bool] = []
    service = _FakeSelectionService(
        show_issue=lambda _issue_id: None,
        resolve_epic=lambda _issue: None,
        next_changeset=lambda _epic_id, *, resume_review: (
            observed.append(resume_review) or {"id": "at-epic.1"}
        ),
    )

    selected = runner.select_changeset(
        context=ChangesetSelectionContext(
            selected_epic="at-epic",
            startup_changeset_id=None,
            resume_review=True,
        ),
        service=service,
    )

    assert selected.issue == {"id": "at-epic.1"}
    assert observed == [True]


def test_select_changeset_keeps_startup_override_for_null_parent_id_payload() -> None:
    calls: list[tuple[str, bool]] = []
    override_issue = {"id": "at-epic.2", "parent_id": None, "parent": "at-epic"}

    def resolve_epic(issue: dict[str, object]) -> str | None:
        parent_id = parse_issue_boundary(issue, source="test").parent_id
        issue_id = issue.get("id")
        if parent_id:
            return parent_id
        return issue_id if isinstance(issue_id, str) else None

    service = _FakeSelectionService(
        show_issue=lambda issue_id: override_issue if issue_id == "at-epic.2" else None,
        resolve_epic=resolve_epic,
        next_changeset=lambda epic_id, *, resume_review: (
            calls.append((epic_id, resume_review)) or {"id": "at-epic.1"}
        ),
    )

    selected = runner.select_changeset(
        context=ChangesetSelectionContext(
            selected_epic="at-epic",
            startup_changeset_id="at-epic.2",
        ),
        service=service,
    )

    assert selected.issue == override_issue
    assert calls == []


def test_find_active_root_branch_conflicts_queries_compatibility_epic_labels() -> None:
    queries: list[list[str]] = []

    class _FakeBeads:
        def run_bd_json(
            self,
            args: list[str],
            *,
            beads_root: Path,
            cwd: Path,
        ) -> list[dict[str, object]]:
            del beads_root, cwd
            queries.append(args)
            label = args[2]
            if label == "ts:epic":
                return [
                    {
                        "id": "ts-epic",
                        "status": "in_progress",
                        "title": "Current",
                        "root_branch": "feat/root",
                    },
                    {
                        "id": "shared-epic",
                        "status": "open",
                        "title": "Shared",
                        "root_branch": "feat/root",
                    },
                ]
            if label == "at:epic":
                return [
                    {
                        "id": "shared-epic",
                        "status": "open",
                        "title": "Shared legacy",
                        "root_branch": "feat/root",
                    },
                    {
                        "id": "at-legacy",
                        "status": "blocked",
                        "title": "Legacy",
                        "root_branch": "feat/root",
                    },
                ]
            return []

        def extract_workspace_root_branch(self, issue: dict[str, object]) -> str:
            return str(issue.get("root_branch") or "")

    with patch(
        "atelier.worker.session.runner.beads_runtime.issue_label_candidates",
        return_value=("ts:epic", "at:epic"),
    ):
        blocking = runner._find_active_root_branch_conflicts(  # pyright: ignore[reportPrivateUsage]
            beads=_FakeBeads(),
            root_branch="feat/root",
            selected_epic="ts-epic",
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
        )

    assert queries == [
        ["list", "--label", "ts:epic", "--all", "--limit", "0"],
        ["list", "--label", "at:epic", "--all", "--limit", "0"],
    ]
    assert [issue["id"] for issue in blocking] == ["shared-epic", "at-legacy"]

from __future__ import annotations

from atelier.worker.context import ChangesetSelectionContext
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

from __future__ import annotations

import pytest

from atelier.worker.session import startup


class FakeNextChangesetService:
    def __init__(
        self,
        *,
        issues_by_id: dict[str, dict[str, object]],
        ready_changesets: list[dict[str, object]],
        descendants: list[dict[str, object]],
        review_handoff_by_id: dict[str, bool] | None = None,
        waiting_by_id: dict[str, bool] | None = None,
        integrated_by_id: dict[str, bool] | None = None,
        work_children_by_id: dict[str, list[dict[str, object]]] | None = None,
    ) -> None:
        self._issues_by_id = issues_by_id
        self._ready_changesets = ready_changesets
        self._descendants = descendants
        self._review_handoff_by_id = review_handoff_by_id or {}
        self._waiting_by_id = waiting_by_id or {}
        self._integrated_by_id = integrated_by_id or {}
        self._work_children_by_id = work_children_by_id or {}

    def show_issue(self, issue_id: str) -> dict[str, object] | None:
        return self._issues_by_id.get(issue_id)

    def ready_changesets(self, *, epic_id: str) -> list[dict[str, object]]:
        del epic_id
        return list(self._ready_changesets)

    def issue_labels(self, issue: dict[str, object]) -> set[str]:
        labels = issue.get("labels")
        if not isinstance(labels, list):
            return set()
        return {str(label) for label in labels if isinstance(label, str)}

    def is_changeset_ready(self, issue: dict[str, object]) -> bool:
        labels = self.issue_labels(issue)
        status = str(issue.get("status") or "").strip().lower()
        return status in {"open", "in_progress"}

    def changeset_waiting_on_review_or_signals(
        self,
        issue: dict[str, object],
        *,
        repo_slug: str | None,
        branch_pr: bool,
        branch_pr_strategy: object,
        git_path: str | None,
    ) -> bool:
        del repo_slug, branch_pr, branch_pr_strategy, git_path
        issue_id = issue.get("id")
        if not isinstance(issue_id, str):
            return False
        return self._waiting_by_id.get(issue_id, False)

    def is_changeset_recovery_candidate(
        self,
        issue: dict[str, object],
        *,
        repo_slug: str | None,
        branch_pr: bool,
        git_path: str | None,
    ) -> bool:
        del issue, repo_slug, branch_pr, git_path
        return False

    def changeset_has_review_handoff_signal(
        self,
        issue: dict[str, object],
        *,
        repo_slug: str | None,
        branch_pr: bool,
        git_path: str | None,
    ) -> bool:
        del repo_slug, branch_pr, git_path
        issue_id = issue.get("id")
        if not isinstance(issue_id, str):
            return False
        return self._review_handoff_by_id.get(issue_id, False)

    def has_open_descendant_changesets(self, changeset_id: str) -> bool:
        del changeset_id
        return False

    def list_descendant_changesets(
        self,
        parent_id: str,
        *,
        include_closed: bool,
    ) -> list[dict[str, object]]:
        del parent_id, include_closed
        return list(self._descendants)

    def list_work_children(
        self,
        parent_id: str,
        *,
        include_closed: bool,
    ) -> list[dict[str, object]]:
        del include_closed
        return list(self._work_children_by_id.get(parent_id, []))

    def changeset_integration_signal(
        self,
        issue: dict[str, object],
        *,
        repo_slug: str | None,
        git_path: str | None,
    ) -> tuple[bool, str | None]:
        del repo_slug, git_path
        issue_id = issue.get("id")
        if not isinstance(issue_id, str):
            return False, None
        return self._integrated_by_id.get(issue_id, False), None

    def is_changeset_in_progress(self, issue: dict[str, object]) -> bool:
        return str(issue.get("status") or "").strip().lower() == "in_progress"


def _changeset(
    issue_id: str,
    *,
    dependencies: list[object] | None = None,
    parent_branch: str | None = None,
    work_branch: str | None = None,
    status: str = "open",
) -> dict[str, object]:
    fields: list[str] = []
    if parent_branch is not None:
        fields.append(f"changeset.parent_branch: {parent_branch}")
    if work_branch is not None:
        fields.append(f"changeset.work_branch: {work_branch}")
    description = "\n".join(fields)
    if description:
        description = f"{description}\n"
    payload: dict[str, object] = {
        "id": issue_id,
        "status": status,
        "labels": [],
        "description": description,
        "type": "task",
    }
    if dependencies is not None:
        payload["dependencies"] = list(dependencies)
    return payload


def _context(*, strategy: str = "sequential") -> startup.NextChangesetContext:
    return startup.NextChangesetContext(
        epic_id="at-epic",
        repo_slug="org/repo",
        branch_pr=True,
        branch_pr_strategy=strategy,
        git_path="git",
    )


def _epic() -> dict[str, object]:
    return {"id": "at-epic", "status": "open", "labels": ["at:epic"]}


def test_next_changeset_service_blocks_stacked_dependency_until_blocker_terminal() -> None:
    blocker = _changeset("at-epic.1", work_branch="feat/at-epic.1")
    downstream = _changeset(
        "at-epic.2",
        dependencies=["at-epic.1"],
        parent_branch="feat/at-epic.1",
        work_branch="feat/at-epic.2",
    )
    service = FakeNextChangesetService(
        issues_by_id={"at-epic": _epic(), blocker["id"]: blocker, downstream["id"]: downstream},
        ready_changesets=[],
        descendants=[blocker, downstream],
        review_handoff_by_id={"at-epic.1": True},
        waiting_by_id={"at-epic.1": True},
    )

    selected = startup.next_changeset_service(context=_context(), service=service)

    assert selected is None


def test_next_changeset_service_allows_downstream_when_dependency_is_integrated() -> None:
    blocker = _changeset("at-epic.1", status="in_progress", work_branch="feat/at-epic.1")
    downstream = _changeset(
        "at-epic.2",
        dependencies=["at-epic.1"],
        parent_branch="feat/at-epic.1",
        work_branch="feat/at-epic.2",
    )
    service = FakeNextChangesetService(
        issues_by_id={"at-epic": _epic(), blocker["id"]: blocker, downstream["id"]: downstream},
        ready_changesets=[],
        descendants=[blocker, downstream],
        review_handoff_by_id={"at-epic.1": True},
        waiting_by_id={"at-epic.1": True},
        integrated_by_id={"at-epic.1": True},
    )

    selected = startup.next_changeset_service(context=_context(), service=service)

    assert selected is not None
    assert selected["id"] == "at-epic.2"


def test_next_changeset_service_blocks_join_dependency_until_all_integrated() -> None:
    dependency_one = _changeset("at-epic.1", status="closed", work_branch="feat/at-epic.1")
    dependency_two = _changeset(
        "at-epic.2",
        status="closed",
        dependencies=["at-epic.1"],
        work_branch="feat/at-epic.2",
    )
    downstream = _changeset(
        "at-epic.3",
        dependencies=["at-epic.1", "at-epic.2"],
        parent_branch="feat/at-epic.2",
        work_branch="feat/at-epic.3",
    )
    service = FakeNextChangesetService(
        issues_by_id={
            "at-epic": _epic(),
            dependency_one["id"]: dependency_one,
            dependency_two["id"]: dependency_two,
            downstream["id"]: downstream,
        },
        ready_changesets=[],
        descendants=[dependency_one, dependency_two, downstream],
        integrated_by_id={"at-epic.2": True},
    )

    selected = startup.next_changeset_service(context=_context(), service=service)

    assert selected is None


def test_next_changeset_service_allows_join_dependency_once_all_integrated() -> None:
    dependency_one = _changeset("at-epic.1", status="closed", work_branch="feat/at-epic.1")
    dependency_two = _changeset(
        "at-epic.2",
        status="closed",
        dependencies=["at-epic.1"],
        work_branch="feat/at-epic.2",
    )
    downstream = _changeset(
        "at-epic.3",
        dependencies=["at-epic.1", "at-epic.2"],
        parent_branch="feat/at-epic.2",
        work_branch="feat/at-epic.3",
    )
    service = FakeNextChangesetService(
        issues_by_id={
            "at-epic": _epic(),
            dependency_one["id"]: dependency_one,
            dependency_two["id"]: dependency_two,
            downstream["id"]: downstream,
        },
        ready_changesets=[],
        descendants=[dependency_one, dependency_two, downstream],
        integrated_by_id={"at-epic.1": True, "at-epic.2": True},
    )

    selected = startup.next_changeset_service(context=_context(), service=service)

    assert selected is not None
    assert selected["id"] == "at-epic.3"


def test_next_changeset_service_blocks_when_review_handoff_evidence_missing() -> None:
    blocker = _changeset("at-epic.1", work_branch="feat/at-epic.1")
    downstream = _changeset(
        "at-epic.2",
        dependencies=["at-epic.1"],
        parent_branch="feat/at-epic.1",
        work_branch="feat/at-epic.2",
    )
    service = FakeNextChangesetService(
        issues_by_id={"at-epic": _epic(), blocker["id"]: blocker, downstream["id"]: downstream},
        ready_changesets=[],
        descendants=[blocker, downstream],
        review_handoff_by_id={"at-epic.1": False},
        waiting_by_id={"at-epic.1": True},
    )

    selected = startup.next_changeset_service(context=_context(), service=service)

    assert selected is None


def test_next_changeset_service_resume_review_selects_waiting_handoff() -> None:
    waiting = _changeset("at-epic.1", status="in_progress", work_branch="feat/at-epic.1")
    service = FakeNextChangesetService(
        issues_by_id={"at-epic": _epic(), waiting["id"]: waiting},
        ready_changesets=[],
        descendants=[waiting],
        review_handoff_by_id={"at-epic.1": True},
        waiting_by_id={"at-epic.1": True},
    )
    context = startup.NextChangesetContext(
        epic_id="at-epic",
        repo_slug="org/repo",
        branch_pr=True,
        branch_pr_strategy="sequential",
        git_path="git",
        resume_review=True,
    )

    selected = startup.next_changeset_service(context=context, service=service)

    assert selected is not None
    assert selected["id"] == "at-epic.1"


def test_next_changeset_service_resume_review_requires_handoff_signal() -> None:
    waiting = _changeset("at-epic.1", status="in_progress", work_branch="feat/at-epic.1")
    service = FakeNextChangesetService(
        issues_by_id={"at-epic": _epic(), waiting["id"]: waiting},
        ready_changesets=[],
        descendants=[waiting],
        review_handoff_by_id={"at-epic.1": False},
        waiting_by_id={"at-epic.1": True},
    )
    context = startup.NextChangesetContext(
        epic_id="at-epic",
        repo_slug="org/repo",
        branch_pr=True,
        branch_pr_strategy="sequential",
        git_path="git",
        resume_review=True,
    )

    selected = startup.next_changeset_service(context=context, service=service)

    assert selected is None


def test_next_changeset_service_accepts_issue_type_leaf_without_changeset_label() -> None:
    issue_type_changeset = {
        "id": "at-epic.1",
        "status": "open",
        "issue_type": "task",
        "labels": [],
        "parent": "at-epic",
    }
    service = FakeNextChangesetService(
        issues_by_id={
            "at-epic": {
                "id": "at-epic",
                "status": "open",
                "issue_type": "epic",
                "labels": ["at:epic"],
            },
            issue_type_changeset["id"]: issue_type_changeset,
        },
        ready_changesets=[],
        descendants=[issue_type_changeset],
    )

    selected = startup.next_changeset_service(context=_context(), service=service)

    assert selected is not None
    assert selected["id"] == "at-epic.1"


def test_next_changeset_service_blocks_when_branch_lineage_is_broken() -> None:
    blocker = _changeset("at-epic.1", work_branch="feat/at-epic.1")
    downstream = _changeset(
        "at-epic.2",
        dependencies=["at-epic.1"],
        parent_branch="feat/not-the-blocker",
        work_branch="feat/at-epic.2",
    )
    service = FakeNextChangesetService(
        issues_by_id={"at-epic": _epic(), blocker["id"]: blocker, downstream["id"]: downstream},
        ready_changesets=[],
        descendants=[blocker, downstream],
        review_handoff_by_id={"at-epic.1": True},
        waiting_by_id={"at-epic.1": True},
    )

    selected = startup.next_changeset_service(context=_context(), service=service)

    assert selected is None


def test_next_changeset_service_keeps_cross_epic_dependencies_blocked() -> None:
    blocker = _changeset("at-other.1", work_branch="feat/at-other.1")
    downstream = _changeset(
        "at-epic.2",
        dependencies=["at-other.1"],
        parent_branch="feat/at-other.1",
        work_branch="feat/at-epic.2",
    )
    service = FakeNextChangesetService(
        issues_by_id={"at-epic": _epic(), blocker["id"]: blocker, downstream["id"]: downstream},
        ready_changesets=[],
        descendants=[downstream],
        review_handoff_by_id={"at-other.1": True},
    )

    selected = startup.next_changeset_service(context=_context(), service=service)

    assert selected is None


@pytest.mark.parametrize(
    "parent_dependency",
    [
        {"relation": "parent-child", "id": "at-epic"},
        {"dependencyType": "parent-child", "issue": {"id": "at-epic"}},
        {"dependency_type": "parent-child", "id": "at-epic"},
        {"dependency_type": "parent-child", "issue": {"id": "at-epic"}},
        {"type": "parent-child", "depends_on_id": "at-epic"},
        "at-epic (open, dependency_type=parent_child)",
    ],
)
def test_next_changeset_service_ignores_parent_child_dependencies(
    parent_dependency: object,
) -> None:
    downstream = _changeset(
        "at-epic.1",
        dependencies=[parent_dependency],
        work_branch="feat/at-epic.1",
    )
    service = FakeNextChangesetService(
        issues_by_id={"at-epic": _epic(), downstream["id"]: downstream},
        ready_changesets=[],
        descendants=[downstream],
    )

    selected = startup.next_changeset_service(context=_context(), service=service)

    assert selected is not None
    assert selected["id"] == "at-epic.1"


def test_next_changeset_service_selects_descendant_when_explicit_epic_dependency_open() -> None:
    epic_changeset = {
        "id": "at-epic",
        "status": "open",
        "labels": ["at:epic"],
        "dependencies": ["at-epic.1"],
    }
    blocker = _changeset("at-epic.1", status="open", work_branch="feat/at-epic.1")
    service = FakeNextChangesetService(
        issues_by_id={"at-epic": epic_changeset, blocker["id"]: blocker},
        ready_changesets=[],
        descendants=[blocker],
    )

    selected = startup.next_changeset_service(context=_context(), service=service)

    assert selected is not None
    assert selected["id"] == "at-epic.1"


def test_next_changeset_service_selects_child_when_explicit_epic_has_dual_labels() -> None:
    explicit_epic = {
        "id": "at-epic",
        "status": "open",
        "labels": ["at:epic"],
    }
    child = _changeset("at-epic.1", status="open", work_branch="feat/at-epic.1")
    service = FakeNextChangesetService(
        issues_by_id={"at-epic": explicit_epic, child["id"]: child},
        ready_changesets=[],
        descendants=[child],
    )

    selected = startup.next_changeset_service(context=_context(), service=service)

    assert selected is not None
    assert selected["id"] == "at-epic.1"


def test_next_changeset_service_blocks_depends_on_id_payload_dependency() -> None:
    downstream = _changeset(
        "at-epic.2",
        dependencies=[{"depends_on_id": "at-epic.1"}],
        work_branch="feat/at-epic.2",
    )
    blocker = _changeset("at-epic.1", status="open", work_branch="feat/at-epic.1")
    service = FakeNextChangesetService(
        issues_by_id={"at-epic": _epic(), blocker["id"]: blocker, downstream["id"]: downstream},
        ready_changesets=[{"id": "at-epic.2", "status": "open", "labels": []}],
        descendants=[downstream],
    )

    selected = startup.next_changeset_service(context=_context(), service=service)

    assert selected is None


def test_next_changeset_service_sequential_blocks_closed_dependency_without_merge_signal() -> None:
    blocker = _changeset("at-epic.1", status="closed", work_branch="feat/at-epic.1")
    downstream = _changeset(
        "at-epic.2",
        dependencies=["at-epic.1"],
        parent_branch="feat/at-epic.1",
        work_branch="feat/at-epic.2",
    )
    service = FakeNextChangesetService(
        issues_by_id={"at-epic": _epic(), blocker["id"]: blocker, downstream["id"]: downstream},
        ready_changesets=[{"id": "at-epic.2", "status": "open", "labels": ["at:changeset"]}],
        descendants=[blocker, downstream],
    )

    selected = startup.next_changeset_service(
        context=_context(strategy="sequential"), service=service
    )

    assert selected is None


def test_next_changeset_service_sequential_accepts_closed_dependency_with_merged_label() -> None:
    blocker = _changeset("at-epic.1", status="closed", work_branch="feat/at-epic.1")
    blocker["labels"] = ["at:changeset", "cs:merged"]
    downstream = _changeset(
        "at-epic.2",
        dependencies=["at-epic.1"],
        parent_branch="feat/at-epic.1",
        work_branch="feat/at-epic.2",
    )
    service = FakeNextChangesetService(
        issues_by_id={"at-epic": _epic(), blocker["id"]: blocker, downstream["id"]: downstream},
        ready_changesets=[{"id": "at-epic.2", "status": "open", "labels": ["at:changeset"]}],
        descendants=[blocker, downstream],
    )

    selected = startup.next_changeset_service(
        context=_context(strategy="sequential"), service=service
    )

    assert selected is not None
    assert selected["id"] == "at-epic.2"


def test_next_changeset_service_non_sequential_keeps_closed_dependency_terminal() -> None:
    blocker = _changeset("at-epic.1", status="closed", work_branch="feat/at-epic.1")
    downstream = _changeset(
        "at-epic.2",
        dependencies=["at-epic.1"],
        parent_branch="feat/at-epic.1",
        work_branch="feat/at-epic.2",
    )
    service = FakeNextChangesetService(
        issues_by_id={"at-epic": _epic(), blocker["id"]: blocker, downstream["id"]: downstream},
        ready_changesets=[{"id": "at-epic.2", "status": "open", "labels": ["at:changeset"]}],
        descendants=[blocker, downstream],
    )

    selected = startup.next_changeset_service(
        context=_context(strategy="on-ready"), service=service
    )

    assert selected is not None
    assert selected["id"] == "at-epic.2"


def test_next_changeset_service_rehydrates_sparse_ready_candidates() -> None:
    blocker = _changeset("at-epic.1", status="open", work_branch="feat/at-epic.1")
    downstream = _changeset(
        "at-epic.2",
        dependencies=[{"depends_on_id": "at-epic.1"}],
        work_branch="feat/at-epic.2",
    )
    sparse_ready = {
        "id": "at-epic.2",
        "status": "in_progress",
        "labels": [],
        "type": "task",
    }
    service = FakeNextChangesetService(
        issues_by_id={"at-epic": _epic(), blocker["id"]: blocker, downstream["id"]: downstream},
        ready_changesets=[sparse_ready],
        descendants=[blocker, downstream],
    )

    selected = startup.next_changeset_service(context=_context(), service=service)

    assert selected is not None
    assert selected["id"] == "at-epic.1"

import pytest

from atelier.worker import selection


def test_filter_epics_uses_status_contract_for_unassigned_and_assigned() -> None:
    issues = [
        {"id": "at-1", "status": "open", "labels": ["at:epic"], "assignee": None},
        {"id": "at-2", "status": "deferred", "labels": ["at:epic"], "assignee": None},
        {"id": "at-4", "status": "open", "labels": ["at:epic"], "assignee": None},
        {
            "id": "at-3",
            "status": "in_progress",
            "labels": ["at:epic"],
            "assignee": "worker/a",
        },
    ]

    ready = selection.filter_epics(
        issues,
        require_unassigned=True,
        allow_hooked=False,
        skip_draft=True,
    )
    assigned = selection.filter_epics(
        issues,
        assignee="worker/a",
        allow_hooked=True,
        skip_draft=True,
    )

    assert [item["id"] for item in ready] == ["at-1", "at-4"]
    assert [item["id"] for item in assigned] == ["at-3"]


def test_filter_epics_requires_at_epic_label_for_executable_identity() -> None:
    issues = [
        {
            "id": "at-typed-epic",
            "status": "open",
            "issue_type": "epic",
            "labels": [],
            "assignee": None,
        }
    ]

    ready = selection.filter_epics(
        issues,
        require_unassigned=True,
        allow_hooked=False,
        skip_draft=True,
    )

    assert ready == []


def test_has_executable_identity_requires_at_epic_label() -> None:
    assert (
        selection.has_executable_identity(
            {
                "id": "at-epic",
                "status": "open",
                "issue_type": "epic",
                "labels": ["at:epic"],
            }
        )
        is True
    )
    assert (
        selection.has_executable_identity(
            {
                "id": "at-unlabeled",
                "status": "open",
                "issue_type": "epic",
                "labels": [],
            }
        )
        is False
    )


def test_sort_by_created_at_orders_oldest_first() -> None:
    issues = [
        {"id": "at-2", "created_at": "2026-02-22T00:00:00+00:00"},
        {"id": "at-1", "created_at": "2026-02-21T00:00:00+00:00"},
    ]

    ordered = selection.sort_by_created_at(issues)

    assert [item["id"] for item in ordered] == ["at-1", "at-2"]


def test_sort_by_recency_prefers_updated_at_then_created_at() -> None:
    issues = [
        {
            "id": "at-2",
            "created_at": "2026-02-20T00:00:00+00:00",
            "updated_at": "2026-02-20T00:01:00+00:00",
        },
        {"id": "at-1", "created_at": "2026-02-20T00:02:00+00:00"},
    ]

    ordered = selection.sort_by_recency(issues)

    assert [item["id"] for item in ordered] == ["at-1", "at-2"]


def test_select_epic_auto_prefers_ready_before_assigned() -> None:
    issues = [
        {
            "id": "at-assigned",
            "status": "in_progress",
            "labels": ["at:epic"],
            "assignee": "worker/1",
            "created_at": "2026-02-22T00:00:00+00:00",
        },
        {
            "id": "at-ready",
            "status": "open",
            "labels": ["at:epic"],
            "assignee": None,
            "created_at": "2026-02-21T00:00:00+00:00",
        },
    ]

    selected = selection.select_epic_auto(
        issues,
        agent_id="worker/1",
        is_actionable=lambda issue_id: issue_id != "at-assigned",
    )

    assert selected == "at-ready"


def test_select_epic_prompt_supports_assume_yes() -> None:
    issues = [
        {
            "id": "at-ready",
            "status": "open",
            "title": "Ready epic",
            "labels": ["at:epic"],
            "assignee": None,
        },
        {
            "id": "at-resume",
            "status": "in_progress",
            "title": "Resume epic",
            "labels": ["at:epic"],
            "assignee": "worker/1",
            "updated_at": "2026-02-22T00:00:00+00:00",
        },
    ]

    selected = selection.select_epic_prompt(
        issues,
        agent_id="worker/1",
        is_actionable=lambda issue_id: True,
        extract_root_branch=lambda issue: str(issue.get("id")),
        select_fn=lambda _title, options: options[-1],
        assume_yes=True,
    )

    assert selected == "at-ready"


def test_stale_family_assigned_epics_reclaims_inactive_assignees_across_families() -> None:
    issues = [
        {
            "id": "at-stale",
            "status": "in_progress",
            "labels": ["at:epic"],
            "assignee": "atelier/worker/codex/p111",
            "created_at": "2026-02-20T00:00:00+00:00",
        },
        {
            "id": "at-active",
            "status": "in_progress",
            "labels": ["at:epic"],
            "assignee": "atelier/worker/codex/p222",
            "created_at": "2026-02-21T00:00:00+00:00",
        },
        {
            "id": "at-other-family",
            "status": "in_progress",
            "labels": ["at:epic"],
            "assignee": "atelier/worker/other/p333",
            "created_at": "2026-02-22T00:00:00+00:00",
        },
    ]

    stale = selection.stale_family_assigned_epics(
        issues,
        agent_id="atelier/worker/codex/p999",
        is_session_active=lambda assignee: assignee.endswith("/p222"),
    )

    assert [item["id"] for item in stale] == ["at-stale", "at-other-family"]


def test_select_epic_from_ready_changesets_uses_epic_for_child_issue() -> None:
    issues = [
        {"id": "at-epic", "status": "open", "labels": ["at:epic"], "assignee": None},
    ]
    ready_changesets = [
        {"id": "at-epic.1", "created_at": "2026-02-20T00:00:00+00:00"},
    ]

    selected = selection.select_epic_from_ready_changesets(
        issues=issues,
        ready_changesets=ready_changesets,
        is_actionable=lambda issue_id: issue_id == "at-epic",
    )

    assert selected == "at-epic"


@pytest.mark.parametrize("parent_value", [{"id": "at-epic"}, "at-epic"])
def test_select_epic_from_ready_changesets_uses_graph_parent_for_non_dotted_child_id(
    parent_value: object,
) -> None:
    issues = [
        {"id": "at-epic", "status": "open", "labels": ["at:epic"], "assignee": None},
    ]
    ready_changesets = [
        {
            "id": "cs-ready-1",
            "parent": parent_value,
            "created_at": "2026-02-20T00:00:00+00:00",
        },
    ]

    selected = selection.select_epic_from_ready_changesets(
        issues=issues,
        ready_changesets=ready_changesets,
        is_actionable=lambda issue_id: issue_id == "at-epic",
    )

    assert selected == "at-epic"


def test_select_epic_from_ready_changesets_supports_mixed_child_id_formats() -> None:
    issues = [
        {"id": "at-epic-a", "status": "open", "labels": ["at:epic"], "assignee": None},
        {"id": "at-epic-b", "status": "open", "labels": ["at:epic"], "assignee": None},
    ]
    ready_changesets = [
        {
            "id": "at-epic-b.1",
            "created_at": "2026-02-20T00:00:00+00:00",
        },
        {
            "id": "cs-a1",
            "parent": {"id": "at-epic-a"},
            "created_at": "2026-02-21T00:00:00+00:00",
        },
    ]

    selected = selection.select_epic_from_ready_changesets(
        issues=issues,
        ready_changesets=ready_changesets,
        is_actionable=lambda issue_id: issue_id == "at-epic-a",
    )

    assert selected == "at-epic-a"


@pytest.mark.parametrize(
    "parent_dependency",
    [
        {"dependency_type": "parent-child", "depends_on_id": "at-epic"},
        {"type": "parent-child", "depends_on_id": "at-epic"},
    ],
)
def test_select_epic_from_ready_changesets_reads_parent_from_parent_child_dependency_shapes(
    parent_dependency: object,
) -> None:
    issues = [
        {"id": "at-epic", "status": "open", "labels": ["at:epic"], "assignee": None},
    ]
    ready_changesets = [
        {
            "id": "cs-ready-1",
            "dependencies": [parent_dependency],
            "created_at": "2026-02-20T00:00:00+00:00",
        },
    ]

    selected = selection.select_epic_from_ready_changesets(
        issues=issues,
        ready_changesets=ready_changesets,
        is_actionable=lambda issue_id: issue_id == "at-epic",
    )

    assert selected == "at-epic"


def test_filter_epics_skips_planner_owned_executable_issue() -> None:
    issues = [
        {
            "id": "at-planner",
            "status": "open",
            "labels": ["at:epic"],
            "assignee": "atelier/planner/codex/p333",
        },
        {
            "id": "at-worker",
            "status": "open",
            "labels": ["at:epic"],
            "assignee": None,
        },
    ]

    ready = selection.filter_epics(
        issues,
        require_unassigned=True,
        allow_hooked=False,
        skip_draft=True,
    )

    assert [item["id"] for item in ready] == ["at-worker"]


def test_select_epic_from_ready_changesets_skips_planner_owned_epic() -> None:
    issues = [
        {
            "id": "at-epic",
            "labels": ["at:epic"],
            "assignee": "atelier/planner/codex/p333",
        },
    ]
    ready_changesets = [{"id": "at-epic.1"}]

    selected = selection.select_epic_from_ready_changesets(
        issues=issues,
        ready_changesets=ready_changesets,
        is_actionable=lambda issue_id: issue_id == "at-epic",
    )

    assert selected is None


def test_select_epic_from_ready_changesets_skips_unlabeled_top_level_work() -> None:
    issues: list[dict[str, object]] = []
    ready_changesets = [
        {"id": "at-unlabeled", "status": "open", "issue_type": "epic", "labels": []},
    ]

    selected = selection.select_epic_from_ready_changesets(
        issues=issues,
        ready_changesets=ready_changesets,
        is_actionable=lambda issue_id: issue_id == "at-unlabeled",
    )

    assert selected is None


def test_has_planner_executable_assignee_ignores_message_bead() -> None:
    issue = {
        "id": "at-msg-1",
        "labels": ["at:message"],
        "assignee": "atelier/planner/codex/p333",
    }

    assert selection.has_planner_executable_assignee(issue) is False

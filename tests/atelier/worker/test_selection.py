from atelier.worker import selection


def test_filter_epics_excludes_drafts_and_requires_unassigned() -> None:
    issues = [
        {"id": "at-1", "status": "open", "labels": ["at:epic"], "assignee": None},
        {"id": "at-2", "status": "open", "labels": ["at:draft"], "assignee": None},
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

    assert [item["id"] for item in ready] == ["at-1"]
    assert [item["id"] for item in assigned] == ["at-3"]


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


def test_stale_family_assigned_epics_filters_to_inactive_family_members() -> None:
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
            "assignee": "atelier/planner/codex/p333",
            "created_at": "2026-02-22T00:00:00+00:00",
        },
    ]

    stale = selection.stale_family_assigned_epics(
        issues,
        agent_id="atelier/worker/codex/p999",
        is_session_active=lambda assignee: assignee.endswith("/p222"),
    )

    assert [item["id"] for item in stale] == ["at-stale"]


def test_select_epic_from_ready_changesets_uses_epic_for_child_issue() -> None:
    issues = [
        {"id": "at-epic", "labels": ["at:epic"], "assignee": None},
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

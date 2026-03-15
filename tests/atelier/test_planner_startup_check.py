from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from atelier import messages, planner_startup_check
from atelier.store import StartupMessageRecord, build_atelier_store
from atelier.testing.beads import (
    IssueFixtureBuilder,
    build_in_memory_beads_client,
)

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "planner_startup_check"


def _parity(
    *,
    active_top_level_work_count: int = 1,
    indexed_active_epic_count: int = 1,
    missing_executable_identity: tuple[object, ...] = (),
    missing_from_index: tuple[str, ...] = (),
    in_parity: bool = True,
) -> SimpleNamespace:
    return SimpleNamespace(
        active_top_level_work_count=active_top_level_work_count,
        indexed_active_epic_count=indexed_active_epic_count,
        missing_executable_identity=missing_executable_identity,
        missing_from_index=missing_from_index,
        in_parity=in_parity,
    )


def test_startup_command_plan_order_is_fixed() -> None:
    plan = planner_startup_check.startup_command_plan()

    assert [(step.name, step.inputs, step.output) for step in plan] == [
        ("list_inbox_unread_messages", ("agent_id",), "inbox_messages"),
        ("list_queue_unread_messages", (), "queued_messages"),
        ("list_indexed_epics", (), "epics"),
        ("compute_epic_discovery_parity", ("epics",), "parity_report"),
    ]


def test_validate_startup_list_invocation_rejects_forbidden_flag() -> None:
    with pytest.raises(ValueError, match="forbidden startup bd invocation flag"):
        planner_startup_check.validate_startup_list_invocation(
            ["list", "--db", "/tmp/beads.db", "--label", "at:message"]
        )


def test_validate_startup_list_invocation_rejects_forbidden_beads_dir_flag() -> None:
    with pytest.raises(ValueError, match="forbidden startup bd invocation flag"):
        planner_startup_check.validate_startup_list_invocation(
            ["list", "--beads-dir", "/tmp/.beads", "--label", "at:message"]
        )


def test_validate_startup_list_invocation_rejects_unsupported_flag() -> None:
    with pytest.raises(ValueError, match="unsupported startup bd list flag"):
        planner_startup_check.validate_startup_list_invocation(
            ["list", "--label", "at:message", "--status", "open"]
        )


def test_execute_startup_command_plan_runs_steps_in_order() -> None:
    calls: list[str] = []

    class _FakeHelper:
        def list_inbox_messages(self, *_args, **_kwargs):
            calls.append("inbox")
            return [{"id": "at-msg-1", "title": "Message"}]

        def list_queue_messages(self, *_args, **_kwargs):
            calls.append("queue")
            return [{"id": "at-q-1", "title": "Queued", "queue": "planner", "claimed_by": ""}]

        def list_epics(self, *_args, **_kwargs):
            calls.append("epics")
            return [{"id": "at-1", "title": "Epic", "status": "open"}]

        def epic_discovery_parity_report(self, *_args, **_kwargs):
            calls.append("parity")
            return _parity()

    helper = _FakeHelper()

    result = planner_startup_check.execute_startup_command_plan(
        "atelier/planner/example",
        helper=helper,  # type: ignore[arg-type]
    )

    assert calls == ["inbox", "queue", "epics", "parity"]
    assert [issue["id"] for issue in result.inbox_messages] == ["at-msg-1"]
    assert [issue["id"] for issue in result.epics] == ["at-1"]


def test_startup_helper_surfaces_threaded_planner_decisions_without_assignee() -> None:
    helper = planner_startup_check.StartupBeadsInvocationHelper(
        beads_root=Path("/beads"),
        cwd=Path("/repo"),
    )
    fake_message = StartupMessageRecord(
        id="at-msg-1",
        title="NEEDS-DECISION: Publish incomplete (at-epic.1)",
        body="Confirm the next publish step.",
        thread_id="at-epic.1",
        thread_kind="changeset",
        kind="notification",
        audience=("planner",),
        queue=None,
        claimed_by=None,
        blocking_roles=("planner",),
    )

    class _FakeStore:
        async def list_startup_messages(self, _query):
            return (fake_message,)

    object.__setattr__(helper, "_store_cache", _FakeStore())

    messages_for_planner = helper.list_inbox_messages("atelier/planner/codex/p200")

    assert [issue["id"] for issue in messages_for_planner] == ["at-msg-1"]
    assert "audience=planner" in str(messages_for_planner[0]["title"])
    assert "at-epic.1" in str(messages_for_planner[0]["title"])


def test_startup_helper_uses_typed_startup_message_projection() -> None:
    helper = planner_startup_check.StartupBeadsInvocationHelper(
        beads_root=Path("/beads"),
        cwd=Path("/repo"),
    )

    fake_message = StartupMessageRecord(
        id="at-msg-assigned",
        title="Assigned planner note",
        body="Direct assignee routing.",
        thread_id=None,
        thread_kind=None,
        kind=None,
        audience=("planner",),
        queue=None,
        claimed_by=None,
        blocking_roles=(),
    )

    class _FakeStore:
        async def list_startup_messages(self, _query):
            return (fake_message,)

    object.__setattr__(helper, "_store_cache", _FakeStore())

    messages_for_planner = helper.list_inbox_messages("atelier/planner/codex/p200")

    assert [issue["id"] for issue in messages_for_planner] == ["at-msg-assigned"]


def test_startup_helper_uses_in_memory_backend_for_inbox_queue_and_epic_queries(
    monkeypatch,
    tmp_path: Path,
) -> None:
    beads_root = tmp_path / ".beads"
    repo_root = tmp_path / "repo"
    beads_root.mkdir()
    repo_root.mkdir()
    helper = planner_startup_check.StartupBeadsInvocationHelper(
        beads_root=beads_root,
        cwd=repo_root,
    )
    builder = IssueFixtureBuilder()
    client, _store = build_in_memory_beads_client(
        issues=(
            builder.issue(
                "at-msg-routed",
                title="NEEDS-DECISION: Publish incomplete (at-epic.1)",
                issue_type="message",
                labels=("at:message", "at:unread"),
                description=messages.render_message(
                    {
                        "from": "atelier/worker/codex/p100",
                        "thread": "at-epic.1",
                        "thread_kind": "changeset",
                        "audience": ["planner"],
                        "kind": "notification",
                    },
                    "Confirm the next publish step.",
                ),
            ),
            builder.issue(
                "at-msg-assigned",
                title="Assigned planner note",
                issue_type="message",
                labels=("at:message", "at:unread"),
                assignee="atelier/planner/codex/p200",
                description="Direct assignee routing.",
            ),
            builder.issue(
                "at-msg-queue",
                title="Queued planner work",
                issue_type="message",
                labels=("at:message", "at:unread"),
                description=messages.render_message(
                    {
                        "from": "atelier/worker/codex/p100",
                        "queue": "planner",
                    },
                    "Queue this follow-up.",
                ),
            ),
            builder.issue(
                "at-msg-worker",
                title="Worker-only thread",
                issue_type="message",
                labels=("at:message", "at:unread"),
                description=messages.render_message(
                    {
                        "from": "atelier/worker/codex/p100",
                        "thread": "at-worker.1",
                        "thread_kind": "changeset",
                        "audience": ["worker"],
                    },
                    "Worker follow-up.",
                ),
            ),
            builder.issue(
                "at-epic-open",
                title="Open epic",
                issue_type="epic",
                labels=("at:epic",),
                status="open",
                dependencies=("at-dep",),
                extra_fields={
                    "dependencies": [
                        {
                            "issue_id": "at-epic-open",
                            "depends_on_id": "at-dep",
                            "type": "blocks",
                        }
                    ]
                },
            ),
            builder.issue(
                "at-epic-closed",
                title="Closed epic",
                issue_type="epic",
                labels=("at:epic",),
                status="closed",
            ),
            builder.issue(
                "at-dep",
                title="Epic dependency",
                issue_type="task",
                status="in_progress",
            ),
        )
    )
    monkeypatch.setattr(
        planner_startup_check,
        "_build_store",
        lambda **_kwargs: build_atelier_store(beads=client),
    )
    monkeypatch.setattr(planner_startup_check, "_build_beads_client", lambda **_kwargs: client)

    inbox_messages = helper.list_inbox_messages("atelier/planner/codex/p200")
    queued_messages = helper.list_queue_messages(queue="planner")
    epics = helper.list_epics()

    assert [issue["id"] for issue in inbox_messages] == [
        "at-msg-routed",
        "at-msg-assigned",
    ]
    assert "audience=planner" in str(inbox_messages[0]["title"])
    assert "changeset=at-epic.1" in str(inbox_messages[0]["title"])
    assert [issue["id"] for issue in queued_messages] == ["at-msg-queue"]
    assert queued_messages[0]["claimed_by"] is None
    assert queued_messages[0]["queue"] == "planner"
    assert [issue["id"] for issue in epics] == ["at-epic-open"]
    assert epics[0]["dependencies"] == [{"id": "at-dep", "status": "in_progress"}]


def test_startup_helper_lists_epics_without_changesets() -> None:
    helper = planner_startup_check.StartupBeadsInvocationHelper(
        beads_root=Path("/beads"),
        cwd=Path("/repo"),
    )
    captured_query = None

    class _FakeStore:
        async def list_epics(self, query):
            nonlocal captured_query
            captured_query = query
            return ()

    object.__setattr__(helper, "_store_cache", _FakeStore())

    assert helper.list_epics(include_closed=False) == []
    assert captured_query is not None
    assert captured_query.include_closed is False
    assert captured_query.include_changesets is False


def test_startup_helper_lists_leaf_descendants_with_in_memory_backend(
    monkeypatch,
    tmp_path: Path,
) -> None:
    beads_root = tmp_path / ".beads"
    repo_root = tmp_path / "repo"
    beads_root.mkdir()
    repo_root.mkdir()
    helper = planner_startup_check.StartupBeadsInvocationHelper(
        beads_root=beads_root,
        cwd=repo_root,
    )
    builder = IssueFixtureBuilder()
    client, _store = build_in_memory_beads_client(
        issues=(
            builder.issue(
                "at-epic",
                title="Epic",
                issue_type="epic",
                labels=("at:epic",),
                status="in_progress",
            ),
            builder.issue(
                "at-epic.1",
                title="Container changeset",
                parent="at-epic",
                issue_type="task",
                status="in_progress",
            ),
            builder.issue(
                "at-epic.1.1",
                title="Leaf changeset",
                parent="at-epic.1",
                issue_type="task",
                status="open",
            ),
            builder.issue(
                "at-epic.2",
                title="Second leaf",
                parent="at-epic",
                issue_type="task",
                status="open",
            ),
            builder.issue(
                "at-msg-ignored",
                title="Thread message",
                parent="at-epic",
                issue_type="message",
                labels=("at:message",),
                status="open",
            ),
        )
    )
    monkeypatch.setattr(
        planner_startup_check,
        "_build_store",
        lambda **_kwargs: build_atelier_store(beads=client),
    )

    descendants = helper.list_descendant_changesets("at-epic")

    assert [issue["id"] for issue in descendants] == ["at-epic.2", "at-epic.1.1"]


def test_build_startup_triage_model_normalizes_and_sorts_sections() -> None:
    command_result = planner_startup_check.StartupCommandResult(
        inbox_messages=[
            {"id": "at-msg-2", "title": "Beta"},
            {"id": "at-msg-1", "title": "Alpha"},
        ],
        queued_messages=[
            {"id": "at-q-2", "title": "Second", "queue": "planner", "claimed_by": "worker-1"},
            {"id": "at-q-1", "title": "First", "queue": "planner", "claimed_by": ""},
        ],
        epics=[
            {"id": "at-2", "title": "Beta epic", "status": "blocked"},
            {"id": "at-1", "title": "Alpha epic", "status": "open"},
        ],
        parity_report=_parity(active_top_level_work_count=2, indexed_active_epic_count=2),
    )

    model = planner_startup_check.build_startup_triage_model(
        beads_root=Path("/beads"),
        command_result=command_result,
        deferred_groups=[
            (
                {"id": "at-2", "title": "Beta epic", "status": "blocked"},
                [
                    {"id": "at-2.2", "title": "Second deferred", "status": "deferred"},
                    {"id": "at-2.1", "title": "First deferred", "status": "deferred"},
                ],
            ),
            (
                {"id": "at-1", "title": "Alpha epic", "status": "open"},
                [{"id": "at-1.1", "title": "Alpha deferred", "status": "deferred"}],
            ),
        ],
        deferred_scan_limit=25,
        deferred_scan_skipped_epics=0,
        epic_list_markdown="Epics by state:\n- (none)",
    )

    assert [message.issue_id for message in model.inbox_messages] == ["at-msg-1", "at-msg-2"]
    assert [message.issue_id for message in model.queued_messages] == ["at-q-1", "at-q-2"]
    assert [group.epic.issue_id for group in model.deferred_changesets] == ["at-1", "at-2"]
    assert [issue.issue_id for issue in model.deferred_changesets[1].changesets] == [
        "at-2.1",
        "at-2.2",
    ]


def test_render_startup_triage_markdown_snapshot_empty() -> None:
    command_result = planner_startup_check.StartupCommandResult(
        inbox_messages=[],
        queued_messages=[],
        epics=[],
        parity_report=_parity(
            active_top_level_work_count=0,
            indexed_active_epic_count=0,
            in_parity=True,
        ),
    )

    model = planner_startup_check.build_startup_triage_model(
        beads_root=Path("/beads"),
        command_result=command_result,
        deferred_groups=[],
        deferred_scan_limit=25,
        deferred_scan_skipped_epics=0,
        epic_list_markdown="Epics by state:\n- (none)",
    )

    rendered = planner_startup_check.render_startup_triage_markdown(model)
    expected = (FIXTURES_DIR / "startup_triage_empty.txt").read_text(encoding="utf-8").rstrip("\n")
    assert rendered == expected


def test_render_startup_triage_markdown_snapshot_full_state() -> None:
    parity = _parity(
        active_top_level_work_count=3,
        indexed_active_epic_count=2,
        in_parity=False,
        missing_executable_identity=(
            SimpleNamespace(
                issue_id="at-missing-2",
                status="open",
                issue_type="epic",
                labels=("zeta", "alpha"),
                remediation_command="bd update at-missing-2 --type epic --add-label at:epic",
            ),
            SimpleNamespace(
                issue_id="at-missing-1",
                status="",
                issue_type="",
                labels=(),
                remediation_command="",
            ),
        ),
        missing_from_index=("at-z", "at-a"),
    )
    command_result = planner_startup_check.StartupCommandResult(
        inbox_messages=[
            {"id": "at-msg-2", "title": "Second"},
            {"id": "at-msg-1", "title": "First"},
        ],
        queued_messages=[
            {"id": "at-q-2", "title": "Queued second", "queue": "planner", "claimed_by": "worker"},
            {"id": "at-q-1", "title": "Queued first", "queue": "planner", "claimed_by": ""},
        ],
        epics=[
            {"id": "at-2", "title": "Blocked epic", "status": "blocked"},
            {"id": "at-1", "title": "Open epic", "status": "open"},
            {"id": "at-3", "title": "Another epic", "status": "in_progress"},
        ],
        parity_report=parity,
    )

    model = planner_startup_check.build_startup_triage_model(
        beads_root=Path("/beads"),
        command_result=command_result,
        deferred_groups=[
            (
                {"id": "at-2", "title": "Blocked epic", "status": "blocked"},
                [
                    {"id": "at-2.2", "title": "Deferred second", "status": "deferred"},
                    {"id": "at-2.1", "title": "Deferred first", "status": "deferred"},
                ],
            ),
            (
                {"id": "at-1", "title": "Open epic", "status": "open"},
                [{"id": "at-1.1", "title": "Alpha deferred", "status": "deferred"}],
            ),
        ],
        deferred_scan_limit=1,
        deferred_scan_skipped_epics=2,
        epic_list_markdown=(
            "Epics by state:\n"
            "Open epics:\n"
            "- at-1 [open] Open epic\n"
            "Blocked epics:\n"
            "- at-2 [blocked] Blocked epic"
        ),
    )

    rendered = planner_startup_check.render_startup_triage_markdown(model)
    expected = (FIXTURES_DIR / "startup_triage_full.txt").read_text(encoding="utf-8").rstrip("\n")
    assert rendered == expected


def test_render_startup_triage_markdown_snapshot_fallback_state() -> None:
    model = planner_startup_check.build_startup_triage_failure_model(
        beads_root=Path("/beads"),
        phase="render_startup_overview",
        error=RuntimeError("command failed: bd list --label at:epic"),
    )

    rendered = planner_startup_check.render_startup_triage_markdown(model)
    expected = (
        (FIXTURES_DIR / "startup_triage_fallback.txt").read_text(encoding="utf-8").rstrip("\n")
    )
    assert rendered == expected


def test_render_startup_triage_markdown_byte_stable_for_identical_input() -> None:
    model = planner_startup_check.build_startup_triage_failure_model(
        beads_root=Path("/beads"),
        phase="render_startup_overview",
        error=RuntimeError("deterministic fallback"),
    )

    first = planner_startup_check.render_startup_triage_markdown(model)
    second = planner_startup_check.render_startup_triage_markdown(model)

    assert first == second

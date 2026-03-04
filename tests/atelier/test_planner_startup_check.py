from __future__ import annotations

from types import SimpleNamespace

import pytest

from atelier import planner_startup_check


def _parity() -> SimpleNamespace:
    return SimpleNamespace(
        active_top_level_work_count=1,
        indexed_active_epic_count=1,
        missing_executable_identity=(),
        missing_from_index=(),
        in_parity=True,
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

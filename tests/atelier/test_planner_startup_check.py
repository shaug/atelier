from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from atelier import planner_startup_check

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
    object.__setattr__(
        helper,
        "_run_list_query",
        lambda _args: [
            {
                "id": "at-msg-1",
                "title": "NEEDS-DECISION: Publish incomplete (at-epic.1)",
                "description": (
                    "---\n"
                    "from: atelier/worker/codex/p100\n"
                    "queue: planner\n"
                    "thread: at-epic.1\n"
                    "msg_type: notification\n"
                    "---\n\n"
                    "Confirm the next publish step."
                ),
            }
        ],
    )

    messages_for_planner = helper.list_inbox_messages("atelier/planner/codex/p200")

    assert [issue["id"] for issue in messages_for_planner] == ["at-msg-1"]
    assert "audience=planner" in str(messages_for_planner[0]["title"])
    assert "at-epic.1" in str(messages_for_planner[0]["title"])


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

from pathlib import Path
from unittest.mock import patch

import pytest

from atelier.worker import runtime, work_command_helpers, work_startup_runtime
from atelier.worker.models import WorkerRunSummary
from atelier.worker.ports import WorkerRuntimeDependencies


def test_run_worker_sessions_queue_mode_runs_once() -> None:
    calls: list[str] = []
    reported: list[str] = []

    def run_once(args: object, *, mode: str, dry_run: bool, session_key: str) -> WorkerRunSummary:
        calls.append(f"{mode}:{dry_run}:{session_key}")
        return WorkerRunSummary(started=False, reason="queue_blocked")

    runtime.run_worker_sessions(
        args=type("Args", (), {"queue": True})(),
        mode="prompt",
        run_mode="default",
        dry_run=False,
        session_key="sess",
        run_worker_once=run_once,
        report_worker_summary=lambda summary, _dry: reported.append(summary.reason),
        watch_interval_seconds=lambda: 5,
        dry_run_log=lambda _message: None,
        emit=lambda _message: None,
    )

    assert calls == ["prompt:False:sess"]
    assert reported == ["queue_blocked"]


def test_run_worker_sessions_dry_run_once_exits_after_started() -> None:
    calls = 0

    def run_once(args: object, *, mode: str, dry_run: bool, session_key: str) -> WorkerRunSummary:
        nonlocal calls
        calls += 1
        return WorkerRunSummary(started=True, reason="agent_session_complete")

    runtime.run_worker_sessions(
        args=type("Args", (), {"queue": False})(),
        mode="auto",
        run_mode="once",
        dry_run=True,
        session_key="sess",
        run_worker_once=run_once,
        report_worker_summary=lambda _summary, _dry: None,
        watch_interval_seconds=lambda: 5,
        dry_run_log=lambda _message: None,
        emit=lambda _message: None,
    )

    assert calls == 1


def test_run_worker_sessions_explicit_no_work_exits_cleanly() -> None:
    calls = 0
    emitted: list[str] = []

    def run_once(args: object, *, mode: str, dry_run: bool, session_key: str) -> WorkerRunSummary:
        del args, mode, dry_run, session_key
        nonlocal calls
        calls += 1
        return WorkerRunSummary(started=False, reason="explicit_epic_not_actionable")

    runtime.run_worker_sessions(
        args=type("Args", (), {"queue": False, "epic_id": "at-explicit"})(),
        mode="auto",
        run_mode="default",
        dry_run=False,
        session_key="sess",
        run_worker_once=run_once,
        report_worker_summary=lambda _summary, _dry: None,
        watch_interval_seconds=lambda: 5,
        dry_run_log=lambda _message: None,
        emit=emitted.append,
    )

    assert calls == 1
    assert emitted[-1] == (
        "Terminal outcome: taxonomy=no_work_explicit_epic, "
        "summary_reason=explicit_epic_not_actionable"
    )


def test_run_worker_sessions_auto_no_work_exits_cleanly() -> None:
    emitted: list[str] = []
    runtime.run_worker_sessions(
        args=type("Args", (), {"queue": False, "epic_id": None})(),
        mode="auto",
        run_mode="default",
        dry_run=False,
        session_key="sess",
        run_worker_once=lambda *_args, **_kwargs: WorkerRunSummary(
            started=False, reason="no_eligible_epics"
        ),
        report_worker_summary=lambda _summary, _dry: None,
        watch_interval_seconds=lambda: 5,
        dry_run_log=lambda _message: None,
        emit=emitted.append,
    )

    assert (
        emitted[-1] == "Terminal outcome: taxonomy=no_work_global, summary_reason=no_eligible_epics"
    )


def test_run_worker_sessions_explicit_fail_closed_exits_nonzero() -> None:
    emitted: list[str] = []
    with pytest.raises(SystemExit) as raised:
        runtime.run_worker_sessions(
            args=type("Args", (), {"queue": False, "epic_id": "at-explicit"})(),
            mode="auto",
            run_mode="default",
            dry_run=False,
            session_key="sess",
            run_worker_once=lambda *_args, **_kwargs: WorkerRunSummary(
                started=False,
                reason="explicit_epic_not_claimable",
                epic_id="at-explicit",
            ),
            report_worker_summary=lambda _summary, _dry: None,
            watch_interval_seconds=lambda: 5,
            dry_run_log=lambda _message: None,
            emit=emitted.append,
        )

    assert raised.value.code == 1
    assert emitted[-1] == (
        "Terminal outcome: taxonomy=fail_closed, summary_reason=explicit_epic_not_claimable, "
        "epic=at-explicit"
    )


def test_run_worker_sessions_auto_fail_closed_exits_nonzero() -> None:
    emitted: list[str] = []
    with pytest.raises(SystemExit) as raised:
        runtime.run_worker_sessions(
            args=type("Args", (), {"queue": False, "epic_id": None})(),
            mode="auto",
            run_mode="default",
            dry_run=False,
            session_key="sess",
            run_worker_once=lambda *_args, **_kwargs: WorkerRunSummary(
                started=False,
                reason="inbox_blocked",
            ),
            report_worker_summary=lambda _summary, _dry: None,
            watch_interval_seconds=lambda: 5,
            dry_run_log=lambda _message: None,
            emit=emitted.append,
        )

    assert raised.value.code == 1
    assert emitted[-1] == "Terminal outcome: taxonomy=fail_closed, summary_reason=inbox_blocked"


def test_run_worker_sessions_auto_skips_local_epic_failure_and_continues() -> None:
    emitted: list[str] = []
    seen_excluded: list[tuple[str, ...]] = []
    calls = 0

    def run_once(args: object, *, mode: str, dry_run: bool, session_key: str) -> WorkerRunSummary:
        del mode, dry_run, session_key
        nonlocal calls
        calls += 1
        seen_excluded.append(tuple(getattr(args, "implicit_excluded_epic_ids", ())))
        if calls == 1:
            return WorkerRunSummary(
                started=False,
                reason="changeset_stack_integrity_failed",
                epic_id="at-fail",
            )
        return WorkerRunSummary(started=False, reason="no_eligible_epics")

    runtime.run_worker_sessions(
        args=type("Args", (), {"queue": False, "epic_id": None})(),
        mode="auto",
        run_mode="default",
        dry_run=False,
        session_key="sess",
        run_worker_once=run_once,
        report_worker_summary=lambda _summary, _dry: None,
        watch_interval_seconds=lambda: 5,
        dry_run_log=lambda _message: None,
        emit=emitted.append,
    )

    assert seen_excluded == [(), ("at-fail",)]
    assert emitted[0] == (
        "Skipping failed epic and continuing implicit selection: "
        "at-fail (changeset_stack_integrity_failed)"
    )
    assert (
        emitted[-1] == "Terminal outcome: taxonomy=no_work_global, summary_reason=no_eligible_epics"
    )


def test_run_worker_sessions_auto_fails_when_local_failure_repeats_same_epic() -> None:
    emitted: list[str] = []
    seen_excluded: list[tuple[str, ...]] = []
    calls = 0

    def run_once(args: object, *, mode: str, dry_run: bool, session_key: str) -> WorkerRunSummary:
        del mode, dry_run, session_key
        nonlocal calls
        calls += 1
        seen_excluded.append(tuple(getattr(args, "implicit_excluded_epic_ids", ())))
        return WorkerRunSummary(
            started=False,
            reason="changeset_stack_integrity_failed",
            epic_id="at-fail",
        )

    with pytest.raises(SystemExit) as raised:
        runtime.run_worker_sessions(
            args=type("Args", (), {"queue": False, "epic_id": None})(),
            mode="auto",
            run_mode="default",
            dry_run=False,
            session_key="sess",
            run_worker_once=run_once,
            report_worker_summary=lambda _summary, _dry: None,
            watch_interval_seconds=lambda: 5,
            dry_run_log=lambda _message: None,
            emit=emitted.append,
        )

    assert raised.value.code == 1
    assert seen_excluded[:2] == [(), ("at-fail",)]
    assert emitted[0] == (
        "Skipping failed epic and continuing implicit selection: "
        "at-fail (changeset_stack_integrity_failed)"
    )
    assert emitted[-1] == (
        "Terminal outcome: taxonomy=fail_closed, summary_reason=changeset_stack_integrity_failed, "
        "epic=at-fail"
    )


def test_run_worker_sessions_explicit_stack_integrity_failure_is_fail_closed() -> None:
    emitted: list[str] = []

    with pytest.raises(SystemExit) as raised:
        runtime.run_worker_sessions(
            args=type("Args", (), {"queue": False, "epic_id": "at-explicit"})(),
            mode="auto",
            run_mode="default",
            dry_run=False,
            session_key="sess",
            run_worker_once=lambda *_args, **_kwargs: WorkerRunSummary(
                started=False,
                reason="changeset_stack_integrity_failed",
                epic_id="at-explicit",
            ),
            report_worker_summary=lambda _summary, _dry: None,
            watch_interval_seconds=lambda: 5,
            dry_run_log=lambda _message: None,
            emit=emitted.append,
        )

    assert raised.value.code == 1
    assert emitted[-1] == (
        "Terminal outcome: taxonomy=fail_closed, "
        "summary_reason=changeset_stack_integrity_failed, epic=at-explicit"
    )


def test_run_worker_sessions_implicit_resets_epic_id_across_retries() -> None:
    emitted: list[str] = []
    seen_epic_ids: list[object] = []
    calls = 0

    def run_once(args: object, *, mode: str, dry_run: bool, session_key: str) -> WorkerRunSummary:
        del mode, dry_run, session_key
        nonlocal calls
        calls += 1
        seen_epic_ids.append(getattr(args, "epic_id", None))
        if calls == 1:
            setattr(args, "epic_id", "at-fail")
            return WorkerRunSummary(
                started=False,
                reason="changeset_stack_integrity_failed",
                epic_id="at-fail",
            )
        return WorkerRunSummary(started=False, reason="no_eligible_epics")

    runtime.run_worker_sessions(
        args=type("Args", (), {"queue": False, "epic_id": None})(),
        mode="auto",
        run_mode="default",
        dry_run=False,
        session_key="sess",
        run_worker_once=run_once,
        report_worker_summary=lambda _summary, _dry: None,
        watch_interval_seconds=lambda: 5,
        dry_run_log=lambda _message: None,
        emit=emitted.append,
    )

    assert seen_epic_ids == [None, None]
    assert emitted[0] == (
        "Skipping failed epic and continuing implicit selection: "
        "at-fail (changeset_stack_integrity_failed)"
    )


def test_run_worker_sessions_implicit_retries_do_not_mutate_caller_args() -> None:
    args = type("Args", (), {"queue": False, "epic_id": None})()
    calls = 0

    def run_once(args: object, *, mode: str, dry_run: bool, session_key: str) -> WorkerRunSummary:
        del mode, dry_run, session_key
        nonlocal calls
        calls += 1
        setattr(args, "epic_id", "at-fail")
        setattr(args, "implicit_excluded_epic_ids", ("at-overwritten",))
        if calls == 1:
            return WorkerRunSummary(
                started=False,
                reason="changeset_stack_integrity_failed",
                epic_id="at-fail",
            )
        return WorkerRunSummary(started=False, reason="no_eligible_epics")

    runtime.run_worker_sessions(
        args=args,
        mode="auto",
        run_mode="default",
        dry_run=False,
        session_key="sess",
        run_worker_once=run_once,
        report_worker_summary=lambda _summary, _dry: None,
        watch_interval_seconds=lambda: 5,
        dry_run_log=lambda _message: None,
        emit=lambda _message: None,
    )

    assert getattr(args, "epic_id", None) is None
    assert not hasattr(args, "implicit_excluded_epic_ids")


def test_classify_non_watch_exit_outcome_is_deterministic() -> None:
    explicit_success = runtime.classify_non_watch_exit_outcome(
        WorkerRunSummary(started=False, reason="explicit_epic_completed"),
        explicit_epic_requested=True,
    )
    global_success = runtime.classify_non_watch_exit_outcome(
        WorkerRunSummary(started=False, reason="no_eligible_epics"),
        explicit_epic_requested=False,
    )
    failure = runtime.classify_non_watch_exit_outcome(
        WorkerRunSummary(started=False, reason="queue_blocked"),
        explicit_epic_requested=False,
    )

    assert explicit_success.taxonomy == runtime.NON_WATCH_EXIT_REASON_NO_WORK_EXPLICIT
    assert explicit_success.success is True
    assert global_success.taxonomy == runtime.NON_WATCH_EXIT_REASON_NO_WORK_GLOBAL
    assert global_success.success is True
    assert failure.taxonomy == runtime.NON_WATCH_EXIT_REASON_FAIL_CLOSED
    assert failure.success is False


def test_run_worker_sessions_watch_logs_and_sleeps_on_no_ready() -> None:
    calls = 0
    emitted: list[str] = []
    slept: list[float] = []

    def run_once(args: object, *, mode: str, dry_run: bool, session_key: str) -> WorkerRunSummary:
        nonlocal calls
        calls += 1
        if calls == 1:
            return WorkerRunSummary(started=False, reason="no_ready_changesets")
        raise RuntimeError("stop-loop")

    try:
        runtime.run_worker_sessions(
            args=type("Args", (), {"queue": False})(),
            mode="auto",
            run_mode="watch",
            dry_run=False,
            session_key="sess",
            run_worker_once=run_once,
            report_worker_summary=lambda _summary, _dry: None,
            watch_interval_seconds=lambda: 9,
            dry_run_log=lambda _message: None,
            emit=emitted.append,
            sleep_fn=lambda seconds: slept.append(seconds),
        )
    except RuntimeError as exc:
        assert str(exc) == "stop-loop"

    assert slept == [9]
    assert emitted == ["No ready work; watching for updates (sleeping 9s)."]


def test_run_worker_sessions_dry_watch_uses_dry_run_log() -> None:
    calls = 0
    logs: list[str] = []
    slept: list[float] = []

    def run_once(args: object, *, mode: str, dry_run: bool, session_key: str) -> WorkerRunSummary:
        nonlocal calls
        calls += 1
        if calls == 1:
            return WorkerRunSummary(started=False, reason="no_ready_changesets")
        raise RuntimeError("stop-loop")

    try:
        runtime.run_worker_sessions(
            args=type("Args", (), {"queue": False})(),
            mode="auto",
            run_mode="watch",
            dry_run=True,
            session_key="sess",
            run_worker_once=run_once,
            report_worker_summary=lambda _summary, _dry: None,
            watch_interval_seconds=lambda: 7,
            dry_run_log=logs.append,
            emit=lambda _message: None,
            sleep_fn=lambda seconds: slept.append(seconds),
        )
    except RuntimeError as exc:
        assert str(exc) == "stop-loop"

    assert slept == [7]
    assert logs == ["Watching for updates (sleeping 7s before next check)."]


def test_build_worker_runtime_dependencies_wires_port_groups() -> None:
    deps = runtime.build_worker_runtime_dependencies(
        resolve_current_project_with_repo_root=lambda: (
            None,
            None,
            "",
            None,
        ),
        confirm_fn=lambda _prompt, **_kwargs: True,
        die_fn=lambda _message: None,
        emit=lambda _message: None,
    )

    assert isinstance(deps, WorkerRuntimeDependencies)
    assert deps.infra.resolve_current_project_with_repo_root is not None
    assert deps.lifecycle.run_startup_contract is not None
    assert deps.commands.ensure_exec_subcommand_flag is not None
    assert deps.control.step is not None


def test_work_command_helpers_exposes_public_finalize_helpers() -> None:
    helper = getattr(work_command_helpers, "finalize_changeset")
    assert callable(helper)


def test_work_startup_runtime_does_not_expose_finalize_private_helpers() -> None:
    assert not hasattr(work_startup_runtime, "_finalize_changeset")


def test_startup_service_no_eligible_summary_does_not_queue_message() -> None:
    emitted: list[str] = []
    issues = [{"id": "at-1", "status": "open", "labels": ["at:epic"]}]
    service = work_startup_runtime._StartupContractService(  # pyright: ignore[reportPrivateUsage]
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
    )

    with (
        patch("atelier.worker.work_startup_runtime.say", side_effect=emitted.append),
        patch("atelier.worker.work_startup_runtime.beads.create_message_bead") as create_message,
    ):
        service.send_needs_decision(
            agent_id="atelier/worker/codex/p1",
            mode="auto",
            issues=issues,
            dry_run=False,
        )

    assert create_message.call_count == 0
    assert emitted[0] == "No eligible epics available."


def test_startup_service_lists_only_non_closed_epics() -> None:
    service = work_startup_runtime._StartupContractService(  # pyright: ignore[reportPrivateUsage]
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
    )

    with patch(
        "atelier.worker.work_startup_runtime.beads.list_epics",
        return_value=[{"id": "at-1"}],
    ) as list_epics:
        issues = service.list_epics()

    assert issues == [{"id": "at-1"}]
    list_epics.assert_called_once_with(
        beads_root=Path("/beads"),
        cwd=Path("/repo"),
        include_closed=False,
    )


def test_startup_service_reports_planner_owned_executable_violations() -> None:
    emitted: list[str] = []
    issues = [
        {
            "id": "at-violation",
            "status": "open",
            "labels": ["at:epic"],
            "assignee": "atelier/planner/codex/p1",
        }
    ]
    service = work_startup_runtime._StartupContractService(  # pyright: ignore[reportPrivateUsage]
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
    )

    with patch("atelier.worker.work_startup_runtime.say", side_effect=emitted.append):
        service.send_needs_decision(
            agent_id="atelier/worker/codex/p2",
            mode="auto",
            issues=issues,
            dry_run=False,
        )

    assert any("Planner-owned executable epics: 1" in line for line in emitted)
    assert any("Ownership violations: at-violation" in line for line in emitted)
    assert any(
        "Ownership-policy blockers may prevent review-feedback pickup." in line for line in emitted
    )

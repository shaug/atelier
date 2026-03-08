import subprocess
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


def test_run_worker_sessions_auto_skips_finalize_dependency_gate_failure_and_continues() -> None:
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
                reason="changeset_finalize_in_progress_dependency_gate_failed",
                epic_id="at-fail",
                changeset_id="at-fail.1",
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
        "at-fail (changeset_finalize_in_progress_dependency_gate_failed)"
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
    args = type("Args", (), {})()
    args.queue = False
    args.epic_id = None
    args.nested = {"seen": []}
    calls = 0
    seen_nested: list[tuple[int, ...]] = []

    def run_once(args: object, *, mode: str, dry_run: bool, session_key: str) -> WorkerRunSummary:
        del mode, dry_run, session_key
        nonlocal calls
        calls += 1
        setattr(args, "epic_id", "at-fail")
        setattr(args, "implicit_excluded_epic_ids", ("at-overwritten",))
        nested = getattr(args, "nested")
        nested["seen"].append(calls)
        seen_nested.append(tuple(nested["seen"]))
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
    assert args.nested == {"seen": []}
    assert seen_nested == [(1,), (2,)]


def test_run_worker_sessions_deepcopy_type_error_falls_back_with_debug_log() -> None:
    class Args:
        def __init__(self) -> None:
            self.queue = False
            self.epic_id = None

        def __deepcopy__(self, memo: object) -> object:
            del memo
            raise TypeError("not deepcopyable")

    original_args = Args()
    seen_ids: list[int] = []

    def run_once(args: object, *, mode: str, dry_run: bool, session_key: str) -> WorkerRunSummary:
        del mode, dry_run, session_key
        seen_ids.append(id(args))
        return WorkerRunSummary(started=False, reason="no_eligible_epics")

    with patch("atelier.worker.runtime.atelier_log.debug") as debug_log:
        runtime.run_worker_sessions(
            args=original_args,
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

    assert len(seen_ids) == 1
    assert any(
        "Falling back to shallow args copy after deepcopy failure" in str(call.args[0])
        for call in debug_log.call_args_list
    )


def test_run_worker_sessions_deepcopy_unexpected_error_bubbles() -> None:
    class Args:
        def __init__(self) -> None:
            self.queue = False
            self.epic_id = None

        def __deepcopy__(self, memo: object) -> object:
            del memo
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        runtime.run_worker_sessions(
            args=Args(),
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
            emit=lambda _message: None,
        )


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


def test_run_worker_sessions_watch_reexecs_before_sleep_when_update_detected() -> None:
    calls = 0
    emitted: list[str] = []
    slept: list[float] = []
    startup_runtime = type("StartupRuntime", (), {"runtime_changed": lambda self: True})()

    def run_once(args: object, *, mode: str, dry_run: bool, session_key: str) -> WorkerRunSummary:
        del args, mode, dry_run, session_key
        nonlocal calls
        calls += 1
        return WorkerRunSummary(started=False, reason="no_ready_changesets")

    with pytest.raises(RuntimeError, match="reexec"):
        with patch(
            "atelier.worker.runtime.worker_restart_runtime.relaunch_worker_process",
            side_effect=RuntimeError("reexec"),
        ) as relaunch:
            runtime.run_worker_sessions(
                args=type(
                    "Args",
                    (),
                    {
                        "queue": False,
                        "startup_runtime": startup_runtime,
                        "restart_on_update": True,
                    },
                )(),
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

    assert calls == 1
    assert slept == []
    assert emitted == ["Runtime update detected; restarting worker before the next idle check."]
    relaunch.assert_called_once_with(startup_runtime)


def test_run_worker_sessions_default_mode_reexecs_only_when_opted_in() -> None:
    calls = 0
    emitted: list[str] = []
    startup_runtime = type("StartupRuntime", (), {"runtime_changed": lambda self: True})()

    def run_once(args: object, *, mode: str, dry_run: bool, session_key: str) -> WorkerRunSummary:
        del args, mode, dry_run, session_key
        nonlocal calls
        calls += 1
        return WorkerRunSummary(started=True, reason="agent_session_complete")

    with pytest.raises(RuntimeError, match="reexec"):
        with patch(
            "atelier.worker.runtime.worker_restart_runtime.relaunch_worker_process",
            side_effect=RuntimeError("reexec"),
        ) as relaunch:
            runtime.run_worker_sessions(
                args=type(
                    "Args",
                    (),
                    {
                        "queue": False,
                        "startup_runtime": startup_runtime,
                        "restart_on_update": True,
                    },
                )(),
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
    assert emitted == ["Runtime update detected; restarting worker before the next idle check."]
    relaunch.assert_called_once_with(startup_runtime)


def test_run_worker_sessions_no_update_skips_reexec() -> None:
    emitted: list[str] = []
    slept: list[float] = []
    startup_runtime = type("StartupRuntime", (), {"runtime_changed": lambda self: False})()
    calls = 0

    def run_once(args: object, *, mode: str, dry_run: bool, session_key: str) -> WorkerRunSummary:
        del args, mode, dry_run, session_key
        nonlocal calls
        calls += 1
        if calls == 1:
            return WorkerRunSummary(started=False, reason="no_ready_changesets")
        raise RuntimeError("stop-loop")

    try:
        with patch(
            "atelier.worker.runtime.worker_restart_runtime.relaunch_worker_process"
        ) as relaunch:
            runtime.run_worker_sessions(
                args=type(
                    "Args",
                    (),
                    {
                        "queue": False,
                        "startup_runtime": startup_runtime,
                        "restart_on_update": True,
                    },
                )(),
                mode="auto",
                run_mode="watch",
                dry_run=False,
                session_key="sess",
                run_worker_once=run_once,
                report_worker_summary=lambda _summary, _dry: None,
                watch_interval_seconds=lambda: 11,
                dry_run_log=lambda _message: None,
                emit=emitted.append,
                sleep_fn=lambda seconds: slept.append(seconds),
            )
    except RuntimeError as exc:
        assert str(exc) == "stop-loop"

    assert emitted == ["No ready work; watching for updates (sleeping 11s)."]
    assert slept == [11]
    relaunch.assert_not_called()


def test_run_worker_sessions_failed_reexec_logs_and_continues() -> None:
    emitted: list[str] = []
    slept: list[float] = []
    startup_runtime = type("StartupRuntime", (), {"runtime_changed": lambda self: True})()
    calls = 0

    def run_once(args: object, *, mode: str, dry_run: bool, session_key: str) -> WorkerRunSummary:
        del args, mode, dry_run, session_key
        nonlocal calls
        calls += 1
        if calls == 1:
            return WorkerRunSummary(started=False, reason="no_ready_changesets")
        raise RuntimeError("stop-loop")

    try:
        with patch(
            "atelier.worker.runtime.worker_restart_runtime.relaunch_worker_process",
            side_effect=OSError("exec failed"),
        ) as relaunch:
            runtime.run_worker_sessions(
                args=type(
                    "Args",
                    (),
                    {
                        "queue": False,
                        "startup_runtime": startup_runtime,
                        "restart_on_update": True,
                    },
                )(),
                mode="auto",
                run_mode="watch",
                dry_run=False,
                session_key="sess",
                run_worker_once=run_once,
                report_worker_summary=lambda _summary, _dry: None,
                watch_interval_seconds=lambda: 13,
                dry_run_log=lambda _message: None,
                emit=emitted.append,
                sleep_fn=lambda seconds: slept.append(seconds),
            )
    except RuntimeError as exc:
        assert str(exc) == "stop-loop"

    assert emitted == [
        "Runtime update detected; restarting worker before the next idle check.",
        "Runtime update detected but restart failed; continuing with the current runtime (OSError: exec failed).",
        "No ready work; watching for updates (sleeping 13s).",
    ]
    assert slept == [13]
    assert relaunch.call_count == 1


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


def test_startup_service_caches_global_signal_scan() -> None:
    service = work_startup_runtime._StartupContractService(  # pyright: ignore[reportPrivateUsage]
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
    )
    conflict = work_startup_runtime.MergeConflictSelection(
        epic_id="at-1",
        changeset_id="at-1.2",
        observed_at="2026-03-01T00:00:00Z",
        pr_url="https://github.com/org/repo/pull/99",
    )
    feedback = work_startup_runtime.ReviewFeedbackSelection(
        epic_id="at-1",
        changeset_id="at-1.3",
        feedback_at="2026-03-02T00:00:00Z",
    )
    selections = work_startup_runtime.GlobalStartupSelections(
        conflict=conflict,
        feedback=feedback,
    )

    with patch(
        "atelier.worker.work_startup_runtime.worker_review.select_global_startup_candidates",
        return_value=selections,
    ) as select_global:
        selected_conflict = service.select_global_conflicted_changeset(repo_slug="org/repo")
        selected_feedback = service.select_global_review_feedback_changeset(repo_slug="org/repo")

    assert selected_conflict == conflict
    assert selected_feedback == feedback
    select_global.assert_called_once_with(
        repo_slug="org/repo",
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
        emit_diagnostic=work_startup_runtime.say,
    )


def test_next_changeset_service_passes_beads_root_to_review_waiting_gate() -> None:
    issue = {"id": "at-1.2"}
    service = work_startup_runtime._NextChangesetService(  # pyright: ignore[reportPrivateUsage]
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
    )

    with patch(
        "atelier.worker.work_startup_runtime.changeset_waiting_on_review_or_signals",
        return_value=True,
    ) as waiting:
        result = service.changeset_waiting_on_review_or_signals(
            issue,
            repo_slug="org/repo",
            branch_pr=True,
            git_path="git",
        )

    assert result is True
    waiting.assert_called_once_with(
        issue,
        repo_slug="org/repo",
        repo_root=Path("/repo"),
        branch_pr=True,
        git_path="git",
        beads_root=Path("/beads"),
    )


def test_startup_finalize_preflight_short_circuits_terminal_pr_with_integration() -> None:
    issue = {
        "status": "blocked",
        "description": "changeset.work_branch: feat/root-at-epic.1\npr_state: draft-pr\n",
    }
    with (
        patch(
            "atelier.worker.work_startup_runtime.changeset_integration_signal",
            return_value=(True, "abc1234"),
        ) as integration_signal,
        patch(
            "atelier.worker.work_startup_runtime.stale_pr_lifecycle.git.git_ref_exists",
            return_value=True,
        ),
        patch(
            "atelier.worker.work_startup_runtime.stale_pr_lifecycle.prs.lookup_github_pr_status",
            return_value=work_startup_runtime.prs.GithubPrLookup(
                outcome="found",
                payload={
                    "number": 42,
                    "state": "CLOSED",
                    "isDraft": False,
                    "reviewDecision": None,
                    "mergedAt": "2026-03-01T00:00:00Z",
                    "closedAt": "2026-03-01T00:00:00Z",
                },
            ),
        ),
    ):
        result = work_startup_runtime.startup_finalize_preflight(
            issue=issue,
            repo_slug="org/repo",
            branch_pr=True,
            repo_root=Path("/repo"),
            git_path="git",
        )

    assert result.should_finalize_only is True
    assert result.reason == "finalize_only:pr_lifecycle_merged_integration_proven"
    integration_signal.assert_called_once_with(
        issue,
        repo_slug="org/repo",
        repo_root=Path("/repo"),
        git_path="git",
        require_target_branch_proof=True,
    )


def test_startup_finalize_preflight_fails_closed_when_pr_not_terminal() -> None:
    issue = {
        "status": "in_progress",
        "description": "changeset.work_branch: feat/root-at-epic.1\npr_state: closed\n",
    }
    with (
        patch(
            "atelier.worker.work_startup_runtime.changeset_integration_signal",
            side_effect=AssertionError("integration should not be checked for active PR states"),
        ) as integration_signal,
        patch(
            "atelier.worker.work_startup_runtime.stale_pr_lifecycle.git.git_ref_exists",
            return_value=True,
        ),
        patch(
            "atelier.worker.work_startup_runtime.stale_pr_lifecycle.prs.lookup_github_pr_status",
            return_value=work_startup_runtime.prs.GithubPrLookup(
                outcome="found",
                payload={
                    "number": 42,
                    "state": "OPEN",
                    "isDraft": False,
                    "reviewDecision": None,
                },
            ),
        ),
    ):
        result = work_startup_runtime.startup_finalize_preflight(
            issue=issue,
            repo_slug="org/repo",
            branch_pr=True,
            repo_root=Path("/repo"),
            git_path="git",
        )

    assert result.should_finalize_only is False
    assert result.reason == "normal_path:pr_lifecycle_pr-open"
    integration_signal.assert_not_called()


def test_startup_finalize_preflight_flags_stale_terminal_pr_without_integration() -> None:
    issue = {
        "status": "blocked",
        "description": "changeset.work_branch: feat/root-at-epic.2\npr_state: draft-pr\n",
    }

    with (
        patch(
            "atelier.worker.work_startup_runtime.stale_pr_lifecycle.git.git_ref_exists",
            return_value=True,
        ),
        patch(
            "atelier.worker.work_startup_runtime.stale_pr_lifecycle.prs.lookup_github_pr_status",
            return_value=work_startup_runtime.prs.GithubPrLookup(
                outcome="found",
                payload={
                    "number": 43,
                    "state": "CLOSED",
                    "isDraft": False,
                    "reviewDecision": None,
                    "mergedAt": "2026-03-02T00:00:00Z",
                    "closedAt": "2026-03-02T00:00:00Z",
                },
            ),
        ),
        patch(
            "atelier.worker.work_startup_runtime.changeset_integration_signal",
            return_value=(False, None),
        ) as integration_signal,
    ):
        result = work_startup_runtime.startup_finalize_preflight(
            issue=issue,
            repo_slug="org/repo",
            branch_pr=True,
            repo_root=Path("/repo"),
            git_path="git",
        )

    assert result.should_finalize_only is False
    assert result.reason == "normal_path:stale_terminal_pr_lifecycle_merged"
    integration_signal.assert_called_once_with(
        issue,
        repo_slug="org/repo",
        repo_root=Path("/repo"),
        git_path="git",
        require_target_branch_proof=True,
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


def test_startup_service_preserves_live_worker_when_hook_lookup_fails() -> None:
    issue = {
        "id": "at-hook-error",
        "status": "in_progress",
        "labels": ["at:epic"],
        "assignee": "atelier/worker/codex/p222",
    }
    service = work_startup_runtime._StartupContractService(  # pyright: ignore[reportPrivateUsage]
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
    )

    with (
        patch(
            "atelier.worker.work_startup_runtime.agent_home.is_session_agent_active",
            return_value=True,
        ),
        patch(
            "atelier.worker.work_startup_runtime.beads.find_agent_bead",
            return_value={"id": "at-agent-live"},
        ),
        patch(
            "atelier.worker.work_startup_runtime.beads.run_bd_command",
            return_value=subprocess.CompletedProcess(
                args=["slot", "show", "at-agent-live", "--json"],
                returncode=1,
                stdout="",
                stderr="slot read failed",
            ),
        ),
    ):
        stale = service.stale_family_assigned_epics(
            [issue],
            agent_id="atelier/worker/codex/p999",
        )

    assert stale == []

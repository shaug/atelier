from atelier.worker import runtime, work_command_helpers, work_startup_runtime
from atelier.worker.models import WorkerRunSummary
from atelier.worker.ports import WorkerRuntimeDependencies


def test_run_worker_sessions_queue_mode_runs_once() -> None:
    calls: list[str] = []
    reported: list[str] = []

    def run_once(
        args: object, *, mode: str, dry_run: bool, session_key: str
    ) -> WorkerRunSummary:
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

    def run_once(
        args: object, *, mode: str, dry_run: bool, session_key: str
    ) -> WorkerRunSummary:
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


def test_run_worker_sessions_watch_logs_and_sleeps_on_no_ready() -> None:
    calls = 0
    emitted: list[str] = []
    slept: list[float] = []

    def run_once(
        args: object, *, mode: str, dry_run: bool, session_key: str
    ) -> WorkerRunSummary:
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

    def run_once(
        args: object, *, mode: str, dry_run: bool, session_key: str
    ) -> WorkerRunSummary:
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


def test_work_command_helpers_exposes_split_private_helpers() -> None:
    helper = getattr(work_command_helpers, "_find_invalid_changeset_labels")
    assert callable(helper)


def test_work_startup_runtime_fallback_exposes_finalize_helper() -> None:
    helper = getattr(work_startup_runtime, "_find_invalid_changeset_labels")
    assert callable(helper)

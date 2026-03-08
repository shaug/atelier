from __future__ import annotations

import os
from pathlib import Path

import pytest

from atelier.worker import restart_runtime


def _make_updated_startup_runtime(tmp_path: Path) -> restart_runtime.WorkerStartupRuntime:
    package_root = tmp_path / "atelier"
    package_root.mkdir()
    (package_root / "worker.py").write_text("print('updated')\n", encoding="utf-8")
    return restart_runtime.WorkerStartupRuntime(
        relaunch_contract=restart_runtime.WorkerRelaunchContract(
            cwd=tmp_path,
            argv=("/venv/bin/python", "-m", "atelier.cli", "work"),
            executable="/venv/bin/python",
            entry_kind="module",
            entry_value="atelier.cli",
            env=(("PATH", "/venv/bin:/usr/bin"),),
        ),
        startup_fingerprint=restart_runtime.WorkerRuntimeFingerprint(
            version="1.2.3",
            code_marker_kind="package-tree-stat-digest",
            code_marker="startup-marker",
            package_root=package_root,
        ),
    )


def test_capture_worker_relaunch_contract_prefers_orig_argv_and_subset_env(
    tmp_path: Path,
) -> None:
    contract = restart_runtime.capture_worker_relaunch_contract(
        argv=("atelier", "work", "--run-mode", "watch"),
        orig_argv=(
            "/venv/bin/python",
            "-m",
            "atelier.cli",
            "work",
            "--run-mode",
            "watch",
        ),
        env={
            "ATELIER_RUN_MODE": "watch",
            "BEADS_DIR": "/tmp/beads",
            "FOO": "bar",
            "HOME": "/Users/tester",
            "PATH": "/venv/bin:/usr/bin",
        },
        cwd=tmp_path,
        executable="/venv/bin/python",
    )

    assert contract.cwd == tmp_path
    assert contract.entry_kind == "module"
    assert contract.entry_value == "atelier.cli"
    assert contract.exec_target() == "/venv/bin/python"
    assert contract.exec_argv() == (
        "/venv/bin/python",
        "-m",
        "atelier.cli",
        "work",
        "--run-mode",
        "watch",
    )
    assert contract.exec_env() == {
        "ATELIER_RUN_MODE": "watch",
        "BEADS_DIR": "/tmp/beads",
        "PATH": "/venv/bin:/usr/bin",
    }


def test_capture_worker_startup_runtime_detects_package_tree_updates(
    tmp_path: Path,
) -> None:
    package_root = tmp_path / "atelier"
    module_path = package_root / "worker.py"
    package_root.mkdir()
    module_path.write_text("print('v1')\n", encoding="utf-8")

    startup = restart_runtime.capture_worker_startup_runtime(
        argv=("atelier", "work"),
        orig_argv=("/venv/bin/python", "-m", "atelier.cli", "work"),
        env={"PATH": "/venv/bin:/usr/bin"},
        cwd=tmp_path,
        executable="/venv/bin/python",
        version="1.2.3",
        package_root=package_root,
    )

    assert startup.startup_fingerprint.version == "1.2.3"
    assert startup.startup_fingerprint.code_marker_kind == "package-tree-stat-digest"
    assert startup.runtime_changed(version="1.2.3", package_root=package_root) is False

    stat = module_path.stat()
    module_path.write_text("print('v2 with changes')\n", encoding="utf-8")
    os.utime(module_path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))

    assert startup.runtime_changed(version="1.2.3", package_root=package_root) is True


def test_relaunch_worker_process_uses_preserved_contract(tmp_path: Path) -> None:
    startup = restart_runtime.capture_worker_startup_runtime(
        argv=("atelier", "work", "--restart-on-update"),
        orig_argv=("/venv/bin/python", "-m", "atelier.cli", "work", "--restart-on-update"),
        env={"PATH": "/venv/bin:/usr/bin", "ATELIER_AGENT_ID": "atelier/worker/codex/p1"},
        cwd=tmp_path,
        executable="/venv/bin/python",
        version="1.2.3",
        package_root=tmp_path,
    )
    captured: dict[str, object] = {}

    def fake_chdir(path: Path) -> None:
        captured["cwd"] = path

    def fake_execvpe(target: str, argv: list[str], env: dict[str, str]) -> None:
        captured["target"] = target
        captured["argv"] = argv
        captured["env"] = env
        raise RuntimeError("reexec")

    with pytest.raises(RuntimeError, match="reexec"):
        restart_runtime.relaunch_worker_process(
            startup.with_restart_loop_state(
                restart_runtime.WorkerRestartLoopState(
                    attempt_count=2,
                    window_started_at=100,
                    retry_not_before=130,
                    last_fingerprint="marker-2",
                )
            ),
            chdir_fn=fake_chdir,
            execvpe_fn=fake_execvpe,
        )

    assert captured == {
        "cwd": tmp_path,
        "target": "/venv/bin/python",
        "argv": ["/venv/bin/python", "-m", "atelier.cli", "work", "--restart-on-update"],
        "env": {
            "ATELIER_AGENT_ID": "atelier/worker/codex/p1",
            "ATELIER_RESTART_ATTEMPT_COUNT": "2",
            "ATELIER_RESTART_LAST_FINGERPRINT": "marker-2",
            "ATELIER_RESTART_RETRY_NOT_BEFORE": "130",
            "ATELIER_RESTART_WINDOW_STARTED_AT": "100",
            "PATH": "/venv/bin:/usr/bin",
        },
    }


def test_capture_worker_startup_runtime_restores_restart_loop_state(tmp_path: Path) -> None:
    startup = restart_runtime.capture_worker_startup_runtime(
        argv=("atelier", "work"),
        orig_argv=("/venv/bin/python", "-m", "atelier.cli", "work"),
        env={
            "PATH": "/venv/bin:/usr/bin",
            "ATELIER_RESTART_ATTEMPT_COUNT": "2",
            "ATELIER_RESTART_WINDOW_STARTED_AT": "120",
            "ATELIER_RESTART_RETRY_NOT_BEFORE": "150",
            "ATELIER_RESTART_LAST_FINGERPRINT": "digest-2",
        },
        cwd=tmp_path,
        executable="/venv/bin/python",
        version="1.2.3",
        package_root=tmp_path,
    )

    assert startup.restart_loop_state == restart_runtime.WorkerRestartLoopState(
        attempt_count=2,
        window_started_at=120,
        retry_not_before=150,
        last_fingerprint="digest-2",
    )


def test_plan_restart_blocks_during_cooldown(tmp_path: Path) -> None:
    startup = _make_updated_startup_runtime(tmp_path)
    current_fingerprint = startup.capture_current_fingerprint()
    startup = startup.with_restart_loop_state(
        restart_runtime.WorkerRestartLoopState(
            attempt_count=1,
            window_started_at=100,
            retry_not_before=115,
            last_fingerprint=current_fingerprint.restart_scope(),
        )
    )

    decision = startup.plan_restart(now=110)

    assert decision is not None
    assert decision.should_restart is False
    assert decision.reason == "cooldown"
    assert decision.message == (
        "Runtime update detected but auto-restart is cooling down for 5s after "
        "attempt 1/3; continuing with the current runtime."
    )


def test_plan_restart_blocks_after_bounded_attempt_limit(tmp_path: Path) -> None:
    startup = _make_updated_startup_runtime(tmp_path)
    current_fingerprint = startup.capture_current_fingerprint()
    startup = startup.with_restart_loop_state(
        restart_runtime.WorkerRestartLoopState(
            attempt_count=3,
            window_started_at=100,
            retry_not_before=100,
            last_fingerprint=current_fingerprint.restart_scope(),
        )
    )

    decision = startup.plan_restart(now=120)

    assert decision is not None
    assert decision.should_restart is False
    assert decision.reason == "max-attempts"
    assert decision.message == (
        "Runtime update detected but auto-restart is paused after 3/3 attempts "
        "in 300s; continuing with the current runtime."
    )


def test_plan_restart_resets_loop_state_for_distinct_runtime_update(tmp_path: Path) -> None:
    startup = _make_updated_startup_runtime(tmp_path).with_restart_loop_state(
        restart_runtime.WorkerRestartLoopState(
            attempt_count=3,
            window_started_at=100,
            retry_not_before=200,
            last_fingerprint="version=1.2.3;marker_kind=package-tree-stat-digest;marker=old-update",
        )
    )

    decision = startup.plan_restart(now=110)

    assert decision is not None
    assert decision.should_restart is True
    assert decision.reason == "restart"
    assert decision.message == (
        "Runtime update detected; restarting worker before the next idle check (attempt 1/3)."
    )
    assert decision.startup_runtime.restart_loop_state.attempt_count == 1
    assert (
        decision.startup_runtime.restart_loop_state.last_fingerprint
        == decision.current_fingerprint.restart_scope()
    )

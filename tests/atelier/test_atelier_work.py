"""Tests for scripts/atelier-work.py."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "atelier-work.py"


def _load_work_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("atelier_work", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load atelier-work module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def supervisor_module() -> ModuleType:
    return _load_work_module()


def test_parse_args_sets_single_cycle_for_dry_run(supervisor_module: ModuleType) -> None:
    parse_args = supervisor_module._parse_args
    config, passthrough = parse_args(["--repo-path", ".", "--dry-run"])

    assert config.dry_run is True
    assert config.max_cycles == 1
    assert config.mainline_branch == "main"
    assert config.install_command == "just install"
    assert passthrough == []


def test_parse_args_default_install_command_is_just_install(supervisor_module: ModuleType) -> None:
    parse_args = supervisor_module._parse_args
    config, _ = parse_args(["--repo-path", "."])
    assert config.install_command == "just install"


def test_parse_args_no_install_disables_install_step(supervisor_module: ModuleType) -> None:
    parse_args = supervisor_module._parse_args
    config, _ = parse_args(["--repo-path", ".", "--no-install"])
    assert config.install_command is None


def test_parse_args_install_override(supervisor_module: ModuleType) -> None:
    parse_args = supervisor_module._parse_args
    config, _ = parse_args(["--repo-path", ".", "--install", "just install-editable"])
    assert config.install_command == "just install-editable"


def test_parse_args_captures_worker_passthrough(supervisor_module: ModuleType) -> None:
    parse_args = supervisor_module._parse_args
    config, passthrough = parse_args(
        [
            "--repo-path",
            ".",
            "--worker-command",
            "atelier work --run-mode once",
            "--",
            "--mode",
            "auto",
            "at-q5fc",
        ]
    )

    assert config.worker_command == "atelier work --run-mode once"
    assert passthrough == ["--mode", "auto", "at-q5fc"]


def test_build_worker_command_appends_passthrough(supervisor_module: ModuleType) -> None:
    build_worker_command = supervisor_module._build_worker_command

    command = build_worker_command(
        "atelier work --run-mode once",
        ["--mode", "auto", "at-q5fc"],
    )

    assert command == [
        "atelier",
        "work",
        "--run-mode",
        "once",
        "--mode",
        "auto",
        "at-q5fc",
    ]


def test_run_cycle_skips_worker_when_preflight_fails(
    monkeypatch: pytest.MonkeyPatch,
    supervisor_module: ModuleType,
) -> None:
    config = supervisor_module.RunnerConfig(
        repo_path=Path("."),
        git_remote="origin",
        git_ref="main",
        mainline_branch="main",
        update_policy="ff-only",
        install_command=None,
        worker_command="atelier work --run-mode once",
        loop_interval_seconds=0.0,
        max_cycles=1,
        dry_run=False,
        fail_fast=False,
        continue_on_worker_failure=False,
    )

    install_called = False
    worker_called = False

    monkeypatch.setattr(supervisor_module, "_run_update_step", lambda _config: False)

    def _record_install(_config: Any) -> bool:
        nonlocal install_called
        install_called = True
        return True

    monkeypatch.setattr(supervisor_module, "_run_install_step", _record_install)

    def _record_worker(_config: Any, _passthrough: Any) -> bool:
        nonlocal worker_called
        worker_called = True
        return True

    monkeypatch.setattr(supervisor_module, "_run_worker_step", _record_worker)

    cycle_rc = supervisor_module._run_cycle(config, ["--mode", "auto"], cycle_number=1)

    assert cycle_rc == 1
    assert install_called is False
    assert worker_called is False


def test_run_cycle_runs_worker_when_preflight_succeeds(
    monkeypatch: pytest.MonkeyPatch,
    supervisor_module: ModuleType,
) -> None:
    config = supervisor_module.RunnerConfig(
        repo_path=Path("."),
        git_remote="origin",
        git_ref="main",
        mainline_branch="main",
        update_policy="ff-only",
        install_command="just install-editable",
        worker_command="atelier work --run-mode once",
        loop_interval_seconds=0.0,
        max_cycles=1,
        dry_run=False,
        fail_fast=False,
        continue_on_worker_failure=False,
    )

    calls: list[tuple[str, list[str]]] = []

    monkeypatch.setattr(supervisor_module, "_run_update_step", lambda _config: True)
    monkeypatch.setattr(supervisor_module, "_run_install_step", lambda _config: True)

    def _record_worker(_config: Any, passthrough: list[str]) -> bool:
        calls.append(("worker", passthrough))
        return True

    monkeypatch.setattr(supervisor_module, "_run_worker_step", _record_worker)

    cycle_rc = supervisor_module._run_cycle(config, ["--mode", "auto"], cycle_number=2)

    assert cycle_rc == 0
    assert calls == [("worker", ["--mode", "auto"])]


def test_run_update_step_returns_false_when_not_on_mainline(
    monkeypatch: pytest.MonkeyPatch,
    supervisor_module: ModuleType,
) -> None:
    config = supervisor_module.RunnerConfig(
        repo_path=Path("."),
        git_remote="origin",
        git_ref=None,
        mainline_branch="main",
        update_policy="ff-only",
        install_command=None,
        worker_command="atelier work --run-mode once",
        loop_interval_seconds=0.0,
        max_cycles=1,
        dry_run=False,
        fail_fast=False,
        continue_on_worker_failure=False,
    )

    logs: list[str] = []

    monkeypatch.setattr(supervisor_module, "_current_branch", lambda _config: "feature-branch")
    monkeypatch.setattr(supervisor_module, "_log", logs.append)

    update_ok = supervisor_module._run_update_step(config)

    assert update_ok is False
    assert any("not on mainline branch" in log for log in logs)


def test_run_update_step_returns_false_when_git_ref_resolution_fails(
    monkeypatch: pytest.MonkeyPatch,
    supervisor_module: ModuleType,
) -> None:
    config = supervisor_module.RunnerConfig(
        repo_path=Path("."),
        git_remote="origin",
        git_ref=None,
        mainline_branch="main",
        update_policy="ff-only",
        install_command=None,
        worker_command="atelier work --run-mode once",
        loop_interval_seconds=0.0,
        max_cycles=1,
        dry_run=False,
        fail_fast=False,
        continue_on_worker_failure=False,
    )

    logs: list[str] = []

    monkeypatch.setattr(supervisor_module, "_current_branch", lambda _config: "main")

    def _raise_ref_error(_config: Any) -> str:
        raise RuntimeError("symbolic-ref failed")

    monkeypatch.setattr(supervisor_module, "_resolve_git_ref", _raise_ref_error)
    monkeypatch.setattr(supervisor_module, "_log", logs.append)

    update_ok = supervisor_module._run_update_step(config)

    assert update_ok is False
    assert any("failed to resolve git ref" in log for log in logs)


def test_main_dry_run_defaults_to_one_cycle(
    monkeypatch: pytest.MonkeyPatch,
    supervisor_module: ModuleType,
    tmp_path: Path,
) -> None:
    calls: list[int] = []

    monkeypatch.setattr(supervisor_module, "_require_git_repo", lambda _repo: None)

    def _record_cycle(_config: Any, _passthrough: Any, cycle_number: int) -> int:
        calls.append(cycle_number)
        return 0

    monkeypatch.setattr(supervisor_module, "_run_cycle", _record_cycle)

    exit_code = supervisor_module.main(["--repo-path", str(tmp_path), "--dry-run"])

    assert exit_code == 0
    assert calls == [1]


def test_main_returns_error_for_missing_repo(supervisor_module: ModuleType, tmp_path: Path) -> None:
    missing_repo = tmp_path / "missing"

    exit_code = supervisor_module.main(["--repo-path", str(missing_repo), "--dry-run"])

    assert exit_code == 2

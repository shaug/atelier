from __future__ import annotations

from pathlib import Path

import pytest

from atelier import runtime_env


def test_sanitize_subprocess_environment_drops_runtime_routing_keys() -> None:
    env, removed = runtime_env.sanitize_subprocess_environment(
        base_env={
            "ATELIER_PROJECT": "/tmp/other",
            "ATELIER_WORKSPACE": "other/workspace",
            "ATELIER_MODE": "auto",
            "ATELIER_WORK_AGENT_TRACE": "1",
            "PATH": "/usr/bin",
        }
    )

    assert "ATELIER_PROJECT" not in env
    assert "ATELIER_WORKSPACE" not in env
    assert env["ATELIER_MODE"] == "auto"
    assert env["ATELIER_WORK_AGENT_TRACE"] == "1"
    assert env["PATH"] == "/usr/bin"
    assert removed == ("ATELIER_PROJECT", "ATELIER_WORKSPACE")


def test_format_ambient_env_warning_returns_none_when_no_keys() -> None:
    assert runtime_env.format_ambient_env_warning(()) is None


def test_format_ambient_env_warning_includes_removed_keys_and_migration_guidance() -> None:
    warning = runtime_env.format_ambient_env_warning(("ATELIER_PROJECT", "ATELIER_WORKSPACE"))

    assert warning is not None
    assert "ATELIER_PROJECT" in warning
    assert "ATELIER_WORKSPACE" in warning
    assert "--repo-dir" in warning
    assert "./worktree" in warning


def test_sanitize_subprocess_environment_empty_mapping_does_not_inherit_ambient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ATELIER_PROJECT", "/tmp/ambient")
    monkeypatch.setenv("ATELIER_WORKSPACE", "ambient/workspace")
    monkeypatch.setenv("PATH", "/usr/bin")

    env, removed = runtime_env.sanitize_subprocess_environment(base_env={})

    assert env == {}
    assert removed == ()


def test_projected_repo_python_command_prefers_repo_venv_python(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    python_path = repo_root / ".venv" / "bin" / "python3"
    python_path.parent.mkdir(parents=True)
    python_path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    python_path.chmod(python_path.stat().st_mode | 0o111)

    command = runtime_env.projected_repo_python_command(
        repo_root=repo_root,
        current_executable="/usr/bin/python3",
    )

    assert command == (str(python_path.resolve()),)


def test_projected_repo_python_command_returns_none_when_current_matches_repo_venv(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    python_path = repo_root / ".venv" / "bin" / "python3"
    python_path.parent.mkdir(parents=True)
    python_path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    python_path.chmod(python_path.stat().st_mode | 0o111)

    command = runtime_env.projected_repo_python_command(
        repo_root=repo_root,
        current_executable=str(python_path.resolve()),
    )

    assert command is None

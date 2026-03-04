from __future__ import annotations

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


def test_sanitize_subprocess_environment_empty_mapping_does_not_inherit_ambient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ATELIER_PROJECT", "/tmp/ambient")
    monkeypatch.setenv("ATELIER_WORKSPACE", "ambient/workspace")
    monkeypatch.setenv("PATH", "/usr/bin")

    env, removed = runtime_env.sanitize_subprocess_environment(base_env={})

    assert env == {}
    assert removed == ()

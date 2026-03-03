from __future__ import annotations

from atelier import runtime_env


def test_sanitize_subprocess_environment_drops_runtime_routing_keys() -> None:
    env, removed = runtime_env.sanitize_subprocess_environment(
        base_env={
            "ATELIER_PROJECT": "/tmp/other",
            "ATELIER_WORKSPACE": "other/workspace",
            "ATELIER_MODE": "auto",
            "PATH": "/usr/bin",
        }
    )

    assert "ATELIER_PROJECT" not in env
    assert "ATELIER_WORKSPACE" not in env
    assert env["ATELIER_MODE"] == "auto"
    assert env["PATH"] == "/usr/bin"
    assert removed == ("ATELIER_PROJECT", "ATELIER_WORKSPACE")


def test_format_ambient_env_warning_returns_none_when_no_keys() -> None:
    assert runtime_env.format_ambient_env_warning(()) is None

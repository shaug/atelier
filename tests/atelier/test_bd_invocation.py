from __future__ import annotations

import subprocess

import pytest

import atelier.bd_invocation as bd_invocation
from atelier.bd_invocation import with_bd_mode


def test_with_bd_mode_returns_direct_command() -> None:
    command = with_bd_mode("list", "--json", beads_dir=None, env={})

    assert command == ["bd", "list", "--json"]


def test_with_bd_mode_preserves_arguments() -> None:
    command = with_bd_mode("show", "at-1", beads_dir=None, env={})

    assert command == ["bd", "show", "at-1"]


def test_ensure_supported_bd_version_accepts_minimum(monkeypatch: pytest.MonkeyPatch) -> None:
    bd_invocation._read_bd_version_for_executable.cache_clear()
    monkeypatch.setattr(
        bd_invocation.shutil, "which", lambda *_args, **_kwargs: "/usr/local/bin/bd"
    )
    monkeypatch.setattr(
        bd_invocation.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=["bd", "--version"],
            returncode=0,
            stdout="bd version 0.51.0",
            stderr="",
        ),
    )

    bd_invocation.ensure_supported_bd_version(env={})


def test_ensure_supported_bd_version_rejects_older(monkeypatch: pytest.MonkeyPatch) -> None:
    bd_invocation._read_bd_version_for_executable.cache_clear()
    monkeypatch.setattr(
        bd_invocation.shutil, "which", lambda *_args, **_kwargs: "/usr/local/bin/bd"
    )
    monkeypatch.setattr(
        bd_invocation.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=["bd", "--version"],
            returncode=0,
            stdout="bd version 0.50.9",
            stderr="",
        ),
    )

    with pytest.raises(RuntimeError, match="requires bd >= 0.51.0"):
        bd_invocation.ensure_supported_bd_version(env={})


def test_ensure_supported_bd_version_rejects_missing_bd(monkeypatch: pytest.MonkeyPatch) -> None:
    bd_invocation._read_bd_version_for_executable.cache_clear()
    monkeypatch.setattr(bd_invocation.shutil, "which", lambda *_args, **_kwargs: None)

    with pytest.raises(RuntimeError, match="missing required command: bd"):
        bd_invocation.ensure_supported_bd_version(env={})


def test_ensure_supported_bd_version_accepts_override_minimum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bd_invocation._read_bd_version_for_executable.cache_clear()
    monkeypatch.setattr(
        bd_invocation.shutil, "which", lambda *_args, **_kwargs: "/usr/local/bin/bd"
    )
    monkeypatch.setattr(
        bd_invocation.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=["bd", "--version"],
            returncode=0,
            stdout="bd version 0.56.1",
            stderr="",
        ),
    )

    bd_invocation.ensure_supported_bd_version(env={}, min_version=(0, 56, 1))


def test_ensure_supported_bd_version_rejects_override_minimum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bd_invocation._read_bd_version_for_executable.cache_clear()
    monkeypatch.setattr(
        bd_invocation.shutil, "which", lambda *_args, **_kwargs: "/usr/local/bin/bd"
    )
    monkeypatch.setattr(
        bd_invocation.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=["bd", "--version"],
            returncode=0,
            stdout="bd version 0.56.0",
            stderr="",
        ),
    )

    with pytest.raises(RuntimeError, match="requires bd >= 0.56.1"):
        bd_invocation.ensure_supported_bd_version(env={}, min_version=(0, 56, 1))

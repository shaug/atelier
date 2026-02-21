"""Tests for typed command execution helpers."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from atelier import exec as exec_util


def test_subprocess_command_runner_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Runner returns typed output and forwards execution options."""
    calls: dict[str, object] = {}

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls["argv"] = argv
        calls["kwargs"] = kwargs
        return subprocess.CompletedProcess(argv, 0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    request = exec_util.CommandRequest(
        argv=("bd", "prime"),
        cwd=Path("/tmp"),
        env={"BEADS_DIR": "/tmp/beads"},
        capture_output=True,
        text=True,
        timeout_seconds=5.0,
        stdin=subprocess.DEVNULL,
    )
    result = exec_util.SubprocessCommandRunner().run(request)

    assert result == exec_util.CommandResult(
        argv=("bd", "prime"),
        returncode=0,
        stdout="ok",
        stderr="",
    )
    assert calls["argv"] == ["bd", "prime"]
    run_kwargs = calls["kwargs"]
    assert isinstance(run_kwargs, dict)
    assert run_kwargs["cwd"] == Path("/tmp")
    assert run_kwargs["env"] == {"BEADS_DIR": "/tmp/beads"}
    assert run_kwargs["capture_output"] is True
    assert run_kwargs["text"] is True
    assert run_kwargs["timeout"] == 5.0
    assert run_kwargs["stdin"] == subprocess.DEVNULL


def test_subprocess_command_runner_returns_none_when_missing_executable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Runner returns None when executable is not found."""

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        del argv, kwargs
        raise FileNotFoundError

    monkeypatch.setattr(subprocess, "run", fake_run)

    request = exec_util.CommandRequest(argv=("missing-cmd",))
    result = exec_util.SubprocessCommandRunner().run(request)

    assert result is None


def test_subprocess_command_runner_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """Runner normalizes timeout failures into typed timeout results."""

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        del kwargs
        raise subprocess.TimeoutExpired(
            cmd=argv, timeout=0.05, output="slow", stderr="timeout"
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    request = exec_util.CommandRequest(argv=("sleep", "1"), timeout_seconds=0.05)
    result = exec_util.SubprocessCommandRunner().run(request)

    assert result is not None
    assert result.timed_out is True
    assert result.returncode == 124
    assert result.stdout == "slow"
    assert result.stderr == "timeout"


def test_run_with_runner_uses_injected_runner() -> None:
    """run_with_runner uses the provided command-runner implementation."""

    class FakeRunner:
        def run(
            self, request: exec_util.CommandRequest
        ) -> exec_util.CommandResult | None:
            assert request.argv == ("git", "status")
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout="clean",
                stderr="",
            )

    result = exec_util.run_with_runner(
        exec_util.CommandRequest(argv=("git", "status")),
        runner=FakeRunner(),
    )

    assert result is not None
    assert result.stdout == "clean"


def test_run_command_forwards_env_and_cwd(monkeypatch: pytest.MonkeyPatch) -> None:
    """run_command builds the correct default command request shape."""
    captured: dict[str, object] = {}

    def fake_run_with_runner(
        request: exec_util.CommandRequest,
        *,
        runner: exec_util.CommandRunner | None = None,
    ) -> exec_util.CommandResult | None:
        del runner
        captured["request"] = request
        return exec_util.CommandResult(
            argv=request.argv,
            returncode=0,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(exec_util, "run_with_runner", fake_run_with_runner)

    exec_util.run_command(
        ["bd", "sync"], cwd=Path("/tmp/atelier"), env={"BEADS_DIR": "/tmp/beads"}
    )

    request = captured["request"]
    assert isinstance(request, exec_util.CommandRequest)
    assert request.argv == ("bd", "sync")
    assert request.cwd == Path("/tmp/atelier")
    assert request.env == {"BEADS_DIR": "/tmp/beads"}
    assert request.capture_output is False
    assert request.text is False


def test_run_command_fails_when_command_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """run_command exits when the command return code is non-zero."""

    def fake_run_with_runner(
        request: exec_util.CommandRequest,
        *,
        runner: exec_util.CommandRunner | None = None,
    ) -> exec_util.CommandResult | None:
        del request, runner
        return exec_util.CommandResult(
            argv=("bd", "sync"),
            returncode=2,
            stdout="",
            stderr="boom",
        )

    monkeypatch.setattr(exec_util, "run_with_runner", fake_run_with_runner)

    with pytest.raises(SystemExit):
        exec_util.run_command(["bd", "sync"])


def test_run_typed_parses_with_spec() -> None:
    """run_typed executes and parses typed command output."""

    class FakeRunner:
        def run(
            self, request: exec_util.CommandRequest
        ) -> exec_util.CommandResult | None:
            assert request.argv == ("bd", "status")
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout="7",
                stderr="",
            )

    spec = exec_util.CommandSpec[int](
        request=exec_util.CommandRequest(argv=("bd", "status")),
        parser=lambda result: int(result.stdout.strip()),
        context="status-int",
    )
    value = exec_util.run_typed(spec, runner=FakeRunner())
    assert value == 7


def test_run_typed_raises_execution_error_for_missing_command() -> None:
    """run_typed raises a typed execution error when executable is missing."""

    class MissingRunner:
        def run(
            self, request: exec_util.CommandRequest
        ) -> exec_util.CommandResult | None:
            del request
            return None

    spec = exec_util.CommandSpec[str](
        request=exec_util.CommandRequest(argv=("missing-cmd",)),
        parser=lambda result: result.stdout,
    )
    with pytest.raises(exec_util.CommandExecutionError) as exc:
        exec_util.run_typed(spec, runner=MissingRunner())

    assert "missing required command: missing-cmd" in str(exc.value)


def test_run_typed_raises_execution_error_for_non_zero_status() -> None:
    """run_typed raises a typed execution error when command fails."""

    class ErrorRunner:
        def run(
            self, request: exec_util.CommandRequest
        ) -> exec_util.CommandResult | None:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=3,
                stdout="",
                stderr="boom",
            )

    spec = exec_util.CommandSpec[str](
        request=exec_util.CommandRequest(argv=("bd", "sync")),
        parser=lambda result: result.stdout,
    )
    with pytest.raises(exec_util.CommandExecutionError) as exc:
        exec_util.run_typed(spec, runner=ErrorRunner())

    assert "command failed: bd sync" in str(exc.value)
    assert "boom" in str(exc.value)


def test_run_typed_raises_parse_error_with_context() -> None:
    """run_typed wraps parser failures in a deterministic parse error."""

    class GoodRunner:
        def run(
            self, request: exec_util.CommandRequest
        ) -> exec_util.CommandResult | None:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout="not-an-int",
                stderr="",
            )

    spec = exec_util.CommandSpec[int](
        request=exec_util.CommandRequest(argv=("bd", "status")),
        parser=lambda result: int(result.stdout.strip()),
        context="parse-int",
    )
    with pytest.raises(exec_util.CommandParseError) as exc:
        exec_util.run_typed(spec, runner=GoodRunner())

    assert "failed to parse command output (parse-int)" in str(exc.value)

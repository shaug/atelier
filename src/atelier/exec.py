"""Subprocess helpers for running external commands."""

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Generic, Mapping, Protocol, TypeVar

from .io import die

ParsedT = TypeVar("ParsedT")


@dataclass(frozen=True)
class CommandRequest:
    """Typed command invocation request."""

    argv: tuple[str, ...]
    cwd: Path | None = None
    env: Mapping[str, str] | None = None
    capture_output: bool = True
    text: bool = True
    timeout_seconds: float | None = None
    stdin: int | None = None


@dataclass(frozen=True)
class CommandResult:
    """Typed command execution result."""

    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False


class CommandRunner(Protocol):
    """Runtime command-execution interface."""

    def run(self, request: CommandRequest) -> CommandResult | None: ...


class SubprocessCommandRunner:
    """Default command-runner adapter backed by subprocess."""

    def run(self, request: CommandRequest) -> CommandResult | None:
        run_kwargs: dict[str, object] = {
            "cwd": request.cwd,
            "env": request.env,
            "check": False,
        }
        if request.capture_output:
            run_kwargs["capture_output"] = True
            run_kwargs["text"] = request.text
        if request.timeout_seconds is not None:
            run_kwargs["timeout"] = request.timeout_seconds
        if request.stdin is not None:
            run_kwargs["stdin"] = request.stdin
        try:
            completed = subprocess.run(list(request.argv), **run_kwargs)
        except FileNotFoundError:
            return None
        except subprocess.TimeoutExpired as exc:
            stdout = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
            stderr = (exc.stderr or "") if isinstance(exc.stderr, str) else ""
            return CommandResult(
                argv=request.argv,
                returncode=124,
                stdout=stdout,
                stderr=stderr,
                timed_out=True,
            )

        stdout = completed.stdout if isinstance(completed.stdout, str) else ""
        stderr = completed.stderr if isinstance(completed.stderr, str) else ""
        return CommandResult(
            argv=request.argv,
            returncode=completed.returncode,
            stdout=stdout,
            stderr=stderr,
        )


_DEFAULT_COMMAND_RUNNER: CommandRunner = SubprocessCommandRunner()


@dataclass(frozen=True)
class CommandSpec(Generic[ParsedT]):
    """Typed command spec with a parser for command output."""

    request: CommandRequest
    parser: Callable[[CommandResult], ParsedT]
    context: str | None = None


@dataclass(frozen=True)
class CommandExecutionError(RuntimeError):
    """Raised when command execution fails before parsing can occur."""

    request: CommandRequest
    detail: str
    result: CommandResult | None = None

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class CommandParseError(RuntimeError):
    """Raised when command output parsing fails."""

    request: CommandRequest
    detail: str
    context: str | None = None

    def __str__(self) -> str:
        return self.detail


def run_with_runner(
    request: CommandRequest, *, runner: CommandRunner | None = None
) -> CommandResult | None:
    """Execute a typed command request with the given runner."""
    active_runner = runner or _DEFAULT_COMMAND_RUNNER
    return active_runner.run(request)


def _missing_command_detail(request: CommandRequest) -> str:
    argv = request.argv
    if not argv:
        return "missing required command"
    return f"missing required command: {argv[0]}"


def _command_failure_detail(request: CommandRequest, result: CommandResult) -> str:
    output = (result.stderr or result.stdout or "").strip()
    command_text = " ".join(request.argv)
    if output:
        return f"command failed: {command_text}\n{output}"
    return f"command failed: {command_text}"


def run_typed(
    spec: CommandSpec[ParsedT], *, runner: CommandRunner | None = None
) -> ParsedT:
    """Execute a command and parse its successful output into a typed value."""
    result = run_with_runner(spec.request, runner=runner)
    if result is None:
        raise CommandExecutionError(
            request=spec.request,
            detail=_missing_command_detail(spec.request),
        )
    if result.returncode != 0:
        raise CommandExecutionError(
            request=spec.request,
            result=result,
            detail=_command_failure_detail(spec.request, result),
        )
    try:
        return spec.parser(result)
    except CommandParseError:
        raise
    except Exception as exc:
        context = f" ({spec.context})" if spec.context else ""
        raise CommandParseError(
            request=spec.request,
            detail=f"failed to parse command output{context}: {exc}",
            context=spec.context,
        ) from exc


def run_command(
    cmd: list[str],
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> None:
    """Run a command and raise a user-facing error on failure.

    Args:
        cmd: Command and arguments to execute.
        cwd: Optional working directory.

    Returns:
        None.

    Example:
        >>> run_command(["true"])
    """
    result = run_with_runner(
        CommandRequest(
            argv=tuple(cmd),
            cwd=cwd,
            env=env,
            capture_output=False,
            text=False,
        )
    )
    if result is None:
        die(f"missing required command: {cmd[0]}")
    if result.returncode != 0:
        die(f"command failed: {' '.join(cmd)}")


def run_git_command(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    """Run a Git command and return the ``CompletedProcess``.

    Args:
        cmd: Git command and arguments.

    Returns:
        ``subprocess.CompletedProcess`` with captured stdout/stderr.

    Example:
        >>> result = run_git_command(["git", "--version"])
        >>> result.returncode in {0, 1}
        True
    """
    try:
        return subprocess.run(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        die("missing required command: git")


def try_run_command(
    cmd: list[str],
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str] | None:
    """Run a command and return ``None`` if the executable is missing.

    Args:
        cmd: Command and arguments to execute.
        cwd: Optional working directory.

    Returns:
        ``CompletedProcess`` on execution, otherwise ``None``.

    Example:
        >>> isinstance(try_run_command(["true"]), subprocess.CompletedProcess)
        True
    """
    try:
        return subprocess.run(
            cmd, cwd=cwd, env=env, capture_output=True, text=True, check=False
        )
    except FileNotFoundError:
        return None


def run_command_status(
    cmd: list[str],
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str] | None:
    """Run a command and return the ``CompletedProcess`` or ``None`` if missing.

    Args:
        cmd: Command and arguments to execute.
        cwd: Optional working directory.

    Returns:
        ``CompletedProcess`` on execution, otherwise ``None``.
    """
    try:
        return subprocess.run(cmd, cwd=cwd, env=env, check=False)
    except FileNotFoundError:
        return None


def run_command_detached(
    cmd: list[str],
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> None:
    """Run a command without blocking the current process.

    Args:
        cmd: Command and arguments to execute.
        cwd: Optional working directory.

    Returns:
        None.
    """
    try:
        subprocess.Popen(cmd, cwd=cwd, env=env, start_new_session=True)
    except FileNotFoundError:
        die(f"missing required command: {cmd[0]}")

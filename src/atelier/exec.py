"""Subprocess helpers for running external commands."""

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Generic, Mapping, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from .io import die

ParsedT = TypeVar("ParsedT")
ModelT = TypeVar("ModelT", bound=BaseModel)


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


def _parse_json_payload(result: CommandResult, *, context: str | None = None) -> object:
    raw = (result.stdout or "").strip()
    if not raw:
        raise CommandParseError(
            request=CommandRequest(argv=result.argv),
            detail=(
                f"failed to parse command output ({context}): empty output"
                if context
                else "failed to parse command output: empty output"
            ),
            context=context,
        )
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        context_suffix = f" ({context})" if context else ""
        raise CommandParseError(
            request=CommandRequest(argv=result.argv),
            detail=f"failed to parse command output{context_suffix}: {exc}",
            context=context,
        ) from exc


def parse_json_model(
    result: CommandResult, *, model_type: type[ModelT], context: str | None = None
) -> ModelT:
    """Parse command stdout JSON into a validated Pydantic model."""
    payload = _parse_json_payload(result, context=context)
    try:
        return model_type.model_validate(payload)
    except ValidationError as exc:
        context_suffix = f" ({context})" if context else ""
        raise CommandParseError(
            request=CommandRequest(argv=result.argv),
            detail=f"failed to validate command output{context_suffix}: {exc}",
            context=context,
        ) from exc


def parse_json_model_optional(
    result: CommandResult, *, model_type: type[ModelT], context: str | None = None
) -> ModelT | None:
    """Parse optional JSON output into a validated Pydantic model."""
    raw = (result.stdout or "").strip()
    if not raw:
        return None
    return parse_json_model(result, model_type=model_type, context=context)


def parse_json_model_list(
    result: CommandResult, *, model_type: type[ModelT], context: str | None = None
) -> list[ModelT]:
    """Parse command stdout JSON array into validated Pydantic models."""
    payload = _parse_json_payload(result, context=context)
    if not isinstance(payload, list):
        context_suffix = f" ({context})" if context else ""
        raise CommandParseError(
            request=CommandRequest(argv=result.argv),
            detail=(
                f"failed to parse command output{context_suffix}: expected a JSON list"
            ),
            context=context,
        )
    models: list[ModelT] = []
    for index, item in enumerate(payload):
        try:
            models.append(model_type.model_validate(item))
        except ValidationError as exc:
            context_suffix = f" ({context})" if context else ""
            raise CommandParseError(
                request=CommandRequest(argv=result.argv),
                detail=(
                    f"failed to validate command output{context_suffix}"
                    f" at index {index}: {exc}"
                ),
                context=context,
            ) from exc
    return models


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

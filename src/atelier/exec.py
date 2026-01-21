"""Subprocess helpers for running external commands."""

import subprocess
from pathlib import Path

from .io import die


def run_command(cmd: list[str], cwd: Path | None = None) -> None:
    """Run a command and raise a user-facing error on failure.

    Args:
        cmd: Command and arguments to execute.
        cwd: Optional working directory.

    Returns:
        None.

    Example:
        >>> run_command(["true"])
    """
    try:
        subprocess.run(cmd, cwd=cwd, check=True)
    except FileNotFoundError:
        die(f"missing required command: {cmd[0]}")
    except subprocess.CalledProcessError:
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
    cmd: list[str], cwd: Path | None = None
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
        return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return None


def run_command_status(
    cmd: list[str], cwd: Path | None = None
) -> subprocess.CompletedProcess[str] | None:
    """Run a command and return the ``CompletedProcess`` or ``None`` if missing.

    Args:
        cmd: Command and arguments to execute.
        cwd: Optional working directory.

    Returns:
        ``CompletedProcess`` on execution, otherwise ``None``.
    """
    try:
        return subprocess.run(cmd, cwd=cwd, check=False)
    except FileNotFoundError:
        return None


def run_command_detached(cmd: list[str], cwd: Path | None = None) -> None:
    """Run a command without blocking the current process.

    Args:
        cmd: Command and arguments to execute.
        cwd: Optional working directory.

    Returns:
        None.
    """
    try:
        subprocess.Popen(cmd, cwd=cwd, start_new_session=True)
    except FileNotFoundError:
        die(f"missing required command: {cmd[0]}")

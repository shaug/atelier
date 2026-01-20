"""Console I/O helpers for user-facing messages and prompts."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path


def say(message: str) -> None:
    """Print a normal message to stdout.

    Args:
        message: Text to print.

    Returns:
        None.

    Example:
        >>> say("Hello")
    """
    print(message)


def warn(message: str) -> None:
    """Print a warning message to stderr.

    Args:
        message: Warning text.

    Returns:
        None.

    Example:
        >>> warn("Something looks off")
    """
    print(f"warning: {message}", file=sys.stderr)


def die(message: str, code: int = 1) -> None:
    """Print an error message and exit.

    Args:
        message: Error message to display.
        code: Exit code to use.

    Returns:
        None. Exits the process via ``sys.exit``.

    Example:
        >>> die("fatal", code=2)
    """
    print(f"error: {message}", file=sys.stderr)
    sys.exit(code)


def prompt(text: str, default: str | None = None, required: bool = False) -> str:
    """Prompt the user for input, optionally enforcing a default or requirement.

    Args:
        text: Prompt label shown to the user.
        default: Default value used when the user enters an empty string.
        required: When true, keep prompting until a non-empty value is provided.

    Returns:
        The user-provided or default string.

    Example:
        Branch prefix (optional) [scott/]:
    """
    while True:
        if default is not None and default != "":
            value = input(f"{text} [{default}]: ").strip()
            if value == "":
                value = default
        else:
            value = input(f"{text}: ").strip()
        if required and value == "":
            continue
        return value


def link_or_copy(src: Path, dest: Path) -> None:
    """Create a symlink from ``dest`` to ``src`` with copy fallback.

    Args:
        src: Source file path.
        dest: Destination file path.

    Returns:
        None.
    """
    if dest.exists() or dest.is_symlink():
        return
    try:
        dest.symlink_to(src)
        return
    except (OSError, NotImplementedError):
        pass
    shutil.copyfile(src, dest)

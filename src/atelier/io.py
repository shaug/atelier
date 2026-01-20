"""Console I/O helpers for user-facing messages and prompts."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

try:
    import questionary
except ImportError:  # pragma: no cover - safety fallback when dependency is missing
    questionary = None


def _use_questionary() -> bool:
    if questionary is None:
        return False
    return sys.stdin.isatty() and sys.stdout.isatty()


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


def prompt(
    text: str,
    default: str | None = None,
    required: bool = False,
    allow_empty: bool = False,
) -> str:
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
        if _use_questionary():
            question = questionary.text(text, default=default or "")
            value = question.ask()
            if value is None:
                die("aborted")
            value = str(value).strip()
        else:
            if default is not None and default != "":
                value = input(f"{text} [{default}]: ").strip()
                if value == "" and not allow_empty:
                    value = default
            else:
                value = input(f"{text}: ").strip()
        if required and value == "":
            continue
        return value


def confirm(text: str, default: bool = False) -> bool:
    """Prompt for a yes/no confirmation.

    Args:
        text: Prompt label shown to the user.
        default: Default answer when the user presses enter.

    Returns:
        ``True`` when the user confirms.
    """
    if _use_questionary():
        response = questionary.confirm(text, default=default).ask()
        return bool(response)
    suffix = "[Y/n]" if default else "[y/N]"
    response = input(f"{text} {suffix}: ").strip().lower()
    if response == "":
        return default
    return response in {"y", "yes"}


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

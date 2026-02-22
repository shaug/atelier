"""Conventional commit message validation helpers."""

from __future__ import annotations

import re
from pathlib import Path

_ALLOWED_TYPES: tuple[str, ...] = (
    "build",
    "chore",
    "ci",
    "docs",
    "feat",
    "fix",
    "perf",
    "refactor",
    "revert",
    "style",
    "test",
)
_HEADER_PATTERN = re.compile(
    r"^(?P<type>[a-z]+)\((?P<scope>[^()\s:]+)\)(?P<breaking>!)?: (?P<subject>.+)$"
)
_IGNORED_PREFIXES: tuple[str, ...] = ("Merge ", "Revert ", "fixup! ", "squash! ")


def _first_non_comment_line(message: str) -> str | None:
    for line in message.splitlines():
        candidate = line.strip()
        if candidate and not candidate.startswith("#"):
            return candidate
    return None


def validate_conventional_commit_header(header: str) -> str | None:
    """Validate a conventional-commit style header.

    Args:
        header: First non-empty, non-comment line from a commit message.

    Returns:
        ``None`` when valid or intentionally ignored, otherwise an error
        message describing the violation.
    """
    normalized = header.strip()
    if not normalized:
        return None
    if normalized.startswith(_IGNORED_PREFIXES):
        return None
    if len(normalized) > 100:
        return "commit header exceeds 100 characters"

    match = _HEADER_PATTERN.match(normalized)
    if match is None:
        return (
            "commit header must match '<type>(<scope>): <subject>' (optional breaking marker: '!')"
        )

    commit_type = match.group("type")
    if commit_type not in _ALLOWED_TYPES:
        allowed = ", ".join(_ALLOWED_TYPES)
        return f"unsupported commit type '{commit_type}' (allowed: {allowed})"

    subject = match.group("subject").strip()
    if not subject:
        return "commit subject must not be empty"
    return None


def validate_commit_message_file(path: Path) -> str | None:
    """Validate a commit message file.

    Args:
        path: Path to the commit message file supplied by git hooks.

    Returns:
        ``None`` when the message is valid, otherwise an error string.
    """
    try:
        payload = path.read_text(encoding="utf-8")
    except OSError as exc:
        return f"failed to read commit message file: {exc}"

    header = _first_non_comment_line(payload)
    if header is None:
        return None
    return validate_conventional_commit_header(header)

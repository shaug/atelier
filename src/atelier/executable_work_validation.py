"""Validation helpers for executable-work bead payloads.

This module centralizes low-information payload guards used by planner and
worker creation flows for executable work beads (epics/changesets).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

_TOKEN_PATTERN: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9]+")
_PLACEHOLDER_VALUES: Final[frozenset[str]] = frozenset(
    {
        "/",
        "//",
        "-",
        "--",
        ".",
        "..",
        "?",
        "??",
        "???",
        "n/a",
        "na",
        "none",
        "null",
        "todo",
        "tbd",
        "placeholder",
        "unknown",
        "tmp",
        "temp",
    }
)
_TITLE_MIN_ALNUM: Final[int] = 4
_TITLE_MIN_TOKENS: Final[int] = 1
_SCOPE_MIN_ALNUM: Final[int] = 6
_SCOPE_MIN_TOKENS: Final[int] = 2
_EXCERPT_MAX_CHARS: Final[int] = 80


@dataclass(frozen=True)
class ValidationFailure:
    """Represents a deterministic payload validation failure.

    Args:
        field_name: Input field name that failed validation.
        code: Stable machine-readable failure code.
        detail: Human-readable detail for diagnostics.
    """

    field_name: str
    code: str
    detail: str


def normalize_text(value: str) -> str:
    """Return whitespace-normalized text.

    Args:
        value: Raw string value from CLI arguments.

    Returns:
        String with internal whitespace collapsed and trimmed.
    """

    return " ".join(value.split())


def compact_excerpt(value: str, *, max_chars: int = _EXCERPT_MAX_CHARS) -> str:
    """Render a compact text excerpt for diagnostics.

    Args:
        value: Raw field value.
        max_chars: Maximum excerpt length.

    Returns:
        A single-line excerpt suitable for stderr output.
    """

    compacted = normalize_text(value)
    if not compacted:
        return "<empty>"
    if len(compacted) <= max_chars:
        return compacted
    return f"{compacted[: max_chars - 3]}..."


def validate_executable_work_payload(
    *,
    title: str,
    scope_text: str,
    scope_field_name: str,
    scope_optional: bool,
) -> tuple[ValidationFailure, ...]:
    """Validate executable-work creation payload fields.

    Args:
        title: Candidate title value.
        scope_text: Candidate scope-like text (`scope` or `description`).
        scope_field_name: Field name used in diagnostics for `scope_text`.
        scope_optional: Whether the scope field is optional.

    Returns:
        Tuple of validation failures. Empty tuple means valid payload.
    """

    failures: list[ValidationFailure] = []
    failures.extend(
        _validate_field(
            field_name="title",
            value=title,
            min_alnum=_TITLE_MIN_ALNUM,
            min_tokens=_TITLE_MIN_TOKENS,
            optional=False,
        )
    )
    failures.extend(
        _validate_field(
            field_name=scope_field_name,
            value=scope_text,
            min_alnum=_SCOPE_MIN_ALNUM,
            min_tokens=_SCOPE_MIN_TOKENS,
            optional=scope_optional,
        )
    )
    return tuple(failures)


def _validate_field(
    *,
    field_name: str,
    value: str,
    min_alnum: int,
    min_tokens: int,
    optional: bool,
) -> tuple[ValidationFailure, ...]:
    normalized = normalize_text(value)
    if not normalized:
        if optional:
            return ()
        return (
            ValidationFailure(
                field_name=field_name,
                code="missing_content",
                detail="value must not be empty",
            ),
        )

    lowered = normalized.lower()
    compacted = lowered.replace(" ", "")
    if lowered in _PLACEHOLDER_VALUES or compacted in _PLACEHOLDER_VALUES:
        return (
            ValidationFailure(
                field_name=field_name,
                code="placeholder_value",
                detail=f"placeholder value `{normalized}` is not allowed",
            ),
        )

    tokens = _TOKEN_PATTERN.findall(normalized)
    alnum_count = sum(len(token) for token in tokens)
    token_count = len(tokens)
    if alnum_count < min_alnum or token_count < min_tokens:
        return (
            ValidationFailure(
                field_name=field_name,
                code="insufficient_content",
                detail=(
                    f"requires at least {min_tokens} word(s) and {min_alnum} "
                    f"alphanumeric characters"
                ),
            ),
        )
    return ()

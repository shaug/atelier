"""Planner bead authoring contract helpers.

This module defines the richer worker-facing context contract for executable
work. Planner guardrails use it to verify that an executable path contains the
context workers need before implementation starts.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Final

from .executable_work_validation import normalize_text

_KEY_PATTERN: Final[re.Pattern[str]] = re.compile(r"[^a-z0-9]+")
_FIELD_HEADER_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^\s*(?:[-*+]\s+|\d+[.)]\s+)?([^:]+):\s*(.*?)\s*$"
)
_TEXT_FIELDS: Final[tuple[str, ...]] = ("description", "notes", "design")
_REQUIRED_FIELD_ALIASES: Final[dict[str, tuple[str, ...]]] = {
    "intent": ("intent",),
    "rationale": ("rationale",),
    "non_goals": ("non_goals", "non_goal"),
    "constraints": ("constraints", "constraint"),
    "edge_cases": ("edge_cases", "edge_case"),
    "related_context": (
        "related_context",
        "related_beads",
        "related_links",
        "broader_context",
    ),
}
_DONE_DEFINITION_ALIASES: Final[tuple[str, ...]] = (
    "done_definition",
    "success_definition",
)
_ACCEPTANCE_FIELDS: Final[tuple[str, ...]] = ("acceptance_criteria", "acceptance")
_SUPPORTED_FIELD_KEYS: Final[frozenset[str]] = frozenset(
    {
        alias
        for aliases in (*_REQUIRED_FIELD_ALIASES.values(), _DONE_DEFINITION_ALIASES)
        for alias in aliases
    }
)
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


def validate_authoring_contract(
    issue: Mapping[str, object],
    *,
    inherited_context: Sequence[Mapping[str, object]] = (),
) -> tuple[str, ...]:
    """Return missing planner authoring contract fields for an executable path.

    The contract is evaluated across the target issue plus any inherited epic
    context that will be presented to the worker alongside it.

    Args:
        issue: Target executable work bead payload.
        inherited_context: Additional issues that provide shared planner context,
            typically the parent epic for a child changeset.

    Returns:
        Tuple of canonical missing field names. Empty tuple means the combined
        executable path has the required context sections.
    """

    combined_fields = _collect_fields([*inherited_context, issue])
    missing: list[str] = []
    for field_name, aliases in _REQUIRED_FIELD_ALIASES.items():
        if any(_has_meaningful_value(combined_fields.get(alias, ())) for alias in aliases):
            continue
        missing.append(field_name)
    if not _has_done_definition([*inherited_context, issue], combined_fields):
        missing.append("done_definition")
    return tuple(missing)


def _collect_fields(issues: Sequence[Mapping[str, object]]) -> dict[str, tuple[str, ...]]:
    values: dict[str, list[str]] = {}
    for issue in issues:
        for field_name in _TEXT_FIELDS:
            raw_value = issue.get(field_name)
            if not isinstance(raw_value, str) or not raw_value.strip():
                continue
            for key, value in _iter_field_lines(raw_value):
                values.setdefault(key, []).append(value)
    return {key: tuple(items) for key, items in values.items()}


def _iter_field_lines(text: str) -> tuple[tuple[str, str], ...]:
    parsed: list[tuple[str, str]] = []
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        match = _FIELD_HEADER_PATTERN.match(lines[index])
        if match is None:
            index += 1
            continue
        normalized_key = _normalize_key(match.group(1))
        if normalized_key not in _SUPPORTED_FIELD_KEYS:
            index += 1
            continue
        inline_value = match.group(2).strip()
        if inline_value:
            parsed.append((normalized_key, inline_value))
            index += 1
            continue

        block_lines: list[str] = []
        index += 1
        while index < len(lines):
            next_line = lines[index]
            next_match = _FIELD_HEADER_PATTERN.match(next_line)
            if next_match is not None:
                next_key = _normalize_key(next_match.group(1))
                if next_key in _SUPPORTED_FIELD_KEYS:
                    break
            stripped_line = next_line.strip()
            if stripped_line:
                block_lines.append(stripped_line)
            index += 1
        parsed.append((normalized_key, "\n".join(block_lines).strip()))
    return tuple(parsed)


def _normalize_key(raw_key: str) -> str:
    normalized = _KEY_PATTERN.sub("_", raw_key.strip().lower()).strip("_")
    return normalized


def _has_meaningful_value(values: Sequence[str]) -> bool:
    for value in values:
        normalized = normalize_text(value)
        if not normalized:
            continue
        lowered = normalized.lower()
        compacted = lowered.replace(" ", "")
        if lowered in _PLACEHOLDER_VALUES or compacted in _PLACEHOLDER_VALUES:
            continue
        return True
    return False


def _has_done_definition(
    issues: Sequence[Mapping[str, object]],
    combined_fields: Mapping[str, tuple[str, ...]],
) -> bool:
    if any(
        _has_meaningful_value(combined_fields.get(alias, ())) for alias in _DONE_DEFINITION_ALIASES
    ):
        return True
    for issue in issues:
        for field_name in _ACCEPTANCE_FIELDS:
            raw_value = issue.get(field_name)
            if isinstance(raw_value, str) and _has_meaningful_value((raw_value,)):
                return True
    return False

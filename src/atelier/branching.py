"""Helpers for workspace root branch naming."""

from __future__ import annotations

import re

from . import workspace

_SEGMENT_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def slugify_title(title: str) -> str:
    """Return a lowercase, hyphenated slug for a title."""
    slug = _NON_ALNUM_RE.sub("-", title.strip().lower())
    slug = slug.strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    return slug


def suggest_root_branch(title: str, prefix: str, *, max_len: int = 30) -> str:
    """Suggest a root branch name from the title and prefix."""
    slug = slugify_title(title)
    if max_len and len(slug) > max_len:
        slug = slug[:max_len].rstrip("-")
    if prefix and slug and not slug.startswith(prefix):
        return f"{prefix}{slug}"
    return slug


def normalize_root_branch(value: str) -> str:
    """Normalize a root branch name."""
    return workspace.normalize_workspace_name(value)


def is_valid_root_branch(value: str) -> bool:
    """Return True when the root branch matches lowercase hyphenated segments."""
    if not value:
        return False
    normalized = normalize_root_branch(value)
    parts = [part for part in normalized.split("/") if part]
    if not parts:
        return False
    return all(_SEGMENT_RE.match(part) for part in parts)


def apply_branch_prefix(value: str, prefix: str) -> str:
    """Apply a branch prefix when not already present."""
    if not prefix:
        return value
    if value.startswith(prefix):
        return value
    return f"{prefix}{value}"


def candidates_for_root_branch(name: str, prefix: str, raw: bool) -> list[str]:
    """Return candidate root branch names for a user input."""
    normalized = normalize_root_branch(name)
    return workspace.workspace_candidate_branches(normalized, prefix, raw)

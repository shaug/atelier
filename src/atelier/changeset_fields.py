"""Shared helpers for parsing changeset metadata fields from bead issues."""

from __future__ import annotations

from . import beads, lifecycle


def issue_fields(issue: dict[str, object]) -> dict[str, str]:
    description = issue.get("description")
    return beads.parse_description_fields(description if isinstance(description, str) else "")


def normalized_field(fields: dict[str, str], key: str) -> str | None:
    raw = fields.get(key)
    if not isinstance(raw, str):
        return None
    normalized = raw.strip()
    if not normalized or normalized.lower() == "null":
        return None
    return normalized


def work_branch(issue: dict[str, object]) -> str | None:
    return normalized_field(issue_fields(issue), "changeset.work_branch")


def root_branch(issue: dict[str, object]) -> str | None:
    return normalized_field(issue_fields(issue), "changeset.root_branch")


def parent_branch(issue: dict[str, object]) -> str | None:
    return normalized_field(issue_fields(issue), "changeset.parent_branch")


def pr_url(issue: dict[str, object]) -> str | None:
    return normalized_field(issue_fields(issue), "pr_url")


def review_state(issue: dict[str, object]) -> str | None:
    fields = issue_fields(issue)
    return lifecycle.normalize_review_state(fields.get("pr_state"))

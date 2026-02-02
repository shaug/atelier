"""Changeset review metadata helpers."""

from __future__ import annotations

from dataclasses import dataclass

_FIELDS = ("pr_url", "pr_number", "pr_state", "review_owner")


@dataclass(frozen=True)
class ReviewMetadata:
    pr_url: str | None = None
    pr_number: str | None = None
    pr_state: str | None = None
    review_owner: str | None = None


def _normalize_value(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned or cleaned.lower() == "null":
        return None
    return cleaned


def _set_field(description: str, key: str, value: str | None) -> str:
    lines = description.splitlines() if description else []
    updated: list[str] = []
    needle = f"{key}:"
    found = False
    for line in lines:
        if line.strip().startswith(needle):
            if not found:
                replacement = value if value is not None else "null"
                updated.append(f"{key}: {replacement}")
                found = True
            continue
        updated.append(line)
    if not found:
        replacement = value if value is not None else "null"
        updated.append(f"{key}: {replacement}")
    return "\n".join(updated).rstrip("\n") + "\n"


def parse_review_metadata(description: str) -> ReviewMetadata:
    """Parse review metadata fields from a description."""
    values: dict[str, str | None] = {field: None for field in _FIELDS}
    for line in description.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        if key not in _FIELDS:
            continue
        values[key] = _normalize_value(value)
    return ReviewMetadata(
        pr_url=values["pr_url"],
        pr_number=values["pr_number"],
        pr_state=values["pr_state"],
        review_owner=values["review_owner"],
    )


def apply_review_metadata(description: str, metadata: ReviewMetadata) -> str:
    """Return a description updated with review metadata fields."""
    updated = description
    updated = _set_field(updated, "pr_url", metadata.pr_url)
    updated = _set_field(updated, "pr_number", metadata.pr_number)
    updated = _set_field(updated, "pr_state", metadata.pr_state)
    updated = _set_field(updated, "review_owner", metadata.review_owner)
    return updated

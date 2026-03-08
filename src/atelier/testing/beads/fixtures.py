"""Deterministic fixture builders for the in-memory Beads harness."""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_FIXTURE_TIMESTAMP = "2025-01-01T00:00:00Z"


def _dedupe_strings(values: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    return tuple(value for value in values if not (value in seen or seen.add(value)))


def _timestamp_for_value(value: int | str) -> str:
    if isinstance(value, int) and 0 <= value < 86400:
        hours, remainder = divmod(value, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"2025-01-01T{hours:02d}:{minutes:02d}:{seconds:02d}Z"
    return DEFAULT_FIXTURE_TIMESTAMP


def build_issue_reference(issue_id: str, *, title: str | None = None) -> dict[str, object]:
    """Build a stable Beads issue reference payload."""

    payload: dict[str, object] = {"id": issue_id}
    if title is not None:
        payload["title"] = title
    return payload


@dataclass(frozen=True)
class IssueFixtureBuilder:
    """Generate deterministic issue fixture payloads.

    Args:
        prefix: Issue id prefix used for integer-backed ids.
        default_issue_type: Issue type emitted when the caller does not provide
            one explicitly.
    """

    prefix: str = "at"
    default_issue_type: str = "task"

    def issue_id(self, value: int | str) -> str:
        """Return a canonical issue id for the fixture namespace."""

        if isinstance(value, int):
            return f"{self.prefix}-{value}"
        return value

    def reference(
        self,
        value: int | str,
        *,
        title: str | None = None,
    ) -> dict[str, object]:
        """Return a canonical issue reference payload."""

        return build_issue_reference(self.issue_id(value), title=title)

    def issue(
        self,
        value: int | str,
        *,
        title: str | None = None,
        issue_type: str | None = None,
        status: str = "open",
        labels: tuple[str, ...] = (),
        parent: int | str | None = None,
        dependencies: tuple[int | str, ...] = (),
        children: tuple[int | str, ...] = (),
        metadata: dict[str, object] | None = None,
        created_at: str | None = None,
        updated_at: str | None = None,
        description: str | None = None,
        design: str | None = None,
        acceptance_criteria: str | None = None,
        assignee: str | None = None,
        owner: str | None = None,
        priority: int | None = None,
        estimate: int | None = None,
        extra_fields: dict[str, object] | None = None,
    ) -> dict[str, object]:
        """Return a canonical issue payload with stable fields."""

        issue_id = self.issue_id(value)
        payload: dict[str, object] = {
            "id": issue_id,
            "title": title or f"Issue {issue_id}",
            "issue_type": issue_type or self.default_issue_type,
            "status": status,
            "labels": list(_dedupe_strings(labels)),
            "created_at": created_at or _timestamp_for_value(value),
            "updated_at": updated_at or _timestamp_for_value(value),
            "dependencies": [self.reference(item) for item in dependencies],
            "children": [self.reference(item) for item in children],
            "metadata": dict(metadata or {}),
        }
        if parent is not None:
            payload["parent"] = self.reference(parent)
        if description is not None:
            payload["description"] = description
        if design is not None:
            payload["design"] = design
        if acceptance_criteria is not None:
            payload["acceptance_criteria"] = acceptance_criteria
        if assignee is not None:
            payload["assignee"] = assignee
        if owner is not None:
            payload["owner"] = owner
        if priority is not None:
            payload["priority"] = priority
        if estimate is not None:
            payload["estimate"] = estimate
        if extra_fields:
            payload.update(extra_fields)
        return payload


def build_issue_payload(
    issue_id: str,
    *,
    title: str | None = None,
    issue_type: str = "task",
    status: str = "open",
    labels: tuple[str, ...] = (),
    metadata: dict[str, object] | None = None,
    extra_fields: dict[str, object] | None = None,
) -> dict[str, object]:
    """Build a single issue payload without creating a builder object."""

    builder = IssueFixtureBuilder()
    return builder.issue(
        issue_id,
        title=title,
        issue_type=issue_type,
        status=status,
        labels=labels,
        metadata=metadata,
        extra_fields=extra_fields,
    )


__all__ = [
    "DEFAULT_FIXTURE_TIMESTAMP",
    "IssueFixtureBuilder",
    "build_issue_payload",
    "build_issue_reference",
]

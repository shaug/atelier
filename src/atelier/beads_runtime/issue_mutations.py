"""Issue description mutation helpers for the Beads compatibility facade."""

from __future__ import annotations

from contextlib import AbstractContextManager
from pathlib import Path
from typing import Protocol


class IssueMutationsClient(Protocol):
    """External-system client boundary for issue description mutations."""

    def issue_write_lock(self, issue_id: str, beads_root: Path) -> AbstractContextManager[None]:
        """Acquire a scoped write lock for an issue."""
        ...

    def read_issue(
        self,
        issue_id: str,
        *,
        beads_root: Path,
        cwd: Path,
    ) -> dict[str, object] | None:
        """Read a single issue payload by id."""
        ...

    def update_issue_description(
        self,
        issue_id: str,
        description: str,
        *,
        beads_root: Path,
        cwd: Path,
    ) -> None:
        """Persist a full issue description."""
        ...

    def die(self, message: str) -> None:
        """Abort execution with a deterministic user-facing message."""
        ...


def parse_description_fields(description: str | None) -> dict[str, str]:
    """Parse key/value fields from an issue description."""
    fields: dict[str, str] = {}
    if not description:
        return fields
    for line in description.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        if not key:
            continue
        fields[key] = value.strip()
    return fields


def normalize_description_field_value(value: str | None) -> str | None:
    """Normalize description field values to ``None`` or trimmed strings."""
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned or cleaned.lower() == "null":
        return None
    return cleaned


def update_description_field(description: str | None, *, key: str, value: str | None) -> str:
    """Set or update a single description key/value field."""
    target = _normalize_description(description)
    lines = target.splitlines() if target else []
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


def issue_description_fields(
    issue_id: str,
    *,
    beads_root: Path,
    cwd: Path,
    client: IssueMutationsClient,
) -> dict[str, str]:
    """Read parsed description fields for a bead."""
    issue = client.read_issue(issue_id, beads_root=beads_root, cwd=cwd)
    if issue is None:
        return {}
    return parse_description_fields(_issue_description(issue))


def update_issue_description_fields(
    issue_id: str,
    fields: dict[str, str | None],
    *,
    beads_root: Path,
    cwd: Path,
    client: IssueMutationsClient,
    expected_current: dict[str, str | None] | None = None,
    require_expected_match: bool = False,
    description_update_max_attempts: int = 5,
) -> dict[str, object]:
    """Apply description field updates with optimistic retry + verification."""
    with client.issue_write_lock(issue_id, beads_root):
        for _attempt in range(max(0, description_update_max_attempts)):
            issue = client.read_issue(issue_id, beads_root=beads_root, cwd=cwd)
            if issue is None:
                client.die(f"issue not found: {issue_id}")
                raise RuntimeError("unreachable")
            if expected_current and not _description_matches_expected(
                issue,
                expected_current=expected_current,
            ):
                if require_expected_match:
                    return issue
                break

            updated = _issue_description(issue)
            changed = False
            for key, value in fields.items():
                next_value = update_description_field(updated, key=key, value=value)
                if next_value != updated:
                    changed = True
                    updated = next_value
            if not changed:
                return issue

            client.update_issue_description(issue_id, updated, beads_root=beads_root, cwd=cwd)
            candidate = client.read_issue(issue_id, beads_root=beads_root, cwd=cwd)
            if candidate is None:
                continue
            if expected_current and not _description_matches_expected(
                candidate,
                expected_current=expected_current,
            ):
                if require_expected_match:
                    return candidate
                continue
            if _description_matches_updates(candidate, fields=fields):
                return candidate
    client.die(f"concurrent description update conflict for {issue_id}")
    raise RuntimeError("unreachable")


def _normalize_description(description: str | None) -> str:
    if not description:
        return ""
    return description.rstrip("\n")


def _issue_description(issue: dict[str, object]) -> str:
    description = issue.get("description")
    return description if isinstance(description, str) else ""


def _description_matches_expected(
    issue: dict[str, object],
    *,
    expected_current: dict[str, str | None],
) -> bool:
    parsed = parse_description_fields(_issue_description(issue))
    for key, value in expected_current.items():
        current = normalize_description_field_value(parsed.get(key))
        expected = normalize_description_field_value(value)
        if current != expected:
            return False
    return True


def _description_matches_updates(
    issue: dict[str, object],
    *,
    fields: dict[str, str | None],
) -> bool:
    parsed = parse_description_fields(_issue_description(issue))
    for key, value in fields.items():
        current = normalize_description_field_value(parsed.get(key))
        expected = normalize_description_field_value(value)
        if current != expected:
            return False
    return True

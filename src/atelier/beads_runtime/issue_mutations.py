"""Issue description mutation helpers for the beads facade."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path


def parse_description_fields(
    description: str | None,
    *,
    parse_impl: Callable[[str | None], dict[str, str]],
) -> dict[str, str]:
    """Parse key/value description fields via the facade parser.

    Args:
        description: Raw issue description text.
        parse_impl: Parser implementation supplied by ``atelier.beads``.

    Returns:
        Parsed key/value field mapping.
    """
    return parse_impl(description)


def issue_description_fields(
    issue_id: str,
    *,
    beads_root: Path,
    cwd: Path,
    run_bd_json: Callable[..., list[dict[str, object]]],
    parse_impl: Callable[[str | None], dict[str, str]],
) -> dict[str, str]:
    """Read parsed description fields for a bead.

    Args:
        issue_id: Bead identifier to inspect.
        beads_root: Beads store root.
        cwd: Working directory for ``bd`` commands.
        run_bd_json: ``bd --json`` command runner.
        parse_impl: Description field parser.

    Returns:
        Parsed fields, or an empty dict when the issue is not found.
    """
    issues = run_bd_json(["show", issue_id], beads_root=beads_root, cwd=cwd)
    if not issues:
        return {}
    description = issues[0].get("description")
    text = description if isinstance(description, str) else ""
    return parse_impl(text)


def update_issue_description_fields(
    issue_id: str,
    fields: dict[str, str | None],
    *,
    beads_root: Path,
    cwd: Path,
    update_impl: Callable[..., dict[str, object]],
) -> dict[str, object]:
    """Apply upsert updates to issue description fields.

    Args:
        issue_id: Bead identifier to mutate.
        fields: Description field updates.
        beads_root: Beads store root.
        cwd: Working directory for ``bd`` commands.
        update_impl: Optimistic update implementation.

    Returns:
        Refreshed issue payload from the update implementation.
    """
    return update_impl(
        issue_id,
        fields=fields,
        beads_root=beads_root,
        cwd=cwd,
    )

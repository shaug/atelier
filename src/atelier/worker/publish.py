"""Worker publish/PR rendering helpers."""

from __future__ import annotations

import re

from .. import beads
from ..external_tickets import ExternalTicketRef

_GITHUB_ISSUE_URL_RE = re.compile(
    r"https://(?:api\.)?github\.com/(?:repos/)?[^/\s]+/[^/\s]+/issues/(?P<number>\d+)\b",
    re.IGNORECASE,
)
_GITHUB_REFERENCE_RE = re.compile(
    (
        r"https://(?:api\.)?github\.com/(?:repos/)?[^/\s]+/[^/\s]+/"
        r"issues/(?P<url_number>\d+)\b|#(?P<short_number>\d+)\b"
    ),
    re.IGNORECASE,
)
_EXPLICIT_GITHUB_CLAUSE_RE = re.compile(
    (
        r"\b(?P<action>fix(?:es|ed|ing)?|close(?:s|d)?|resolve(?:s|d)?|"
        r"address(?:es|ed|ing)?)\b"
        r"(?:\s+(?:issue|issues|ticket|tickets|bug|bugs)\b)?"
        r"\s*(?::|-)?\s*"
        r"(?P<references>"
        r"(?:https://(?:api\.)?github\.com/(?:repos/)?[^/\s]+/[^/\s]+/issues/\d+\b|#\d+\b)"
        r"(?:\s*(?:,|and|&)\s*"
        r"(?:https://(?:api\.)?github\.com/(?:repos/)?[^/\s]+/[^/\s]+/issues/\d+\b|#\d+\b))*"
        r")"
    ),
    re.IGNORECASE,
)


def normalized_markdown_bullets(value: str) -> list[str]:
    """Normalize multiline text into plain bullet items."""
    items: list[str] = []
    for raw in value.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("- "):
            line = line[2:].strip()
        elif line.startswith("* "):
            line = line[2:].strip()
        items.append(line)
    return items


def format_ticket_reference(ticket: ExternalTicketRef) -> str:
    """Format a user-facing ticket reference for PR descriptions.

    Args:
        ticket: External ticket reference payload.

    Returns:
        Display-ready ticket reference string.
    """
    ticket_id = (ticket.ticket_id or "").strip()
    if ticket.provider != "github":
        return ticket_id
    normalized = normalize_github_reference(ticket_id)
    if normalized:
        return normalized
    return normalize_github_reference(ticket.url or "") or ticket_id


def ticket_action_verb(ticket: ExternalTicketRef) -> str:
    """Resolve the PR ticket action verb for an external ticket.

    Args:
        ticket: External ticket reference payload.

    Returns:
        ``Fixes`` for resolvable tickets and ``Addresses`` for context tickets.
    """
    if ticket.relation == "context":
        return "Addresses"
    return "Fixes"


def normalize_github_reference(value: str) -> str | None:
    """Normalize GitHub issue references into ``#<number>`` form."""
    cleaned = value.strip()
    if not cleaned:
        return None
    if cleaned.startswith("#") and cleaned[1:].isdigit():
        return cleaned
    if cleaned.isdigit():
        return f"#{cleaned}"
    match = _GITHUB_ISSUE_URL_RE.search(cleaned)
    if match:
        return f"#{match.group('number')}"
    return None


def parse_explicit_github_references(description: str | None) -> list[tuple[str, str]]:
    """Parse explicit ``Fixes/Addresses`` GitHub references from free-form text."""
    if not description:
        return []

    references: list[tuple[str, str]] = []
    for match in _EXPLICIT_GITHUB_CLAUSE_RE.finditer(description):
        action_token = match.group("action").lower()
        action = "Addresses" if action_token.startswith("address") else "Fixes"
        segment = match.group("references")
        for reference_match in _GITHUB_REFERENCE_RE.finditer(segment):
            number = reference_match.group("url_number") or reference_match.group("short_number")
            if not number:
                continue
            references.append((action, f"#{number}"))
    return references


def _merge_ticket_line(
    *,
    key: tuple[str, str],
    reference: str,
    action: str,
    lines: list[str],
    seen: dict[tuple[str, str], int],
    actions: dict[tuple[str, str], str],
) -> None:
    position = seen.get(key)
    if position is None:
        seen[key] = len(lines)
        actions[key] = action
        lines.append(f"- {action} {reference}")
        return
    if actions.get(key) != "Fixes" and action == "Fixes":
        actions[key] = "Fixes"
        lines[position] = f"- Fixes {reference}"


def render_pr_ticket_lines(issue: dict[str, object]) -> list[str]:
    """Render PR ticket bullets from a bead issue payload.

    Args:
        issue: Bead issue payload.

    Returns:
        Ticket bullets for the PR ``Tickets`` section.
    """
    description = issue.get("description")
    tickets = beads.parse_external_tickets(description if isinstance(description, str) else None)
    lines: list[str] = []
    seen: dict[tuple[str, str], int] = {}
    actions: dict[tuple[str, str], str] = {}
    for ticket in tickets:
        reference = format_ticket_reference(ticket).strip()
        if not reference:
            continue
        dedupe_key = (ticket.provider, reference.lower())
        _merge_ticket_line(
            key=dedupe_key,
            reference=reference,
            action=ticket_action_verb(ticket),
            lines=lines,
            seen=seen,
            actions=actions,
        )
    for action, reference in parse_explicit_github_references(
        description if isinstance(description, str) else None
    ):
        dedupe_key = ("github", reference.lower())
        _merge_ticket_line(
            key=dedupe_key,
            reference=reference,
            action=action,
            lines=lines,
            seen=seen,
            actions=actions,
        )
    return lines


def render_changeset_pr_body(issue: dict[str, object], *, fields: dict[str, str]) -> str:
    """Render a user-facing PR body from bead fields."""
    summary = ""
    for key in ("scope", "intent", "summary", "rationale"):
        value = fields.get(key)
        if isinstance(value, str) and value.strip():
            summary = value.strip()
            break
    if not summary:
        summary = str(issue.get("title") or "Changeset implementation").strip()
    rationale = fields.get("rationale")
    rationale_text = rationale.strip() if isinstance(rationale, str) else ""
    acceptance_raw = issue.get("acceptance_criteria")
    acceptance_text = acceptance_raw.strip() if isinstance(acceptance_raw, str) else ""
    lines: list[str] = ["## Summary", summary]
    if rationale_text and rationale_text != summary:
        lines.extend(["", "## Why", rationale_text])
    if acceptance_text:
        lines.extend(["", "## Acceptance Criteria"])
        for item in normalized_markdown_bullets(acceptance_text):
            lines.append(f"- {item}")
    ticket_lines = render_pr_ticket_lines(issue)
    lines.extend(["", "## Tickets"])
    lines.extend(ticket_lines or ["- None"])
    return "\n".join(lines).strip()

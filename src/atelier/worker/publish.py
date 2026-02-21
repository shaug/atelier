"""Worker publish/PR rendering helpers."""

from __future__ import annotations

from .. import beads
from ..external_tickets import ExternalTicketRef


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
    if ticket.provider == "github":
        if ticket_id.startswith("#"):
            return ticket_id
        if ticket_id.isdigit():
            return f"#{ticket_id}"
    return ticket_id


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
    seen: set[tuple[str, str]] = set()
    for ticket in tickets:
        reference = format_ticket_reference(ticket).strip()
        if not reference:
            continue
        dedupe_key = (ticket.provider, reference.lower())
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        lines.append(f"- {ticket_action_verb(ticket)} {reference}")
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
    if ticket_lines:
        lines.extend(["", "## Tickets"])
        lines.extend(ticket_lines)
    return "\n".join(lines).strip()

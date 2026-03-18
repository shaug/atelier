"""Read-only helpers for parsing bead description metadata."""

from __future__ import annotations

import json

from atelier.external_tickets import ExternalTicketRef, normalize_external_ticket_entry

EXTERNAL_TICKETS_KEY = "external_tickets"


def normalize_description(description: str | None) -> str:
    """Return a stable description string for comparisons and formatting."""

    if not description:
        return ""
    return description.rstrip("\n")


def parse_description_fields(description: str | None) -> dict[str, str]:
    """Parse colon-delimited key/value fields from a bead description."""

    fields: dict[str, str] = {}
    if not description:
        return fields
    for line in description.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        cleaned_key = key.strip()
        if not cleaned_key:
            continue
        fields[cleaned_key] = value.strip()
    return fields


def normalize_field_value(value: str | None) -> str | None:
    """Normalize one parsed description field value."""

    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned or cleaned.lower() == "null":
        return None
    return cleaned


def parse_external_tickets(description: str | None) -> list[ExternalTicketRef]:
    """Parse persisted external ticket metadata from one description."""

    if not description:
        return []
    fields = parse_description_fields(description)
    tickets_raw = fields.get(EXTERNAL_TICKETS_KEY)
    if not tickets_raw or tickets_raw.lower() == "null":
        return []
    try:
        payload = json.loads(tickets_raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    tickets: list[ExternalTicketRef] = []
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        normalized = normalize_external_ticket_entry(entry)
        if normalized is None:
            continue
        tickets.append(normalized)
    return tickets

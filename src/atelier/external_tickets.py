"""Schema helpers for external ticket linkage."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

EXTERNAL_TICKET_RELATIONS = ("primary", "secondary", "context", "derived")
EXTERNAL_TICKET_DIRECTIONS = ("imported", "exported", "linked")
EXTERNAL_TICKET_SYNC_MODES = ("manual", "import", "export", "sync")
EXTERNAL_TICKET_STATES = (
    "open",
    "in_progress",
    "blocked",
    "in_review",
    "closed",
    "unknown",
)
EXTERNAL_TICKET_ON_CLOSE_ACTIONS = ("none", "comment", "close", "sync")

_RELATION_ALIASES = {
    "context_only": "context",
    "reference": "context",
    "child": "derived",
}
_DIRECTION_ALIASES = {
    "import": "imported",
    "export": "exported",
}
_SYNC_MODE_ALIASES = {
    "pull": "import",
    "import_only": "import",
    "read_only": "import",
    "push": "export",
    "export_only": "export",
    "write_only": "export",
    "bidirectional": "sync",
    "two_way": "sync",
    "both": "sync",
    "none": "manual",
}
_STATE_ALIASES = {
    "inprogress": "in_progress",
    "in-progress": "in_progress",
    "in review": "in_review",
    "in-review": "in_review",
    "todo": "open",
}


@dataclass(frozen=True)
class ExternalTicketRef:
    """Canonical reference to an external ticket.

    Fields:
        provider: Normalized provider slug (for example: github, linear, jira).
        ticket_id: Provider ticket id/key (preserves case).
        url: Optional canonical URL.
        title: Optional cached ticket title.
        summary: Optional short summary snippet.
        body: Optional cached ticket body.
        notes: Optional cached notes from provider.
        relation: primary|secondary|context|derived.
        direction: imported|exported|linked.
        sync_mode: manual|import|export|sync.
        state: open|in_progress|blocked|in_review|closed|unknown.
        raw_state: Provider-native state string when captured.
        state_updated_at: Optional ISO-8601 timestamp for cached state.
        parent_id: Optional provider parent ticket id.
        on_close: none|comment|close|sync.
        content_updated_at: Optional ISO-8601 timestamp for cached content.
        notes_updated_at: Optional ISO-8601 timestamp for cached notes.
        last_synced_at: Optional ISO-8601 timestamp for last sync.
    """

    provider: str
    ticket_id: str
    url: str | None = None
    title: str | None = None
    summary: str | None = None
    body: str | None = None
    notes: str | None = None
    relation: str | None = None
    direction: str | None = None
    sync_mode: str | None = None
    state: str | None = None
    raw_state: str | None = None
    state_updated_at: str | None = None
    parent_id: str | None = None
    on_close: str | None = None
    content_updated_at: str | None = None
    notes_updated_at: str | None = None
    last_synced_at: str | None = None


def normalize_optional_string(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    return None


def normalize_slug(value: object) -> str | None:
    cleaned = normalize_optional_string(value)
    if cleaned is None:
        return None
    return cleaned.lower()


def normalize_identifier(value: object) -> str | None:
    cleaned = normalize_optional_string(value)
    if cleaned is None:
        return None
    return cleaned


def _normalize_enum(
    value: object,
    *,
    allowed: tuple[str, ...],
    aliases: dict[str, str] | None = None,
) -> str | None:
    cleaned = normalize_optional_string(value)
    if cleaned is None:
        return None
    key = cleaned.lower().replace("-", "_").replace(" ", "_")
    if aliases and key in aliases:
        return aliases[key]
    if key in allowed:
        return key
    return None


def normalize_relation(value: object) -> str | None:
    return _normalize_enum(value, allowed=EXTERNAL_TICKET_RELATIONS, aliases=_RELATION_ALIASES)


def normalize_direction(value: object) -> str | None:
    return _normalize_enum(value, allowed=EXTERNAL_TICKET_DIRECTIONS, aliases=_DIRECTION_ALIASES)


def normalize_sync_mode(value: object) -> str | None:
    return _normalize_enum(value, allowed=EXTERNAL_TICKET_SYNC_MODES, aliases=_SYNC_MODE_ALIASES)


def normalize_state(value: object) -> str | None:
    return _normalize_enum(value, allowed=EXTERNAL_TICKET_STATES, aliases=_STATE_ALIASES)


def normalize_on_close(value: object) -> str | None:
    return _normalize_enum(value, allowed=EXTERNAL_TICKET_ON_CLOSE_ACTIONS, aliases=None)


def normalize_timestamp(value: object) -> str | None:
    cleaned = normalize_optional_string(value)
    if cleaned is None:
        return None
    candidate = cleaned.replace("Z", "+00:00")
    try:
        dt.datetime.fromisoformat(candidate)
    except ValueError:
        return None
    return cleaned


def normalize_external_ticket_entry(
    entry: dict[str, object],
) -> ExternalTicketRef | None:
    provider = normalize_slug(entry.get("provider"))
    ticket_id = normalize_identifier(entry.get("id") or entry.get("ticket_id"))
    if not provider or not ticket_id:
        return None
    return ExternalTicketRef(
        provider=provider,
        ticket_id=ticket_id,
        url=normalize_optional_string(entry.get("url")),
        title=normalize_optional_string(entry.get("title")),
        summary=normalize_optional_string(entry.get("summary")),
        body=normalize_optional_string(entry.get("body")),
        notes=normalize_optional_string(entry.get("notes")),
        relation=normalize_relation(entry.get("relation")),
        direction=normalize_direction(entry.get("direction")),
        sync_mode=normalize_sync_mode(entry.get("sync_mode")),
        state=normalize_state(entry.get("state")),
        raw_state=normalize_optional_string(entry.get("raw_state")),
        state_updated_at=normalize_timestamp(entry.get("state_updated_at")),
        parent_id=normalize_optional_string(entry.get("parent_id")),
        on_close=normalize_on_close(entry.get("on_close")),
        content_updated_at=normalize_timestamp(entry.get("content_updated_at")),
        notes_updated_at=normalize_timestamp(entry.get("notes_updated_at")),
        last_synced_at=normalize_timestamp(entry.get("last_synced_at")),
    )


def external_ticket_payload(ticket: ExternalTicketRef) -> dict[str, object]:
    payload: dict[str, object] = {"provider": ticket.provider, "id": ticket.ticket_id}
    if ticket.url is not None:
        payload["url"] = ticket.url
    if ticket.title is not None:
        payload["title"] = ticket.title
    if ticket.summary is not None:
        payload["summary"] = ticket.summary
    if ticket.body is not None:
        payload["body"] = ticket.body
    if ticket.notes is not None:
        payload["notes"] = ticket.notes
    if ticket.relation is not None:
        payload["relation"] = ticket.relation
    if ticket.direction is not None:
        payload["direction"] = ticket.direction
    if ticket.sync_mode is not None:
        payload["sync_mode"] = ticket.sync_mode
    if ticket.state is not None:
        payload["state"] = ticket.state
    if ticket.raw_state is not None:
        payload["raw_state"] = ticket.raw_state
    if ticket.state_updated_at is not None:
        payload["state_updated_at"] = ticket.state_updated_at
    if ticket.parent_id is not None:
        payload["parent_id"] = ticket.parent_id
    if ticket.on_close is not None:
        payload["on_close"] = ticket.on_close
    if ticket.content_updated_at is not None:
        payload["content_updated_at"] = ticket.content_updated_at
    if ticket.notes_updated_at is not None:
        payload["notes_updated_at"] = ticket.notes_updated_at
    if ticket.last_synced_at is not None:
        payload["last_synced_at"] = ticket.last_synced_at
    return payload


def validate_external_ticket_ref(ticket: ExternalTicketRef) -> list[str]:
    errors: list[str] = []
    if not ticket.provider:
        errors.append("provider is required")
    if not ticket.ticket_id:
        errors.append("ticket_id is required")
    if ticket.relation and ticket.relation not in EXTERNAL_TICKET_RELATIONS:
        errors.append(f"relation must be one of {EXTERNAL_TICKET_RELATIONS}")
    if ticket.direction and ticket.direction not in EXTERNAL_TICKET_DIRECTIONS:
        errors.append(f"direction must be one of {EXTERNAL_TICKET_DIRECTIONS}")
    if ticket.sync_mode and ticket.sync_mode not in EXTERNAL_TICKET_SYNC_MODES:
        errors.append(f"sync_mode must be one of {EXTERNAL_TICKET_SYNC_MODES}")
    if ticket.state and ticket.state not in EXTERNAL_TICKET_STATES:
        errors.append(f"state must be one of {EXTERNAL_TICKET_STATES}")
    if ticket.on_close and ticket.on_close not in EXTERNAL_TICKET_ON_CLOSE_ACTIONS:
        errors.append(f"on_close must be one of {EXTERNAL_TICKET_ON_CLOSE_ACTIONS}")
    if ticket.state_updated_at and normalize_timestamp(ticket.state_updated_at) is None:
        errors.append("state_updated_at must be ISO-8601")
    if ticket.last_synced_at and normalize_timestamp(ticket.last_synced_at) is None:
        errors.append("last_synced_at must be ISO-8601")
    if ticket.content_updated_at and normalize_timestamp(ticket.content_updated_at) is None:
        errors.append("content_updated_at must be ISO-8601")
    if ticket.notes_updated_at and normalize_timestamp(ticket.notes_updated_at) is None:
        errors.append("notes_updated_at must be ISO-8601")
    return errors

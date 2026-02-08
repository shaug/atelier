from __future__ import annotations

from atelier.external_tickets import (
    ExternalTicketRef,
    external_ticket_payload,
    normalize_external_ticket_entry,
    normalize_state,
    normalize_sync_mode,
    validate_external_ticket_ref,
)


def test_normalize_external_ticket_entry_aliases() -> None:
    entry = {
        "provider": "GitHub",
        "id": "ABC-1",
        "relation": "context_only",
        "direction": "export",
        "sync_mode": "two_way",
        "state": "in review",
        "on_close": "comment",
        "state_updated_at": "2026-02-08T10:00:00Z",
        "last_synced_at": "2026-02-08T11:00:00+00:00",
    }
    ticket = normalize_external_ticket_entry(entry)
    assert ticket is not None
    assert ticket.provider == "github"
    assert ticket.ticket_id == "ABC-1"
    assert ticket.relation == "context"
    assert ticket.direction == "exported"
    assert ticket.sync_mode == "sync"
    assert ticket.state == "in_review"
    assert ticket.on_close == "comment"
    assert ticket.state_updated_at == "2026-02-08T10:00:00Z"
    assert ticket.last_synced_at == "2026-02-08T11:00:00+00:00"


def test_normalize_external_ticket_entry_rejects_missing_fields() -> None:
    assert normalize_external_ticket_entry({"provider": "github"}) is None
    assert normalize_external_ticket_entry({"id": "1"}) is None


def test_normalize_external_ticket_entry_drops_invalid_timestamp() -> None:
    entry = {"provider": "github", "id": "1", "state_updated_at": "nope"}
    ticket = normalize_external_ticket_entry(entry)
    assert ticket is not None
    assert ticket.state_updated_at is None


def test_external_ticket_payload_omits_none_fields() -> None:
    ticket = ExternalTicketRef(provider="github", ticket_id="1")
    payload = external_ticket_payload(ticket)
    assert payload == {"provider": "github", "id": "1"}


def test_validate_external_ticket_ref_reports_bad_values() -> None:
    ticket = ExternalTicketRef(
        provider="github",
        ticket_id="1",
        relation="bogus",
        sync_mode="bogus",
    )
    errors = validate_external_ticket_ref(ticket)
    assert any("relation" in error for error in errors)
    assert any("sync_mode" in error for error in errors)


def test_normalizers_lowercase_and_map() -> None:
    assert normalize_sync_mode("Import_Only") == "import"
    assert normalize_state("In-Progress") == "in_progress"

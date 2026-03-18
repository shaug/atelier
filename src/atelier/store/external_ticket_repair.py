"""Store-owned repair flow for missing external ticket metadata."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

from atelier.lib.beads import IssueRecord, ListIssuesRequest
from atelier.lib.beads import description_fields as bead_fields

from .contract import RepairExternalTicketMetadataRequest, UpdateExternalTicketsRequest
from .models import ExternalTicketLink, ExternalTicketMetadataRepairResult

if TYPE_CHECKING:
    from .beads_store import AtelierStore


def _normalized_labels(values: tuple[str, ...]) -> set[str]:
    return {value.strip() for value in values if value.strip()}


def _persisted_tickets(issue: IssueRecord) -> tuple[ExternalTicketLink, ...]:
    tickets = bead_fields.parse_external_tickets(issue.description or "")
    return tuple(ExternalTicketLink.from_external_ref(ticket) for ticket in tickets)


def _beads_root(beads: object) -> Path | None:
    root = getattr(beads, "_beads_root", None)
    if isinstance(root, Path):
        return root
    resolve = getattr(beads, "_resolve_beads_root", None)
    if callable(resolve):
        resolved = resolve()
        if isinstance(resolved, Path):
            return resolved
    return None


def _history_from_issue_store(
    beads: object,
    issue_id: str,
) -> tuple[tuple[str | None, str | None], ...]:
    issue_store = getattr(beads, "_issue_store", None)
    if issue_store is None:
        return ()
    history = getattr(issue_store, "description_history", None)
    if not callable(history):
        return ()
    records = history(issue_id)
    return records if isinstance(records, tuple) else ()


def _description_from_sqlite_payload(payload: object) -> str | None:
    if not isinstance(payload, str) or not payload.strip():
        return None
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    description = parsed.get("description")
    return description if isinstance(description, str) else None


def _recover_from_in_memory_history(
    beads: object,
    issue_id: str,
) -> tuple[ExternalTicketLink, ...]:
    for old_description, new_description in reversed(_history_from_issue_store(beads, issue_id)):
        for description in (new_description, old_description):
            tickets = bead_fields.parse_external_tickets(description)
            if tickets:
                return tuple(ExternalTicketLink.from_external_ref(ticket) for ticket in tickets)
    return ()


def _recover_from_sqlite_history(
    beads: object,
    issue_id: str,
) -> tuple[ExternalTicketLink, ...]:
    beads_root = _beads_root(beads)
    if beads_root is None:
        return ()
    db_path = beads_root / "beads.db"
    if not db_path.exists():
        return ()
    try:
        with sqlite3.connect(db_path) as connection:
            rows = connection.execute(
                """
                SELECT old_value, new_value
                FROM events
                WHERE issue_id = ?
                  AND event_type = 'updated'
                ORDER BY id DESC
                """,
                (issue_id,),
            )
            for old_value, new_value in rows:
                for payload in (new_value, old_value):
                    description = _description_from_sqlite_payload(payload)
                    tickets = bead_fields.parse_external_tickets(description)
                    if tickets:
                        return tuple(
                            ExternalTicketLink.from_external_ref(ticket) for ticket in tickets
                        )
    except sqlite3.Error:
        return ()
    return ()


def _recover_tickets(beads: object, issue_id: str) -> tuple[ExternalTicketLink, ...]:
    in_memory = _recover_from_in_memory_history(beads, issue_id)
    if in_memory:
        return in_memory
    return _recover_from_sqlite_history(beads, issue_id)


async def repair_external_ticket_metadata(
    store: "AtelierStore",
    request: RepairExternalTicketMetadataRequest,
) -> tuple[ExternalTicketMetadataRepairResult, ...]:
    """Repair missing external ticket metadata through the store boundary.

    Args:
        store: Concrete store implementation that owns repair semantics.
        request: Repair selection and whether recovered metadata should be
            persisted back to the store.

    Returns:
        One result per issue with provider labels but missing persisted external
        ticket metadata.
    """

    if request.issue_ids:
        issues_list: list[IssueRecord] = []
        for issue_id in request.issue_ids:
            issues_list.append(await store._show_issue(issue_id))
        issues = tuple(issues_list)
    else:
        issues = await store._beads.list(
            ListIssuesRequest(include_closed=True, limit=store.scan_limit)
        )

    results: list[ExternalTicketMetadataRepairResult] = []
    for issue in issues:
        providers = tuple(
            sorted(
                label.removeprefix("ext:")
                for label in _normalized_labels(issue.labels)
                if label.startswith("ext:")
            )
        )
        if not providers:
            continue
        if _persisted_tickets(issue):
            continue
        recovered_tickets = _recover_tickets(store._beads, issue.id)
        repaired = False
        if recovered_tickets and request.apply:
            await store.update_external_tickets(
                UpdateExternalTicketsRequest(issue_id=issue.id, tickets=recovered_tickets)
            )
            repaired = True
        results.append(
            ExternalTicketMetadataRepairResult(
                issue_id=issue.id,
                providers=providers,
                recovered=bool(recovered_tickets),
                repaired=repaired,
                ticket_count=len(recovered_tickets),
            )
        )
    return tuple(sorted(results, key=lambda item: item.issue_id))

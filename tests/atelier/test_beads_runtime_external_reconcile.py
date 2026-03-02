from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from atelier.beads_runtime import external_reconcile
from atelier.external_tickets import ExternalTicketRef


@dataclass(frozen=True)
class _Result:
    issue_id: str
    stale_exported_github_tickets: int
    reconciled_tickets: int
    updated: bool
    needs_decision_notes: tuple[str, ...]


def _github_ticket(*, ticket_id: str, state: str) -> ExternalTicketRef:
    return ExternalTicketRef(
        provider="github",
        ticket_id=ticket_id,
        direction="exported",
        state=state,
        relation="derived",
        url="https://github.com/owner/repo/issues/1",
    )


def test_reconcile_closed_issue_records_missing_repo_note() -> None:
    notes: list[str] = []

    result = external_reconcile.reconcile_closed_issue_exported_github_tickets(
        "at-1",
        beads_root=Path("/beads"),
        cwd=Path("/repo"),
        run_bd_json=lambda _args, **_kwargs: [
            {"id": "at-1", "status": "closed", "description": "x"}
        ],
        parse_external_tickets=lambda _description: [_github_ticket(ticket_id="77", state="open")],
        close_action_for_ticket=lambda _ticket: "close",
        github_repo_from_ticket_url=lambda _url: None,
        merge_ticket_state=lambda ticket, refreshed, assume_closed=False: ticket,
        update_external_tickets=lambda _issue_id, _tickets, **_kwargs: {},
        append_external_close_note=lambda _issue_id, note, **_kwargs: notes.append(note),
        result_factory=_Result,
    )

    assert result.stale_exported_github_tickets == 1
    assert result.reconciled_tickets == 0
    assert result.updated is False
    assert notes
    assert "missing repo slug" in notes[0]


def test_reconcile_reopened_issue_records_missing_repo_note() -> None:
    notes: list[str] = []

    result = external_reconcile.reconcile_reopened_issue_exported_github_tickets(
        "at-1",
        beads_root=Path("/beads"),
        cwd=Path("/repo"),
        run_bd_json=lambda _args, **_kwargs: [
            {"id": "at-1", "status": "in_progress", "description": "x"}
        ],
        parse_external_tickets=lambda _description: [
            _github_ticket(ticket_id="88", state="closed")
        ],
        github_repo_from_ticket_url=lambda _url: None,
        merge_ticket_state=lambda ticket, refreshed, assume_closed=False: ticket,
        update_external_tickets=lambda _issue_id, _tickets, **_kwargs: {},
        append_external_reopen_note=lambda _issue_id, note, **_kwargs: notes.append(note),
        result_factory=_Result,
    )

    assert result.stale_exported_github_tickets == 1
    assert result.reconciled_tickets == 0
    assert result.updated is False
    assert notes
    assert "cannot reopen exported ticket state" in notes[0]

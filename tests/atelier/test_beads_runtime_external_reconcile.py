from __future__ import annotations

from dataclasses import dataclass, field

from atelier.beads_runtime import external_reconcile
from atelier.external_tickets import ExternalTicketRef


@dataclass(frozen=True)
class _Result:
    issue_id: str
    stale_exported_github_tickets: int
    reconciled_tickets: int
    updated: bool
    needs_decision_notes: tuple[str, ...]


@dataclass
class _Provider:
    close_result: ExternalTicketRef | None = None
    reopen_result: ExternalTicketRef | None = None

    def close_ticket(
        self,
        ticket: ExternalTicketRef,
        *,
        comment: str | None = None,
    ) -> ExternalTicketRef:
        del ticket, comment
        if self.close_result is not None:
            return self.close_result
        raise RuntimeError("close unavailable")

    def sync_state(self, ticket: ExternalTicketRef) -> ExternalTicketRef:
        return ticket

    def reopen_ticket(
        self,
        ticket: ExternalTicketRef,
        *,
        comment: str | None = None,
    ) -> ExternalTicketRef:
        del ticket, comment
        if self.reopen_result is not None:
            return self.reopen_result
        raise RuntimeError("reopen unavailable")


@dataclass
class _Client:
    issue: dict[str, object] | None
    notes: list[str]
    provider: _Provider = field(default_factory=_Provider)

    def show_issue(self, issue_id: str) -> dict[str, object] | None:
        del issue_id
        return self.issue

    def parse_external_tickets(self, description: str | None) -> list[ExternalTicketRef]:
        del description
        return []

    def github_repo_from_ticket_url(self, url: str | None) -> str | None:
        del url
        return None

    def github_provider(self, repo_slug: str) -> _Provider:
        del repo_slug
        return self.provider

    def merge_ticket_state(
        self,
        ticket: ExternalTicketRef,
        refreshed: ExternalTicketRef,
        *,
        assume_closed: bool = False,
    ) -> ExternalTicketRef:
        del assume_closed
        return refreshed if refreshed is not None else ticket

    def update_external_tickets(
        self,
        issue_id: str,
        tickets: list[ExternalTicketRef],
    ) -> dict[str, object]:
        del issue_id, tickets
        return {}

    def append_external_close_note(self, issue_id: str, note: str) -> None:
        del issue_id
        self.notes.append(note)

    def append_external_reopen_note(self, issue_id: str, note: str) -> None:
        del issue_id
        self.notes.append(note)


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
    client = _Client(issue={"id": "at-1", "status": "closed", "description": "x"}, notes=notes)
    client.parse_external_tickets = lambda _description: [
        _github_ticket(ticket_id="77", state="open")
    ]  # type: ignore[method-assign]

    result = external_reconcile.reconcile_closed_issue_exported_github_tickets(
        "at-1",
        client=client,
        result_factory=_Result,
    )

    assert result.stale_exported_github_tickets == 1
    assert result.reconciled_tickets == 0
    assert result.updated is False
    assert notes
    assert "missing repo slug" in notes[0]


def test_reconcile_reopened_issue_records_missing_repo_note() -> None:
    notes: list[str] = []
    client = _Client(issue={"id": "at-1", "status": "in_progress", "description": "x"}, notes=notes)
    client.parse_external_tickets = (  # type: ignore[method-assign]
        lambda _description: [_github_ticket(ticket_id="88", state="closed")]
    )

    result = external_reconcile.reconcile_reopened_issue_exported_github_tickets(
        "at-1",
        client=client,
        result_factory=_Result,
    )

    assert result.stale_exported_github_tickets == 1
    assert result.reconciled_tickets == 0
    assert result.updated is False
    assert notes
    assert "cannot reopen exported ticket state" in notes[0]

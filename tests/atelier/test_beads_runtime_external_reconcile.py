from __future__ import annotations

import json
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
class _IssueStore:
    issue: dict[str, object] | None
    notes: list[str]
    updated_tickets: list[ExternalTicketRef] | None = None

    def show_issue(self, issue_id: str) -> dict[str, object] | None:
        del issue_id
        return self.issue

    def update_external_tickets(
        self,
        issue_id: str,
        tickets: list[ExternalTicketRef],
    ) -> dict[str, object]:
        del issue_id
        self.updated_tickets = list(tickets)
        return {}

    def append_external_close_note(self, issue_id: str, note: str) -> None:
        del issue_id
        self.notes.append(note)

    def append_external_reopen_note(self, issue_id: str, note: str) -> None:
        del issue_id
        self.notes.append(note)


@dataclass
class _GithubClient:
    provider: _Provider = field(default_factory=_Provider)

    def github_repo_from_ticket_url(self, url: str | None) -> str | None:
        return external_reconcile.github_repo_from_ticket_url(url)

    def github_provider(self, repo_slug: str) -> _Provider:
        del repo_slug
        return self.provider


def _issue_with_tickets(*, status: str, tickets: list[dict[str, object]]) -> dict[str, object]:
    return {
        "id": "at-1",
        "status": status,
        "description": f"external_tickets: {json.dumps(tickets)}\n",
    }


def test_reconcile_closed_issue_records_missing_repo_note() -> None:
    notes: list[str] = []
    issue_store = _IssueStore(
        issue=_issue_with_tickets(
            status="closed",
            tickets=[
                {
                    "provider": "github",
                    "id": "77",
                    "direction": "exported",
                    "state": "open",
                    "relation": "derived",
                }
            ],
        ),
        notes=notes,
    )

    result = external_reconcile.reconcile_closed_issue_exported_github_tickets(
        "at-1",
        issue_store=issue_store,
        github=_GithubClient(),
        result_factory=_Result,
    )

    assert result.stale_exported_github_tickets == 1
    assert result.reconciled_tickets == 0
    assert result.updated is False
    assert notes
    assert "missing repo slug" in notes[0]


def test_reconcile_reopened_issue_records_missing_repo_note() -> None:
    notes: list[str] = []
    issue_store = _IssueStore(
        issue=_issue_with_tickets(
            status="in_progress",
            tickets=[
                {
                    "provider": "github",
                    "id": "88",
                    "direction": "exported",
                    "state": "closed",
                    "relation": "derived",
                }
            ],
        ),
        notes=notes,
    )

    result = external_reconcile.reconcile_reopened_issue_exported_github_tickets(
        "at-1",
        issue_store=issue_store,
        github=_GithubClient(),
        result_factory=_Result,
    )

    assert result.stale_exported_github_tickets == 1
    assert result.reconciled_tickets == 0
    assert result.updated is False
    assert notes
    assert "cannot reopen exported ticket state" in notes[0]

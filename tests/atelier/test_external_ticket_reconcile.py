from __future__ import annotations

import pytest

from atelier.external_ticket_reconcile import (
    ExternalTicketReconcileOutcome,
    reconcile_exported_github_tickets,
)
from atelier.external_tickets import ExternalTicketRef


def test_reconcile_exported_github_tickets_reopens_closed_exports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    issue_id = "at-change"
    ticket = ExternalTicketRef(
        provider="github",
        ticket_id="179",
        url="https://api.github.com/repos/acme/widgets/issues/179",
        direction="exported",
        state="closed",
        parent_id="174",
    )

    def fake_reopen(self, ref, *, comment=None):
        assert comment == (
            f"Reopening external ticket because local bead {issue_id} is active again."
        )
        assert ref == ticket
        return ExternalTicketRef(
            provider="github",
            ticket_id="179",
            url="https://github.com/acme/widgets/issues/179",
            direction="exported",
            state="open",
            raw_state="open",
            state_updated_at="2026-03-26T03:00:00Z",
            parent_id="200",
        )

    monkeypatch.setattr(
        "atelier.github_issues_provider.GithubIssuesProvider.reopen_ticket",
        fake_reopen,
    )

    result = reconcile_exported_github_tickets(
        issue_id=issue_id,
        tickets=(ticket,),
        reopen=True,
    )

    assert result.stale_exported_github_tickets == 1
    assert result.reconciled_tickets == 1
    assert result.updated is True
    assert result.needs_decision_notes == ()
    (merged_ticket,) = result.merged_tickets
    assert merged_ticket.provider == "github"
    assert merged_ticket.ticket_id == "179"
    assert merged_ticket.url == "https://github.com/acme/widgets/issues/179"
    assert merged_ticket.direction == "exported"
    assert merged_ticket.state == "open"
    assert merged_ticket.raw_state == "open"
    assert merged_ticket.state_updated_at == "2026-03-26T03:00:00Z"
    assert merged_ticket.parent_id == "200"
    assert merged_ticket.last_synced_at is not None


def test_reconcile_exported_github_tickets_closes_open_exports_with_comment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    issue_id = "at-change"
    ticket = ExternalTicketRef(
        provider="github",
        ticket_id="180",
        url="https://api.github.com/repos/acme/widgets/issues/180",
        direction="exported",
        state="open",
        on_close="comment",
    )

    def fake_close(self, ref, *, comment=None):
        assert comment == f"Closing external ticket because local bead {issue_id} is closed."
        assert ref == ticket
        return ExternalTicketRef(
            provider="github",
            ticket_id="180",
            url="https://github.com/acme/widgets/issues/180",
            direction="exported",
            state="closed",
            raw_state="closed",
            state_updated_at="2026-03-26T03:05:00Z",
        )

    monkeypatch.setattr(
        "atelier.github_issues_provider.GithubIssuesProvider.close_ticket",
        fake_close,
    )

    result = reconcile_exported_github_tickets(
        issue_id=issue_id,
        tickets=(ticket,),
        reopen=False,
    )

    assert result.stale_exported_github_tickets == 1
    assert result.reconciled_tickets == 1
    assert result.updated is True
    assert result.needs_decision_notes == ()
    (merged_ticket,) = result.merged_tickets
    assert merged_ticket.provider == "github"
    assert merged_ticket.ticket_id == "180"
    assert merged_ticket.url == "https://github.com/acme/widgets/issues/180"
    assert merged_ticket.direction == "exported"
    assert merged_ticket.state == "closed"
    assert merged_ticket.raw_state == "closed"
    assert merged_ticket.state_updated_at == "2026-03-26T03:05:00Z"
    assert merged_ticket.on_close == "comment"
    assert merged_ticket.last_synced_at is not None

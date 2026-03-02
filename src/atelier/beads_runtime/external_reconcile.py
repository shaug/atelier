"""External ticket reconciliation helpers for the beads facade."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, TypeVar

from ..external_tickets import ExternalTicketRef

ReconcileResultT = TypeVar("ReconcileResultT")


class GithubTicketProvider(Protocol):
    """External provider API used by GitHub ticket reconciliation."""

    def close_ticket(
        self,
        ticket: ExternalTicketRef,
        *,
        comment: str | None = None,
    ) -> ExternalTicketRef:
        """Close a GitHub ticket and return refreshed state."""
        ...

    def sync_state(self, ticket: ExternalTicketRef) -> ExternalTicketRef:
        """Read latest GitHub ticket state without mutation."""
        ...

    def reopen_ticket(
        self,
        ticket: ExternalTicketRef,
        *,
        comment: str | None = None,
    ) -> ExternalTicketRef:
        """Reopen a GitHub ticket and return refreshed state."""
        ...


class ExternalReconcileClient(Protocol):
    """Cohesive boundary for external ticket reconciliation operations."""

    def show_issue(self, issue_id: str) -> dict[str, object] | None:
        """Load issue payload by id."""
        ...

    def parse_external_tickets(self, description: str | None) -> list[ExternalTicketRef]:
        """Parse external ticket metadata from issue description."""
        ...

    def github_repo_from_ticket_url(self, url: str | None) -> str | None:
        """Resolve a GitHub repo slug from a ticket URL."""
        ...

    def github_provider(self, repo_slug: str) -> GithubTicketProvider:
        """Return a provider instance for the given GitHub repository."""
        ...

    def merge_ticket_state(
        self,
        ticket: ExternalTicketRef,
        refreshed: ExternalTicketRef,
        *,
        assume_closed: bool = False,
    ) -> ExternalTicketRef:
        """Merge provider state into a stored ticket reference."""
        ...

    def update_external_tickets(
        self,
        issue_id: str,
        tickets: list[ExternalTicketRef],
    ) -> dict[str, object]:
        """Persist updated external ticket metadata for an issue."""
        ...

    def append_external_close_note(self, issue_id: str, note: str) -> None:
        """Append a close reconciliation note for operator follow-up."""
        ...

    def append_external_reopen_note(self, issue_id: str, note: str) -> None:
        """Append a reopen reconciliation note for operator follow-up."""
        ...


def _close_action_for_ticket(ticket: ExternalTicketRef) -> str:
    # Keep context and explicit opt-out links untouched on local close.
    if ticket.relation == "context" or ticket.on_close == "none":
        return "none"
    if ticket.on_close in {"close", "comment"}:
        return "close"
    if ticket.on_close == "sync":
        return "sync"
    if ticket.direction != "exported":
        return "none"
    return "close"


def reconcile_closed_issue_exported_github_tickets(
    issue_id: str,
    *,
    client: ExternalReconcileClient,
    result_factory: Callable[..., ReconcileResultT],
) -> ReconcileResultT:
    """Reconcile stale exported GitHub ticket metadata for a closed bead."""
    issue = client.show_issue(issue_id)
    if issue is None:
        return result_factory(
            issue_id=issue_id,
            stale_exported_github_tickets=0,
            reconciled_tickets=0,
            updated=False,
            needs_decision_notes=tuple(),
        )
    status = str(issue.get("status") or "").strip().lower()
    if status not in {"closed", "done"}:
        return result_factory(
            issue_id=issue_id,
            stale_exported_github_tickets=0,
            reconciled_tickets=0,
            updated=False,
            needs_decision_notes=tuple(),
        )
    description = issue.get("description")
    existing_tickets = client.parse_external_tickets(
        description if isinstance(description, str) else None
    )
    if not existing_tickets:
        return result_factory(
            issue_id=issue_id,
            stale_exported_github_tickets=0,
            reconciled_tickets=0,
            updated=False,
            needs_decision_notes=tuple(),
        )

    stale = 0
    reconciled = 0
    updated = False
    notes: list[str] = []
    provider_cache: dict[str, GithubTicketProvider] = {}
    merged_tickets: list[ExternalTicketRef] = []
    for ticket in existing_tickets:
        if ticket.provider != "github" or ticket.direction != "exported":
            merged_tickets.append(ticket)
            continue
        if ticket.state == "closed":
            merged_tickets.append(ticket)
            continue
        stale += 1
        action = _close_action_for_ticket(ticket)
        if action == "none":
            merged_tickets.append(ticket)
            continue
        repo_slug = client.github_repo_from_ticket_url(ticket.url)
        if not repo_slug:
            notes.append(
                f"github:{ticket.ticket_id} missing repo slug; "
                "cannot reconcile exported ticket state"
            )
            merged_tickets.append(ticket)
            continue
        provider = provider_cache.get(repo_slug)
        if provider is None:
            provider = client.github_provider(repo_slug)
            provider_cache[repo_slug] = provider
        close_comment = None
        if ticket.on_close == "comment":
            close_comment = f"Closing external ticket because local bead {issue_id} is closed."
        try:
            if action == "close":
                refreshed = provider.close_ticket(ticket, comment=close_comment)
                merged = client.merge_ticket_state(ticket, refreshed, assume_closed=True)
            else:
                refreshed = provider.sync_state(ticket)
                merged = client.merge_ticket_state(ticket, refreshed, assume_closed=False)
        except RuntimeError as exc:
            notes.append(f"github:{ticket.ticket_id} {exc}")
            merged_tickets.append(ticket)
            continue
        merged_tickets.append(merged)
        reconciled += 1
        if merged != ticket:
            updated = True

    if updated:
        client.update_external_tickets(issue_id, merged_tickets)

    unique_notes: list[str] = []
    seen_notes: set[str] = set()
    for note in notes:
        if note in seen_notes:
            continue
        seen_notes.add(note)
        unique_notes.append(note)
        client.append_external_close_note(issue_id, note)

    return result_factory(
        issue_id=issue_id,
        stale_exported_github_tickets=stale,
        reconciled_tickets=reconciled,
        updated=updated,
        needs_decision_notes=tuple(unique_notes),
    )


def reconcile_reopened_issue_exported_github_tickets(
    issue_id: str,
    *,
    client: ExternalReconcileClient,
    result_factory: Callable[..., ReconcileResultT],
) -> ReconcileResultT:
    """Reopen stale exported GitHub tickets when a local bead reopens."""
    issue = client.show_issue(issue_id)
    if issue is None:
        return result_factory(
            issue_id=issue_id,
            stale_exported_github_tickets=0,
            reconciled_tickets=0,
            updated=False,
            needs_decision_notes=tuple(),
        )
    status = str(issue.get("status") or "").strip().lower()
    if status in {"closed", "done"}:
        return result_factory(
            issue_id=issue_id,
            stale_exported_github_tickets=0,
            reconciled_tickets=0,
            updated=False,
            needs_decision_notes=tuple(),
        )
    description = issue.get("description")
    existing_tickets = client.parse_external_tickets(
        description if isinstance(description, str) else None
    )
    if not existing_tickets:
        return result_factory(
            issue_id=issue_id,
            stale_exported_github_tickets=0,
            reconciled_tickets=0,
            updated=False,
            needs_decision_notes=tuple(),
        )

    stale = 0
    reconciled = 0
    updated = False
    notes: list[str] = []
    provider_cache: dict[str, GithubTicketProvider] = {}
    merged_tickets: list[ExternalTicketRef] = []
    for ticket in existing_tickets:
        if ticket.provider != "github" or ticket.direction != "exported":
            merged_tickets.append(ticket)
            continue
        if ticket.state != "closed":
            merged_tickets.append(ticket)
            continue
        stale += 1
        repo_slug = client.github_repo_from_ticket_url(ticket.url)
        if not repo_slug:
            notes.append(
                f"github:{ticket.ticket_id} missing repo slug; cannot reopen exported ticket state"
            )
            merged_tickets.append(ticket)
            continue
        provider = provider_cache.get(repo_slug)
        if provider is None:
            provider = client.github_provider(repo_slug)
            provider_cache[repo_slug] = provider
        try:
            refreshed = provider.reopen_ticket(
                ticket,
                comment=f"Reopening external ticket because local bead {issue_id} is active again.",
            )
            merged = client.merge_ticket_state(ticket, refreshed, assume_closed=False)
        except RuntimeError as exc:
            notes.append(f"github:{ticket.ticket_id} {exc}")
            merged_tickets.append(ticket)
            continue
        merged_tickets.append(merged)
        reconciled += 1
        if merged != ticket:
            updated = True

    if updated:
        client.update_external_tickets(issue_id, merged_tickets)

    unique_notes: list[str] = []
    seen_notes: set[str] = set()
    for note in notes:
        if note in seen_notes:
            continue
        seen_notes.add(note)
        unique_notes.append(note)
        client.append_external_reopen_note(issue_id, note)

    return result_factory(
        issue_id=issue_id,
        stale_exported_github_tickets=stale,
        reconciled_tickets=reconciled,
        updated=updated,
        needs_decision_notes=tuple(unique_notes),
    )

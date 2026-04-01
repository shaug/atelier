"""Provider-owned helpers for exported external ticket reconciliation."""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from urllib.parse import urlparse

from .external_tickets import ExternalTicketRef
from .github_issues_provider import GithubIssuesProvider

_GITHUB_API_ISSUE_PATH = re.compile(r"^/repos/(?P<owner>[^/]+)/(?P<repo>[^/]+)/issues/[^/]+$")
_GITHUB_WEB_ISSUE_PATH = re.compile(r"^/(?P<owner>[^/]+)/(?P<repo>[^/]+)/issues/[^/]+$")


@dataclass(frozen=True)
class ExternalTicketReconcileOutcome:
    """Result of one exported GitHub reconciliation attempt.

    Attributes:
        stale_exported_github_tickets: Number of stale exported GitHub tickets
            observed in the input.
        reconciled_tickets: Number of stale tickets for which a provider
            operation completed successfully.
        merged_tickets: Output ticket state, preserving untouched entries and
            merging refreshed provider data for reconciled tickets.
        updated: Whether any ticket metadata changed relative to the input.
        needs_decision_notes: Deduplicated operator notes for tickets that could
            not be reconciled automatically.
    """

    stale_exported_github_tickets: int
    reconciled_tickets: int
    merged_tickets: tuple[ExternalTicketRef, ...]
    updated: bool
    needs_decision_notes: tuple[str, ...] = ()


def reconcile_exported_github_tickets(
    *,
    issue_id: str,
    tickets: tuple[ExternalTicketRef, ...],
    reopen: bool,
) -> ExternalTicketReconcileOutcome:
    """Reconcile exported GitHub ticket state for one local issue.

    Args:
        issue_id: Local bead identifier that owns the exported tickets.
        tickets: Persisted external ticket metadata for the local issue.
        reopen: When true, reopen stale closed exports. When false, reconcile
            stale open exports for a closed local issue.

    Returns:
        The provider-owned reconciliation outcome, including merged ticket
        state and any decision notes for failures that must stay fail-closed.
    """
    stale = 0
    reconciled = 0
    updated = False
    notes: list[str] = []
    provider_cache: dict[str, GithubIssuesProvider] = {}
    merged_tickets: list[ExternalTicketRef] = []

    for ticket in tickets:
        if ticket.provider != "github" or ticket.direction != "exported":
            merged_tickets.append(ticket)
            continue
        if reopen and ticket.state != "closed":
            merged_tickets.append(ticket)
            continue
        if not reopen and ticket.state == "closed":
            merged_tickets.append(ticket)
            continue

        stale += 1
        action = "reopen" if reopen else _close_action_for_ticket(ticket)
        if action == "none":
            merged_tickets.append(ticket)
            continue
        repo_slug = _github_repo_from_ticket_url(ticket.url)
        if repo_slug is None:
            problem = (
                "cannot reopen exported ticket state"
                if reopen
                else "cannot reconcile exported ticket state"
            )
            notes.append(f"github:{ticket.ticket_id} missing repo slug; {problem}")
            merged_tickets.append(ticket)
            continue
        provider = provider_cache.get(repo_slug)
        if provider is None:
            provider = GithubIssuesProvider(repo=repo_slug)
            provider_cache[repo_slug] = provider

        try:
            merged = _run_provider_reconcile(
                issue_id=issue_id,
                provider=provider,
                ticket=ticket,
                action=action,
            )
        except RuntimeError as exc:
            notes.append(f"github:{ticket.ticket_id} {exc}")
            merged_tickets.append(ticket)
            continue

        merged_tickets.append(merged)
        reconciled += 1
        if merged != ticket:
            updated = True

    return ExternalTicketReconcileOutcome(
        stale_exported_github_tickets=stale,
        reconciled_tickets=reconciled,
        merged_tickets=tuple(merged_tickets),
        updated=updated,
        needs_decision_notes=_dedupe_preserve_order(notes),
    )


def _dedupe_preserve_order(values: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    return tuple(value for value in values if not (value in seen or seen.add(value)))


def _run_provider_reconcile(
    *,
    issue_id: str,
    provider: GithubIssuesProvider,
    ticket: ExternalTicketRef,
    action: str,
) -> ExternalTicketRef:
    if action == "reopen":
        refreshed = provider.reopen_ticket(
            ticket,
            comment=f"Reopening external ticket because local bead {issue_id} is active again.",
        )
        return _merge_ticket_state(ticket, refreshed)
    if action == "close":
        close_comment = None
        if ticket.on_close == "comment":
            close_comment = f"Closing external ticket because local bead {issue_id} is closed."
        refreshed = provider.close_ticket(ticket, comment=close_comment)
        return _merge_ticket_state(ticket, refreshed, assume_closed=True)
    refreshed = provider.sync_state(ticket)
    return _merge_ticket_state(ticket, refreshed)


def _github_repo_from_ticket_url(url: str | None) -> str | None:
    cleaned = (url or "").strip()
    if not cleaned:
        return None
    parsed = urlparse(cleaned)
    host = parsed.netloc.lower().split(":", 1)[0]
    path = parsed.path or ""
    if host == "api.github.com":
        match = _GITHUB_API_ISSUE_PATH.match(path)
    elif host in {"github.com", "www.github.com"}:
        match = _GITHUB_WEB_ISSUE_PATH.match(path)
    else:
        return None
    if not match:
        return None
    owner = match.group("owner").strip()
    repo = match.group("repo").strip()
    if not owner or not repo:
        return None
    return f"{owner}/{repo}"


def _close_action_for_ticket(ticket: ExternalTicketRef) -> str:
    if ticket.relation == "context" or ticket.on_close == "none":
        return "none"
    if ticket.on_close in {"close", "comment"}:
        return "close"
    if ticket.on_close == "sync":
        return "sync"
    if ticket.direction != "exported":
        return "none"
    return "close"


def _merge_ticket_state(
    ticket: ExternalTicketRef,
    refreshed: ExternalTicketRef,
    *,
    assume_closed: bool = False,
) -> ExternalTicketRef:
    return ExternalTicketRef(
        provider=ticket.provider,
        ticket_id=ticket.ticket_id,
        url=refreshed.url or ticket.url,
        title=refreshed.title or ticket.title,
        summary=refreshed.summary or ticket.summary,
        body=refreshed.body or ticket.body,
        notes=refreshed.notes or ticket.notes,
        relation=ticket.relation,
        direction=ticket.direction,
        sync_mode=ticket.sync_mode,
        state=refreshed.state or ("closed" if assume_closed else ticket.state),
        raw_state=refreshed.raw_state or ticket.raw_state,
        state_updated_at=refreshed.state_updated_at or ticket.state_updated_at,
        parent_id=refreshed.parent_id or ticket.parent_id,
        on_close=ticket.on_close,
        content_updated_at=refreshed.content_updated_at or ticket.content_updated_at,
        notes_updated_at=refreshed.notes_updated_at or ticket.notes_updated_at,
        last_synced_at=(
            refreshed.last_synced_at or dt.datetime.now(tz=dt.timezone.utc).isoformat()
        ),
    )

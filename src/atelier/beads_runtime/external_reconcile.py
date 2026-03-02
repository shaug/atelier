"""External ticket reconciliation helpers for the beads facade."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from ..external_tickets import ExternalTicketRef

RunBdJson = Callable[..., list[dict[str, object]]]
ReconcileResultT = TypeVar("ReconcileResultT")


def reconcile_closed_issue_exported_github_tickets(
    issue_id: str,
    *,
    beads_root: Path,
    cwd: Path,
    run_bd_json: RunBdJson,
    parse_external_tickets: Callable[[str | None], list[ExternalTicketRef]],
    close_action_for_ticket: Callable[[ExternalTicketRef], str],
    github_repo_from_ticket_url: Callable[[str | None], str | None],
    merge_ticket_state: Callable[..., ExternalTicketRef],
    update_external_tickets: Callable[..., dict[str, object]],
    append_external_close_note: Callable[..., None],
    result_factory: Callable[..., ReconcileResultT],
) -> ReconcileResultT:
    """Reconcile stale exported GitHub ticket metadata for a closed bead."""
    issues = run_bd_json(["show", issue_id], beads_root=beads_root, cwd=cwd)
    if not issues:
        return result_factory(
            issue_id=issue_id,
            stale_exported_github_tickets=0,
            reconciled_tickets=0,
            updated=False,
            needs_decision_notes=tuple(),
        )
    issue = issues[0]
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
    existing_tickets = parse_external_tickets(description if isinstance(description, str) else None)
    if not existing_tickets:
        return result_factory(
            issue_id=issue_id,
            stale_exported_github_tickets=0,
            reconciled_tickets=0,
            updated=False,
            needs_decision_notes=tuple(),
        )

    from ..github_issues_provider import GithubIssuesProvider

    stale = 0
    reconciled = 0
    updated = False
    notes: list[str] = []
    provider_cache: dict[str, GithubIssuesProvider] = {}
    merged_tickets: list[ExternalTicketRef] = []
    for ticket in existing_tickets:
        if ticket.provider != "github" or ticket.direction != "exported":
            merged_tickets.append(ticket)
            continue
        if ticket.state == "closed":
            merged_tickets.append(ticket)
            continue
        stale += 1
        action = close_action_for_ticket(ticket)
        if action == "none":
            merged_tickets.append(ticket)
            continue
        repo_slug = github_repo_from_ticket_url(ticket.url)
        if not repo_slug:
            notes.append(
                f"github:{ticket.ticket_id} missing repo slug; "
                "cannot reconcile exported ticket state"
            )
            merged_tickets.append(ticket)
            continue
        provider = provider_cache.get(repo_slug)
        if provider is None:
            provider = GithubIssuesProvider(repo=repo_slug)
            provider_cache[repo_slug] = provider
        close_comment = None
        if ticket.on_close == "comment":
            close_comment = f"Closing external ticket because local bead {issue_id} is closed."
        try:
            if action == "close":
                refreshed = provider.close_ticket(ticket, comment=close_comment)
                merged = merge_ticket_state(ticket, refreshed, assume_closed=True)
            else:
                refreshed = provider.sync_state(ticket)
                merged = merge_ticket_state(ticket, refreshed, assume_closed=False)
        except RuntimeError as exc:
            notes.append(f"github:{ticket.ticket_id} {exc}")
            merged_tickets.append(ticket)
            continue
        merged_tickets.append(merged)
        reconciled += 1
        if merged != ticket:
            updated = True

    if updated:
        update_external_tickets(issue_id, merged_tickets, beads_root=beads_root, cwd=cwd)

    unique_notes: list[str] = []
    seen_notes: set[str] = set()
    for note in notes:
        if note in seen_notes:
            continue
        seen_notes.add(note)
        unique_notes.append(note)
        append_external_close_note(issue_id, note, beads_root=beads_root, cwd=cwd)

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
    beads_root: Path,
    cwd: Path,
    run_bd_json: RunBdJson,
    parse_external_tickets: Callable[[str | None], list[ExternalTicketRef]],
    github_repo_from_ticket_url: Callable[[str | None], str | None],
    merge_ticket_state: Callable[..., ExternalTicketRef],
    update_external_tickets: Callable[..., dict[str, object]],
    append_external_reopen_note: Callable[..., None],
    result_factory: Callable[..., ReconcileResultT],
) -> ReconcileResultT:
    """Reopen stale exported GitHub tickets when a local bead reopens."""
    issues = run_bd_json(["show", issue_id], beads_root=beads_root, cwd=cwd)
    if not issues:
        return result_factory(
            issue_id=issue_id,
            stale_exported_github_tickets=0,
            reconciled_tickets=0,
            updated=False,
            needs_decision_notes=tuple(),
        )
    issue = issues[0]
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
    existing_tickets = parse_external_tickets(description if isinstance(description, str) else None)
    if not existing_tickets:
        return result_factory(
            issue_id=issue_id,
            stale_exported_github_tickets=0,
            reconciled_tickets=0,
            updated=False,
            needs_decision_notes=tuple(),
        )

    from ..github_issues_provider import GithubIssuesProvider

    stale = 0
    reconciled = 0
    updated = False
    notes: list[str] = []
    provider_cache: dict[str, GithubIssuesProvider] = {}
    merged_tickets: list[ExternalTicketRef] = []
    for ticket in existing_tickets:
        if ticket.provider != "github" or ticket.direction != "exported":
            merged_tickets.append(ticket)
            continue
        if ticket.state != "closed":
            merged_tickets.append(ticket)
            continue
        stale += 1
        repo_slug = github_repo_from_ticket_url(ticket.url)
        if not repo_slug:
            notes.append(
                f"github:{ticket.ticket_id} missing repo slug; cannot reopen exported ticket state"
            )
            merged_tickets.append(ticket)
            continue
        provider = provider_cache.get(repo_slug)
        if provider is None:
            provider = GithubIssuesProvider(repo=repo_slug)
            provider_cache[repo_slug] = provider
        try:
            refreshed = provider.reopen_ticket(
                ticket,
                comment=f"Reopening external ticket because local bead {issue_id} is active again.",
            )
            merged = merge_ticket_state(ticket, refreshed, assume_closed=False)
        except RuntimeError as exc:
            notes.append(f"github:{ticket.ticket_id} {exc}")
            merged_tickets.append(ticket)
            continue
        merged_tickets.append(merged)
        reconciled += 1
        if merged != ticket:
            updated = True

    if updated:
        update_external_tickets(issue_id, merged_tickets, beads_root=beads_root, cwd=cwd)

    unique_notes: list[str] = []
    seen_notes: set[str] = set()
    for note in notes:
        if note in seen_notes:
            continue
        seen_notes.add(note)
        unique_notes.append(note)
        append_external_reopen_note(issue_id, note, beads_root=beads_root, cwd=cwd)

    return result_factory(
        issue_id=issue_id,
        stale_exported_github_tickets=stale,
        reconciled_tickets=reconciled,
        updated=updated,
        needs_decision_notes=tuple(unique_notes),
    )

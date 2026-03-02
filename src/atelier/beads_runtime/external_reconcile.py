"""External ticket reconciliation helpers for the beads facade."""

from __future__ import annotations

import datetime as dt
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Literal, Protocol, TypeVar, overload
from urllib.parse import urlparse

from .. import github_issues_provider
from ..external_tickets import ExternalTicketRef, normalize_external_ticket_entry
from .issue_mutations import parse_description_fields

ReconcileResultT = TypeVar("ReconcileResultT")
EXTERNAL_TICKETS_KEY = "external_tickets"
_GITHUB_API_ISSUE_PATH = re.compile(r"^/repos/(?P<owner>[^/]+)/(?P<repo>[^/]+)/issues/[^/]+$")
_GITHUB_WEB_ISSUE_PATH = re.compile(r"^/(?P<owner>[^/]+)/(?P<repo>[^/]+)/issues/[^/]+$")
_NOT_FOUND_PATTERN = re.compile(r"(^|\D)404(\D|$)")


class GithubClient(Protocol):
    """External GitHub CLI boundary used by reconcile helpers."""

    @overload
    def gh(self, args: list[str], *, json_mode: Literal[False] = False) -> None: ...

    @overload
    def gh(self, args: list[str], *, json_mode: Literal[True]) -> object: ...

    def gh(self, args: list[str], *, json_mode: bool = False) -> object | None:
        """Run a GitHub CLI command via a concrete adapter."""
        ...


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


@dataclass(frozen=True)
class GithubIssuesClient:
    """GitHub issue operations built on top of the gh command boundary."""

    repo_slug: str
    github: GithubClient

    def close_ticket(
        self,
        ticket: ExternalTicketRef,
        *,
        comment: str | None = None,
    ) -> ExternalTicketRef:
        args = ["issue", "close", str(ticket.ticket_id), "--repo", self.repo_slug]
        if comment:
            args.extend(["--comment", comment])
        self.github.gh(args)
        return self.sync_state(ticket)

    def sync_state(self, ticket: ExternalTicketRef) -> ExternalTicketRef:
        payload = self.github.gh(
            ["api", f"repos/{self.repo_slug}/issues/{ticket.ticket_id}"],
            json_mode=True,
        )
        if not isinstance(payload, dict):
            raise RuntimeError("Unexpected gh issue view output")
        parent_id = _load_parent_ticket_id(
            self.github,
            repo_slug=self.repo_slug,
            ticket_id=ticket.ticket_id,
        )
        refreshed = github_issues_provider.issue_payload_to_ref(payload, parent_id=parent_id)
        if refreshed is None:
            raise RuntimeError("Failed to parse issue state")
        return refreshed

    def reopen_ticket(
        self,
        ticket: ExternalTicketRef,
        *,
        comment: str | None = None,
    ) -> ExternalTicketRef:
        args = ["issue", "reopen", str(ticket.ticket_id), "--repo", self.repo_slug]
        if comment:
            args.extend(["--comment", comment])
        self.github.gh(args)
        return self.sync_state(ticket)


class ExternalReconcileIssueStore(Protocol):
    """Issue metadata persistence boundary for reconcile flows."""

    def show_issue(self, issue_id: str) -> dict[str, object] | None:
        """Load issue payload by id."""
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


class ExternalReconcileGithubClient(Protocol):
    """GitHub provider boundary for reconcile flows."""

    def github_repo_from_ticket_url(self, url: str | None) -> str | None:
        """Resolve a GitHub repo slug from a ticket URL."""
        ...

    def github_issues(self, repo_slug: str) -> GithubTicketProvider:
        """Return a GitHub issues client for the given repository."""
        ...


def parse_external_tickets(description: str | None) -> list[ExternalTicketRef]:
    """Parse external ticket references from issue description text."""
    if not description:
        return []
    fields = parse_description_fields(description)
    tickets_raw = fields.get(EXTERNAL_TICKETS_KEY)
    if not tickets_raw or tickets_raw.lower() == "null":
        return []
    try:
        payload = json.loads(tickets_raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    tickets: list[ExternalTicketRef] = []
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        normalized = normalize_external_ticket_entry(entry)
        if normalized is not None:
            tickets.append(normalized)
    return tickets


def github_repo_from_ticket_url(url: str | None) -> str | None:
    """Resolve ``owner/repo`` from GitHub issue API or web URLs."""
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


def merge_ticket_state(
    ticket: ExternalTicketRef,
    refreshed: ExternalTicketRef,
    *,
    assume_closed: bool = False,
) -> ExternalTicketRef:
    """Merge provider ticket state into local metadata."""
    return replace(
        ticket,
        url=refreshed.url or ticket.url,
        parent_id=refreshed.parent_id or ticket.parent_id,
        state=refreshed.state or ("closed" if assume_closed else ticket.state),
        raw_state=refreshed.raw_state or ticket.raw_state,
        state_updated_at=refreshed.state_updated_at or ticket.state_updated_at,
        content_updated_at=refreshed.content_updated_at or ticket.content_updated_at,
        notes_updated_at=refreshed.notes_updated_at or ticket.notes_updated_at,
        last_synced_at=dt.datetime.now(tz=dt.timezone.utc).isoformat(),
    )


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
    issue_store: ExternalReconcileIssueStore,
    github: ExternalReconcileGithubClient,
    result_factory: Callable[..., ReconcileResultT],
) -> ReconcileResultT:
    """Reconcile stale exported GitHub ticket metadata for a closed bead."""
    issue = issue_store.show_issue(issue_id)
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
    existing_tickets = parse_external_tickets(description if isinstance(description, str) else None)
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
        repo_slug = github.github_repo_from_ticket_url(ticket.url)
        if not repo_slug:
            notes.append(
                f"github:{ticket.ticket_id} missing repo slug; "
                "cannot reconcile exported ticket state"
            )
            merged_tickets.append(ticket)
            continue
        provider = provider_cache.get(repo_slug)
        if provider is None:
            provider = github.github_issues(repo_slug)
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
        issue_store.update_external_tickets(issue_id, merged_tickets)

    unique_notes: list[str] = []
    seen_notes: set[str] = set()
    for note in notes:
        if note in seen_notes:
            continue
        seen_notes.add(note)
        unique_notes.append(note)
        issue_store.append_external_close_note(issue_id, note)

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
    issue_store: ExternalReconcileIssueStore,
    github: ExternalReconcileGithubClient,
    result_factory: Callable[..., ReconcileResultT],
) -> ReconcileResultT:
    """Reopen stale exported GitHub tickets when a local bead reopens."""
    issue = issue_store.show_issue(issue_id)
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
    existing_tickets = parse_external_tickets(description if isinstance(description, str) else None)
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
        repo_slug = github.github_repo_from_ticket_url(ticket.url)
        if not repo_slug:
            notes.append(
                f"github:{ticket.ticket_id} missing repo slug; cannot reopen exported ticket state"
            )
            merged_tickets.append(ticket)
            continue
        provider = provider_cache.get(repo_slug)
        if provider is None:
            provider = github.github_issues(repo_slug)
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
        issue_store.update_external_tickets(issue_id, merged_tickets)

    unique_notes: list[str] = []
    seen_notes: set[str] = set()
    for note in notes:
        if note in seen_notes:
            continue
        seen_notes.add(note)
        unique_notes.append(note)
        issue_store.append_external_reopen_note(issue_id, note)

    return result_factory(
        issue_id=issue_id,
        stale_exported_github_tickets=stale,
        reconciled_tickets=reconciled,
        updated=updated,
        needs_decision_notes=tuple(unique_notes),
    )


def _load_parent_ticket_id(
    github: GithubClient,
    *,
    repo_slug: str,
    ticket_id: str,
) -> str | None:
    try:
        payload = github.gh(
            ["api", f"repos/{repo_slug}/issues/{ticket_id}/parent"],
            json_mode=True,
        )
    except RuntimeError as exc:
        if _NOT_FOUND_PATTERN.search(str(exc).lower()):
            return None
        raise
    if not isinstance(payload, dict):
        return None
    parent = payload.get("id") or payload.get("number")
    if isinstance(parent, int):
        return str(parent)
    if isinstance(parent, str):
        cleaned = parent.strip()
        return cleaned or None
    return None

from __future__ import annotations

import json
from contextlib import nullcontext
from dataclasses import dataclass, field
from pathlib import Path
from subprocess import CompletedProcess

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
class _ReconcileClient:
    issue: dict[str, object] | None
    notes: list[str]
    beads_root: Path = Path("/beads")
    cwd: Path = Path("/repo")
    commands: list[list[str]] = field(default_factory=list)

    def issue_write_lock(self, issue_id: str):
        del issue_id
        return nullcontext()

    def show_issue(self, issue_id: str) -> dict[str, object] | None:
        del issue_id
        if self.issue is None:
            return None
        return dict(self.issue)

    def create_issue_with_body(self, args: list[str], description: str) -> str:
        del args, description
        raise RuntimeError("not used")

    def update_issue_description(self, issue_id: str, description: str) -> None:
        del issue_id
        if self.issue is not None:
            self.issue["description"] = description

    def bd(
        self,
        args: list[str],
        *,
        json_mode: bool = False,
        allow_failure: bool = False,
    ) -> CompletedProcess[str] | list[dict[str, object]]:
        del allow_failure
        if json_mode:
            if args[:1] == ["show"] and self.issue is not None:
                return [dict(self.issue)]
            return []
        self.commands.append(list(args))
        if self.issue is not None and args[:1] == ["update"]:
            if "--append-notes" in args:
                self.notes.append(str(args[-1]))
            labels_raw = self.issue.get("labels")
            labels = set()
            if isinstance(labels_raw, list):
                labels = {
                    label.strip().lower()
                    for label in labels_raw
                    if isinstance(label, str) and label.strip()
                }
            add_indices = [
                idx + 1
                for idx, value in enumerate(args)
                if value == "--add-label" and idx + 1 < len(args)
            ]
            remove_indices = [
                idx + 1
                for idx, value in enumerate(args)
                if value == "--remove-label" and idx + 1 < len(args)
            ]
            for index in add_indices:
                labels.add(str(args[index]).strip().lower())
            for index in remove_indices:
                labels.discard(str(args[index]).strip().lower())
            self.issue["labels"] = sorted(labels)
        return CompletedProcess(args=args, returncode=0, stdout="", stderr="")


@dataclass
class _GhBoundary:
    issue_payload: dict[str, object]
    parent_payload: object | Exception
    calls: list[tuple[list[str], bool]] = field(default_factory=list)

    def gh(self, args: list[str], *, json_mode: bool = False) -> object | None:
        self.calls.append((list(args), json_mode))
        if args[:2] in (["issue", "close"], ["issue", "reopen"]):
            return None
        if args == ["api", "repos/org/repo/issues/7"]:
            return self.issue_payload
        if args == ["api", "repos/org/repo/issues/7/parent"]:
            if isinstance(self.parent_payload, Exception):
                raise self.parent_payload
            return self.parent_payload
        return None


def _issue_with_tickets(*, status: str, tickets: list[dict[str, object]]) -> dict[str, object]:
    return {
        "id": "at-1",
        "status": status,
        "description": f"external_tickets: {json.dumps(tickets)}\n",
        "labels": ["ext:github", "ext:jira"],
    }


def test_reconcile_closed_issue_records_missing_repo_note() -> None:
    notes: list[str] = []
    client = _ReconcileClient(
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
        client=client,
        github=_GhBoundary(issue_payload={}, parent_payload={}),
        result_factory=_Result,
    )

    assert result.stale_exported_github_tickets == 1
    assert result.reconciled_tickets == 0
    assert result.updated is False
    assert notes
    assert "missing repo slug" in notes[0]


def test_reconcile_reopened_issue_records_missing_repo_note() -> None:
    notes: list[str] = []
    client = _ReconcileClient(
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
        client=client,
        github=_GhBoundary(issue_payload={}, parent_payload={}),
        result_factory=_Result,
    )

    assert result.stale_exported_github_tickets == 1
    assert result.reconciled_tickets == 0
    assert result.updated is False
    assert notes
    assert "cannot reopen exported ticket state" in notes[0]


def test_reconcile_closed_issue_updates_ticket_metadata_and_labels() -> None:
    notes: list[str] = []
    client = _ReconcileClient(
        issue=_issue_with_tickets(
            status="closed",
            tickets=[
                {
                    "provider": "github",
                    "id": "7",
                    "url": "https://github.com/org/repo/issues/7",
                    "direction": "exported",
                    "state": "open",
                    "relation": "primary",
                }
            ],
        ),
        notes=notes,
    )
    boundary = _GhBoundary(
        issue_payload={
            "number": 7,
            "url": "https://github.com/org/repo/issues/7",
            "state": "CLOSED",
            "stateReason": "completed",
            "updatedAt": "2026-03-02T00:00:00Z",
        },
        parent_payload={"number": 1},
    )

    result = external_reconcile.reconcile_closed_issue_exported_github_tickets(
        "at-1",
        client=client,
        github=boundary,
        result_factory=_Result,
    )

    assert result.stale_exported_github_tickets == 1
    assert result.reconciled_tickets == 1
    assert result.updated is True
    assert result.needs_decision_notes == tuple()
    assert client.issue is not None
    assert client.issue.get("labels") == ["ext:github"]
    refreshed = external_reconcile.parse_external_tickets(str(client.issue.get("description")))
    assert len(refreshed) == 1
    assert refreshed[0].state == "closed"
    assert refreshed[0].parent_id == "1"


def test_github_issues_client_sync_state_ignores_missing_parent_endpoint() -> None:
    boundary = _GhBoundary(
        issue_payload={
            "number": 7,
            "url": "https://github.com/org/repo/issues/7",
            "state": "OPEN",
            "stateReason": "reopened",
            "updatedAt": "2026-03-02T00:00:00Z",
        },
        parent_payload=RuntimeError("HTTP 404 Not Found"),
    )
    client = external_reconcile.GithubIssuesClient(repo_slug="org/repo", github=boundary)
    ticket = ExternalTicketRef(provider="github", ticket_id="7")

    refreshed = client.sync_state(ticket)

    assert refreshed.ticket_id == "7"
    assert refreshed.parent_id is None
    assert refreshed.state == "open"


def test_github_issues_client_close_ticket_routes_through_gh_boundary() -> None:
    boundary = _GhBoundary(
        issue_payload={
            "number": 7,
            "url": "https://github.com/org/repo/issues/7",
            "state": "CLOSED",
            "stateReason": "completed",
            "updatedAt": "2026-03-02T00:00:00Z",
        },
        parent_payload={"number": 1},
    )
    client = external_reconcile.GithubIssuesClient(repo_slug="org/repo", github=boundary)
    ticket = ExternalTicketRef(provider="github", ticket_id="7")

    refreshed = client.close_ticket(ticket, comment="closing from test")

    assert boundary.calls[0] == (
        [
            "issue",
            "close",
            "7",
            "--repo",
            "org/repo",
            "--comment",
            "closing from test",
        ],
        False,
    )
    assert refreshed.state == "closed"
    assert refreshed.parent_id == "1"

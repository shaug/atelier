from __future__ import annotations

from pathlib import Path

import pytest

from atelier.external_providers import (
    ExternalTicketImportRequest,
    ExternalTicketLinkRequest,
    ExternalTicketSyncOptions,
)
from atelier.external_tickets import ExternalTicketRef
from atelier.repo_beads_provider import RepoBeadsProvider


def test_repo_beads_provider_import_uses_readonly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / ".beads").mkdir()
    provider = RepoBeadsProvider(repo_root=tmp_path)
    payload = [
        {
            "id": "bd-1",
            "title": "Docs",
            "description": "Details",
            "acceptance_criteria": "AC1",
            "status": "open",
            "updated_at": "2026-02-08T10:00:00Z",
            "labels": ["p1"],
        }
    ]
    seen: dict[str, object] = {}

    def fake_run_bd_json(
        args: list[str], *, beads_root: Path, cwd: Path
    ) -> list[dict[str, object]]:
        seen["args"] = args
        seen["beads_root"] = beads_root
        seen["cwd"] = cwd
        return payload

    monkeypatch.setattr("atelier.repo_beads_provider.run_bd_json", fake_run_bd_json)

    records = provider.import_tickets(
        ExternalTicketImportRequest(
            include_closed=True,
            limit=5,
            query="Docs",
            sync_options=ExternalTicketSyncOptions(include_body=False),
        )
    )
    assert records
    assert records[0].ref.provider == "beads"
    assert records[0].ref.ticket_id == "bd-1"
    assert records[0].ref.state == "open"
    assert records[0].body is None

    args = seen["args"]
    assert isinstance(args, list)
    assert "--readonly" in args
    assert "list" in args
    assert "--all" in args
    assert "--limit" in args
    assert "--title-contains" in args


def test_repo_beads_provider_link_reads_issue(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / ".beads").mkdir()
    provider = RepoBeadsProvider(repo_root=tmp_path)
    payload = [
        {
            "id": "bd-2",
            "title": "Link",
            "description": "More details",
            "acceptance_criteria": "AC2",
            "status": "in_progress",
            "updated_at": "2026-02-08T11:00:00Z",
            "labels": ["p2"],
        }
    ]
    seen: dict[str, object] = {}

    def fake_run_bd_json(
        args: list[str], *, beads_root: Path, cwd: Path
    ) -> list[dict[str, object]]:
        seen["args"] = args
        return payload

    monkeypatch.setattr("atelier.repo_beads_provider.run_bd_json", fake_run_bd_json)

    record = provider.link_ticket(
        ExternalTicketLinkRequest(
            bead_id="at-1",
            ticket=ExternalTicketRef(provider="beads", ticket_id="bd-2"),
        )
    )
    assert record.ref.ticket_id == "bd-2"
    assert record.body == "More details\n\nAcceptance criteria:\nAC2"
    assert record.ref.state == "in_progress"

    args = seen["args"]
    assert isinstance(args, list)
    assert "--readonly" in args
    assert "show" in args

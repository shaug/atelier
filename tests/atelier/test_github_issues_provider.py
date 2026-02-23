from __future__ import annotations

import json
from pathlib import Path

import pytest

from atelier.external_providers import (
    ExternalTicketCreateRequest,
    ExternalTicketImportRequest,
    ExternalTicketSyncOptions,
)
from atelier.external_tickets import ExternalTicketRef
from atelier.github_issues_provider import (
    GithubIssuesProvider,
    issue_payload_to_record,
    issue_payload_to_ref,
)


def test_issue_payload_to_ref_handles_basic_fields() -> None:
    payload = {
        "number": 42,
        "url": "https://github.com/org/repo/issues/42",
        "state": "OPEN",
        "stateReason": "planned",
        "updatedAt": "2026-02-08T10:00:00Z",
    }
    ref = issue_payload_to_ref(payload)
    assert ref is not None
    assert ref.provider == "github"
    assert ref.ticket_id == "42"
    assert ref.url == "https://github.com/org/repo/issues/42"
    assert ref.state == "open"
    assert ref.raw_state == "planned"
    assert ref.state_updated_at == "2026-02-08T10:00:00Z"


def test_issue_payload_to_ref_respects_state_toggle() -> None:
    payload = {
        "number": 101,
        "url": "https://github.com/org/repo/issues/101",
        "state": "OPEN",
        "stateReason": "planned",
        "updatedAt": "2026-02-08T10:00:00Z",
    }
    ref = issue_payload_to_ref(payload, sync_options=ExternalTicketSyncOptions(include_state=False))
    assert ref is not None
    assert ref.state is None
    assert ref.raw_state is None
    assert ref.state_updated_at is None


def test_issue_payload_to_record_includes_labels() -> None:
    payload = {
        "number": 7,
        "title": "Fix bug",
        "body": "Details",
        "labels": [{"name": "bug"}, {"name": "triage"}],
        "state": "CLOSED",
    }
    record = issue_payload_to_record(payload)
    assert record is not None
    assert record.ref.ticket_id == "7"
    assert record.title == "Fix bug"
    assert record.body == "Details"
    assert record.labels == ("bug", "triage")
    assert record.ref.state == "closed"


def test_issue_payload_to_record_respects_body_toggle() -> None:
    payload = {
        "number": 8,
        "title": "Missing docs",
        "body": "Extra details",
        "stateReason": "not planned",
        "labels": [],
        "state": "OPEN",
    }
    record = issue_payload_to_record(
        payload,
        sync_options=ExternalTicketSyncOptions(include_body=False, include_notes=False),
    )
    assert record is not None
    assert record.body is None
    assert record.summary is None


def test_import_tickets_parses_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = GithubIssuesProvider(repo="org/repo")
    payload = [
        {"number": 1, "title": "One", "state": "OPEN", "labels": []},
        {"number": 2, "title": "Two", "state": "CLOSED", "labels": []},
    ]

    def fake_run_json(cmd: list[str]) -> object:
        return payload

    monkeypatch.setattr("atelier.github_issues_provider._run_json", fake_run_json)
    monkeypatch.setattr("atelier.github_issues_provider._require_gh", lambda: None)

    records = provider.import_tickets(request=ExternalTicketImportRequest(include_closed=True))
    assert len(records) == 2
    assert records[0].ref.ticket_id == "1"


def test_create_ticket_uses_input_file_for_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = GithubIssuesProvider(repo="org/repo")
    captured_payload: dict[str, object] = {}

    def fake_run_json(cmd: list[str]) -> object:
        input_index = cmd.index("--input")
        payload_path = Path(cmd[input_index + 1])
        captured_payload.update(json.loads(payload_path.read_text(encoding="utf-8")))
        return {
            "number": 21,
            "title": "Danger `title` $(whoami)",
            "body": "Body with `ticks` and $(printf no-op)",
            "state": "OPEN",
            "labels": [],
        }

    monkeypatch.setattr("atelier.github_issues_provider._run_json", fake_run_json)
    monkeypatch.setattr("atelier.github_issues_provider._require_gh", lambda: None)

    record = provider.create_ticket(
        ExternalTicketCreateRequest(
            bead_id="at-1",
            title="Danger `title` $(whoami)",
            body="Body with `ticks` and $(printf no-op)",
            labels=("triage",),
        )
    )

    assert captured_payload["title"] == "Danger `title` $(whoami)"
    assert captured_payload["body"] == "Body with `ticks` and $(printf no-op)"
    assert captured_payload["labels"] == ["triage"]
    assert record.ref.ticket_id == "21"


def test_update_ticket_uses_body_file(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = GithubIssuesProvider(repo="org/repo")
    captured_commands: list[list[str]] = []
    captured_body: dict[str, str] = {}
    title_text = "Title with `ticks` and $(echo safe)"

    def fake_run(cmd: list[str]) -> str:
        captured_commands.append(cmd)
        if "--body-file" in cmd:
            body_path = Path(cmd[cmd.index("--body-file") + 1])
            captured_body["text"] = body_path.read_text(encoding="utf-8")
        return ""

    monkeypatch.setattr("atelier.github_issues_provider._run", fake_run)
    monkeypatch.setattr("atelier.github_issues_provider._require_gh", lambda: None)
    monkeypatch.setattr(GithubIssuesProvider, "sync_state", lambda self, ref: ref)

    ref = ExternalTicketRef(provider="github", ticket_id="44")
    updated = provider.update_ticket(
        ref,
        title=title_text,
        body="Body with markdown `code`\n$(echo safe)",
    )

    assert updated == ref
    assert captured_body["text"] == "Body with markdown `code`\n$(echo safe)"
    assert any("--body-file" in command for command in captured_commands)
    edit_command = next(command for command in captured_commands if "--body-file" in command)
    title_index = edit_command.index("--title")
    assert edit_command[title_index + 1] == title_text
    assert not any(token == "--body" for command in captured_commands for token in command)

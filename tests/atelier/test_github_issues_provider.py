from __future__ import annotations

import pytest

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

    records = provider.import_tickets(
        request=type(
            "Req", (), {"include_closed": True, "limit": None, "query": None}
        )()
    )
    assert len(records) == 2
    assert records[0].ref.ticket_id == "1"

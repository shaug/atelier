from __future__ import annotations

from pathlib import Path

import pytest

from atelier.external_providers import (
    ExternalTicketCreateRequest,
    ExternalTicketImportRequest,
    ExternalTicketLinkRequest,
    ExternalTicketSyncOptions,
)
from atelier.external_tickets import ExternalTicketRef
from atelier.lib.beads import (
    CloseIssueRequest,
    CreateIssueRequest,
    IssueRecord,
    ListIssuesRequest,
    ShowIssueRequest,
    UpdateIssueRequest,
)
from atelier.repo_beads_provider import RepoBeadsProvider


class _FakeBeadsClient:
    def __init__(
        self,
        *,
        list_result: tuple[IssueRecord, ...] = (),
        show_result: IssueRecord | None = None,
    ) -> None:
        self.list_result = list_result
        self.show_result = show_result
        self.list_requests: list[ListIssuesRequest] = []
        self.show_requests: list[ShowIssueRequest] = []
        self.create_requests: list[CreateIssueRequest] = []
        self.update_requests: list[UpdateIssueRequest] = []
        self.close_requests: list[CloseIssueRequest] = []

    def list(self, request: ListIssuesRequest) -> tuple[IssueRecord, ...]:
        self.list_requests.append(request)
        return self.list_result

    def show(self, request: ShowIssueRequest) -> IssueRecord:
        self.show_requests.append(request)
        if self.show_result is None:
            raise AssertionError("show_result was not configured")
        return self.show_result

    def create(self, request: CreateIssueRequest) -> IssueRecord:
        self.create_requests.append(request)
        return IssueRecord.model_validate(
            {
                "id": "bd-9",
                "title": request.title,
                "description": request.description,
                "status": "open",
                "labels": list(request.labels),
                "updated_at": "2026-02-08T12:00:00Z",
            }
        )

    def update(self, request: UpdateIssueRequest) -> IssueRecord:
        self.update_requests.append(request)
        return IssueRecord.model_validate(
            {
                "id": request.issue_id,
                "status": request.status or "open",
                "updated_at": "2026-02-24T22:00:00Z",
            }
        )

    def close(self, request: CloseIssueRequest) -> IssueRecord:
        self.close_requests.append(request)
        return IssueRecord.model_validate(
            {
                "id": request.issue_id,
                "status": "closed",
                "updated_at": "2026-02-24T22:00:00Z",
            }
        )


def test_repo_beads_provider_import_uses_readonly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / ".beads").mkdir()
    provider = RepoBeadsProvider(repo_root=tmp_path)
    client = _FakeBeadsClient(
        list_result=(
            IssueRecord.model_validate(
                {
                    "id": "bd-1",
                    "title": "Docs",
                    "description": "Details",
                    "acceptance_criteria": "AC1",
                    "status": "open",
                    "updated_at": "2026-02-08T10:00:00Z",
                    "labels": ["p1"],
                }
            ),
        )
    )
    seen: dict[str, object] = {}

    def fake_build_beads_client(
        *, repo_root: Path, beads_root: Path, readonly: bool = False
    ) -> _FakeBeadsClient:
        seen["repo_root"] = repo_root
        seen["beads_root"] = beads_root
        seen["readonly"] = readonly
        return client

    monkeypatch.setattr("atelier.repo_beads_provider._build_beads_client", fake_build_beads_client)

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

    assert seen == {
        "repo_root": tmp_path,
        "beads_root": tmp_path / ".beads",
        "readonly": True,
    }
    assert client.list_requests == [
        ListIssuesRequest(include_closed=True, limit=5, title_query="Docs")
    ]


def test_repo_beads_provider_link_reads_issue(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / ".beads").mkdir()
    provider = RepoBeadsProvider(repo_root=tmp_path)
    client = _FakeBeadsClient(
        show_result=IssueRecord.model_validate(
            {
                "id": "bd-2",
                "title": "Link",
                "description": "More details",
                "acceptance_criteria": "AC2",
                "status": "in_progress",
                "updated_at": "2026-02-08T11:00:00Z",
                "labels": ["p2"],
            }
        )
    )
    monkeypatch.setattr(
        "atelier.repo_beads_provider._build_beads_client",
        lambda **_kwargs: client,
    )

    record = provider.link_ticket(
        ExternalTicketLinkRequest(
            bead_id="at-1",
            ticket=ExternalTicketRef(provider="beads", ticket_id="bd-2"),
        )
    )
    assert record.ref.ticket_id == "bd-2"
    assert record.body == "More details\n\nAcceptance criteria:\nAC2"
    assert record.ref.state == "in_progress"
    assert client.show_requests == [ShowIssueRequest(issue_id="bd-2")]


def test_repo_beads_provider_create_requires_allow_write(
    tmp_path: Path,
) -> None:
    (tmp_path / ".beads").mkdir()
    provider = RepoBeadsProvider(repo_root=tmp_path)
    request = ExternalTicketCreateRequest(bead_id="at-1", title="Export", body="Body")
    with pytest.raises(RuntimeError, match="allow_write"):
        provider.create_ticket(request)


def test_repo_beads_provider_create_ticket_when_allowed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / ".beads").mkdir()
    provider = RepoBeadsProvider(repo_root=tmp_path, allow_write=True)
    client = _FakeBeadsClient()
    seen: dict[str, object] = {}

    def fake_build_beads_client(**kwargs: object) -> _FakeBeadsClient:
        seen["kwargs"] = kwargs
        return client

    monkeypatch.setattr("atelier.repo_beads_provider._build_beads_client", fake_build_beads_client)

    record = provider.create_ticket(
        ExternalTicketCreateRequest(
            bead_id="at-1",
            title="Exported",
            body="Body",
            labels=("epic",),
        )
    )
    assert record.ref.ticket_id == "bd-9"
    assert record.title == "Exported"
    assert client.create_requests == [
        CreateIssueRequest(
            title="Exported",
            type="epic",
            description="Body",
            labels=("epic",),
        )
    ]
    assert seen["kwargs"] == {
        "repo_root": tmp_path,
        "beads_root": tmp_path / ".beads",
        "readonly": False,
    }


def test_repo_beads_provider_update_preserves_external_ticket_metadata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / ".beads").mkdir()
    provider = RepoBeadsProvider(
        repo_root=tmp_path,
        allow_write=True,
        sync_options=ExternalTicketSyncOptions(
            include_state=False,
            include_body=False,
            include_notes=False,
        ),
    )
    read_client = _FakeBeadsClient(
        show_result=IssueRecord.model_validate(
            {
                "id": "bd-9",
                "description": (
                    "scope: old\n"
                    "external_tickets: "
                    '[{"provider":"github","id":"174","direction":"export"}]\n'
                ),
                "status": "open",
                "updated_at": "2026-02-24T22:00:00Z",
            }
        )
    )
    write_client = _FakeBeadsClient()

    def fake_build_beads_client(*, readonly: bool = False, **_kwargs: object) -> _FakeBeadsClient:
        return read_client if readonly else write_client

    monkeypatch.setattr("atelier.repo_beads_provider._build_beads_client", fake_build_beads_client)

    provider.update_ticket(
        ExternalTicketRef(provider="beads", ticket_id="bd-9"),
        body="Intent\nupdated description\n",
    )

    assert read_client.show_requests == [ShowIssueRequest(issue_id="bd-9")]
    assert len(write_client.update_requests) == 1
    description = write_client.update_requests[0].description
    assert "Intent" in description
    assert "external_tickets:" in description
    assert '"id":"174"' in description


def test_repo_beads_provider_close_uses_typed_client(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / ".beads").mkdir()
    provider = RepoBeadsProvider(repo_root=tmp_path, allow_write=True)
    write_client = _FakeBeadsClient()
    monkeypatch.setattr(
        "atelier.repo_beads_provider._build_beads_client",
        lambda **_kwargs: write_client,
    )
    monkeypatch.setattr(
        RepoBeadsProvider,
        "sync_state",
        lambda self, ref: ExternalTicketRef(provider=ref.provider, ticket_id=ref.ticket_id),
    )

    ref = ExternalTicketRef(provider="beads", ticket_id="bd-7")
    closed = provider.close_ticket(ref)

    assert closed.ticket_id == "bd-7"
    assert write_client.close_requests == [CloseIssueRequest(issue_id="bd-7")]

from __future__ import annotations

import json
from pathlib import Path

import atelier.auto_export as auto_export
from atelier.external_providers import (
    ExternalProviderCapabilities,
    ExternalTicketCreateRequest,
    ExternalTicketRecord,
)
from atelier.external_tickets import ExternalTicketRef
from atelier.models import ProjectConfig, ProjectSection


class FakeProvider:
    def __init__(self, *, supports_children: bool = False) -> None:
        self.slug = "github"
        self.display_name = "GitHub Issues"
        self.capabilities = ExternalProviderCapabilities(
            supports_import=True,
            supports_create=True,
            supports_link=True,
            supports_set_in_progress=True,
            supports_update=True,
            supports_children=supports_children,
            supports_state_sync=True,
        )
        self.created: list[ExternalTicketCreateRequest] = []
        self.created_children: list[tuple[ExternalTicketRef, str, str | None, tuple[str, ...]]] = []
        self.fail_create = False

    def import_tickets(self, request):  # pragma: no cover - not used here
        return []

    def create_ticket(self, request: ExternalTicketCreateRequest) -> ExternalTicketRecord:
        if self.fail_create:
            raise RuntimeError("boom")
        self.created.append(request)
        return ExternalTicketRecord(
            ref=ExternalTicketRef(
                provider=self.slug,
                ticket_id=str(100 + len(self.created)),
                url=f"https://example.test/{100 + len(self.created)}",
            )
        )

    def link_ticket(self, request):  # pragma: no cover - not used here
        raise NotImplementedError

    def set_in_progress(self, ref):  # pragma: no cover - not used here
        raise NotImplementedError

    def update_ticket(self, ref, *, title=None, body=None):  # pragma: no cover - not used here
        raise NotImplementedError

    def create_child_ticket(self, ref, *, title, body=None, labels=()):
        if not self.capabilities.supports_children:
            raise NotImplementedError
        self.created_children.append((ref, title, body, labels))
        return ExternalTicketRef(
            provider=self.slug,
            ticket_id=str(700 + len(self.created_children)),
            url=f"https://example.test/{700 + len(self.created_children)}",
            parent_id=ref.ticket_id,
        )

    def sync_state(self, ref):  # pragma: no cover - not used here
        return ref


def _context(*, auto_enabled: bool) -> auto_export.AutoExportContext:
    config_payload = ProjectConfig(
        project=ProjectSection(
            provider="github",
            auto_export_new=auto_enabled,
            origin="github.com/acme/widgets",
        )
    )
    return auto_export.AutoExportContext(
        project_config=config_payload,
        project_dir=Path("/project-data"),
        repo_root=Path("/repo"),
        beads_root=Path("/project-data/.beads"),
    )


def test_auto_export_skips_when_disabled(monkeypatch) -> None:
    provider = FakeProvider()
    context = _context(auto_enabled=False)
    issue = {"id": "at-1", "title": "Epic", "labels": ["at:epic"], "description": ""}

    monkeypatch.setattr(auto_export, "_resolve_provider", lambda *_args, **_kwargs: provider)
    monkeypatch.setattr(auto_export, "_load_issue", lambda *_args, **_kwargs: issue)

    result = auto_export.auto_export_issue("at-1", context=context)

    assert result.status == "skipped"
    assert "disabled" in result.message
    assert provider.created == []


def test_auto_export_exports_when_enabled(monkeypatch) -> None:
    provider = FakeProvider()
    context = _context(auto_enabled=True)
    issue = {"id": "at-1", "title": "Epic", "labels": ["at:epic"], "description": ""}
    captured: dict[str, object] = {}

    monkeypatch.setattr(auto_export, "_resolve_provider", lambda *_args, **_kwargs: provider)
    monkeypatch.setattr(auto_export, "_load_issue", lambda *_args, **_kwargs: issue)

    def fake_update(issue_id: str, tickets: list[ExternalTicketRef], **_kwargs: object) -> None:
        captured["issue_id"] = issue_id
        captured["tickets"] = tickets

    monkeypatch.setattr(auto_export.beads, "update_external_tickets", fake_update)
    monkeypatch.setattr(auto_export.beads, "list_work_children", lambda *_, **__: [])

    result = auto_export.auto_export_issue("at-1", context=context)

    assert result.status == "exported"
    assert provider.created
    assert captured["issue_id"] == "at-1"
    tickets = captured["tickets"]
    assert isinstance(tickets, list)
    assert tickets
    ticket = tickets[0]
    assert isinstance(ticket, ExternalTicketRef)
    assert ticket.direction == "exported"
    assert ticket.sync_mode == "export"
    assert ticket.relation == "primary"


def test_auto_export_honors_opt_out_label(monkeypatch) -> None:
    provider = FakeProvider()
    context = _context(auto_enabled=True)
    issue = {
        "id": "at-1",
        "title": "Epic",
        "labels": ["at:epic", "ext:no-export"],
        "description": "",
    }

    monkeypatch.setattr(auto_export, "_resolve_provider", lambda *_args, **_kwargs: provider)
    monkeypatch.setattr(auto_export, "_load_issue", lambda *_args, **_kwargs: issue)

    result = auto_export.auto_export_issue("at-1", context=context)

    assert result.status == "skipped"
    assert "opted out" in result.message
    assert provider.created == []


def test_auto_export_adds_parent_cross_link_when_children_not_supported(monkeypatch) -> None:
    provider = FakeProvider(supports_children=False)
    context = _context(auto_enabled=True)
    parent_tickets = json.dumps(
        [
            {
                "provider": "github",
                "id": "99",
                "url": "https://example.test/99",
                "direction": "exported",
                "sync_mode": "export",
            }
        ]
    )
    issues = {
        "at-child": {
            "id": "at-child",
            "parent": "at-parent",
            "title": "Child changeset",
            "labels": [],
            "type": "task",
            "description": "scope: child\n",
        },
        "at-parent": {
            "id": "at-parent",
            "title": "Parent epic",
            "labels": ["at:epic"],
            "description": f"external_tickets: {parent_tickets}\n",
        },
    }
    captured: dict[str, object] = {}

    monkeypatch.setattr(auto_export, "_resolve_provider", lambda *_args, **_kwargs: provider)
    monkeypatch.setattr(
        auto_export, "_load_issue", lambda issue_id, **_kwargs: issues.get(issue_id)
    )
    monkeypatch.setattr(auto_export.beads, "list_work_children", lambda *_, **__: [])

    def fake_update(issue_id: str, tickets: list[ExternalTicketRef], **_kwargs: object) -> None:
        captured["issue_id"] = issue_id
        captured["tickets"] = tickets

    monkeypatch.setattr(auto_export.beads, "update_external_tickets", fake_update)

    result = auto_export.auto_export_issue("at-child", context=context)

    assert result.status == "exported"
    assert provider.created
    body = provider.created[0].body
    assert isinstance(body, str)
    assert "Parent external ticket: github:99" in body
    tickets = captured["tickets"]
    assert isinstance(tickets, list)
    ticket = tickets[0]
    assert isinstance(ticket, ExternalTicketRef)
    assert ticket.parent_id == "99"
    assert ticket.relation == "derived"


def test_auto_export_creates_provider_child_ticket_when_supported(monkeypatch) -> None:
    provider = FakeProvider(supports_children=True)
    context = _context(auto_enabled=True)
    parent_tickets = json.dumps(
        [
            {
                "provider": "github",
                "id": "99",
                "url": "https://example.test/99",
                "direction": "exported",
                "sync_mode": "export",
            }
        ]
    )
    issues = {
        "at-child": {
            "id": "at-child",
            "parent": "at-parent",
            "title": "Child changeset",
            "labels": [],
            "type": "task",
            "description": "scope: child\n",
        },
        "at-parent": {
            "id": "at-parent",
            "title": "Parent epic",
            "labels": ["at:epic"],
            "description": f"external_tickets: {parent_tickets}\n",
        },
    }

    monkeypatch.setattr(auto_export, "_resolve_provider", lambda *_args, **_kwargs: provider)
    monkeypatch.setattr(
        auto_export, "_load_issue", lambda issue_id, **_kwargs: issues.get(issue_id)
    )
    monkeypatch.setattr(
        auto_export.beads, "update_external_tickets", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(auto_export.beads, "list_work_children", lambda *_, **__: [])

    result = auto_export.auto_export_issue("at-child", context=context)

    assert result.status == "exported"
    assert not provider.created
    assert provider.created_children
    parent_ref, title, body, labels = provider.created_children[0]
    assert parent_ref.ticket_id == "99"
    assert title == "Child changeset"
    assert isinstance(body, str)
    assert labels == ("atelier", "changeset")


def test_auto_export_failure_is_non_fatal_and_returns_retry(monkeypatch) -> None:
    provider = FakeProvider()
    provider.fail_create = True
    context = _context(auto_enabled=True)
    issue = {"id": "at-1", "title": "Epic", "labels": ["at:epic"], "description": ""}

    monkeypatch.setattr(auto_export, "_resolve_provider", lambda *_args, **_kwargs: provider)
    monkeypatch.setattr(auto_export, "_load_issue", lambda *_args, **_kwargs: issue)
    monkeypatch.setattr(auto_export.beads, "list_work_children", lambda *_, **__: [])

    result = auto_export.auto_export_issue("at-1", context=context)

    assert result.status == "failed"
    assert "boom" in result.message
    assert result.retry_command is not None


def test_auto_export_ignores_legacy_provider_env_override(
    monkeypatch,
) -> None:
    provider = FakeProvider()
    context = _context(auto_enabled=True)
    monkeypatch.setenv("ATELIER_EXTERNAL_PROVIDER", "beads")
    monkeypatch.setattr(
        auto_export.external_registry,
        "resolve_external_providers",
        lambda *_args, **_kwargs: [
            auto_export.external_registry.ExternalProviderContext(provider=provider)
        ],
    )

    assert auto_export._resolve_provider(context, provider_slug=None) is provider

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_script():
    scripts_dir = (
        Path(__file__).resolve().parents[3] / "src/atelier/skills/planner-startup-check/scripts"
    )
    path = scripts_dir / "refresh_overview.py"
    spec = importlib.util.spec_from_file_location("test_planner_startup_refresh_script", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_render_startup_overview_reports_empty_sections(monkeypatch) -> None:
    module = _load_script()
    monkeypatch.setattr(module.beads, "list_inbox_messages", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(module.beads, "list_queue_messages", lambda **_kwargs: [])
    monkeypatch.setattr(module.beads, "list_descendant_changesets", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(module.planner_overview, "list_epics", lambda **_kwargs: [])
    monkeypatch.setattr(
        module.planner_overview,
        "render_epics",
        lambda issues, *, show_drafts: "Epics by state:\n- (none)",
    )

    rendered = module._render_startup_overview(
        "atelier/planner/example",
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
    )

    assert rendered.splitlines() == [
        "Planner startup overview",
        "No unread messages.",
        "No queued messages.",
        "No deferred changesets under open/in-progress/blocked epics.",
        "Epics by state:",
        "- (none)",
    ]


def test_render_startup_overview_lists_claim_state_and_sorts_messages(monkeypatch) -> None:
    module = _load_script()
    inbox = [
        {"id": "at-msg-2", "title": "Beta"},
        {"id": "at-msg-1", "title": "Alpha"},
    ]
    queued = [
        {
            "id": "at-q-2",
            "queue": "planner",
            "title": "Second",
            "claimed_by": "atelier/worker/agent",
        },
        {
            "id": "at-q-1",
            "queue": "planner",
            "title": "First",
            "claimed_by": "",
        },
    ]
    calls: dict[str, object] = {}

    def _fake_list_inbox_messages(*_args, **_kwargs):
        return inbox

    def _fake_list_queue_messages(**kwargs):
        calls["queue_kwargs"] = kwargs
        return queued

    def _fake_list_descendant_changesets(parent_id: str, **kwargs):
        calls.setdefault("descendant_calls", []).append((parent_id, kwargs))
        if parent_id == "at-1":
            return [
                {"id": "at-1.2", "title": "Second deferred", "status": "deferred"},
                {"id": "at-1.1", "title": "First deferred", "status": "deferred"},
                {"id": "at-1.3", "title": "Ready now", "status": "open"},
            ]
        if parent_id == "at-2":
            return [
                {"id": "at-2.1", "title": "Blocked epic child", "status": "deferred"},
            ]
        return []

    monkeypatch.setattr(module.beads, "list_inbox_messages", _fake_list_inbox_messages)
    monkeypatch.setattr(module.beads, "list_queue_messages", _fake_list_queue_messages)
    monkeypatch.setattr(
        module.beads, "list_descendant_changesets", _fake_list_descendant_changesets
    )
    monkeypatch.setattr(
        module.planner_overview,
        "list_epics",
        lambda **_kwargs: [
            {"id": "at-1", "title": "Epic one", "status": "open"},
            {"id": "at-2", "title": "Epic blocked", "status": "blocked"},
            {"id": "at-3", "title": "Epic closed", "status": "closed"},
        ],
    )
    monkeypatch.setattr(
        module.planner_overview,
        "render_epics",
        lambda issues, *, show_drafts: "Epics by state:\nOpen epics:\n- at-1 [open] Example",
    )

    rendered = module._render_startup_overview(
        "atelier/planner/example",
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
    )

    assert rendered.splitlines() == [
        "Planner startup overview",
        "Unread messages:",
        "- at-msg-1 Alpha",
        "- at-msg-2 Beta",
        "Queued messages:",
        "- at-q-1 [planner] First | claim: unclaimed",
        "- at-q-2 [planner] Second | claim: claimed by atelier/worker/agent",
        "Deferred changesets under open/in-progress/blocked epics:",
        "- at-1 [open] Epic one",
        "  - at-1.1 [deferred] First deferred",
        "  - at-1.2 [deferred] Second deferred",
        "- at-2 [blocked] Epic blocked",
        "  - at-2.1 [deferred] Blocked epic child",
        "Epics by state:",
        "Open epics:",
        "- at-1 [open] Example",
    ]
    assert calls["queue_kwargs"] == {
        "beads_root": Path("/beads"),
        "cwd": Path("/repo"),
        "unread_only": True,
        "unclaimed_only": False,
    }
    assert calls["descendant_calls"] == [
        (
            "at-1",
            {
                "beads_root": Path("/beads"),
                "cwd": Path("/repo"),
                "include_closed": False,
            },
        ),
        (
            "at-2",
            {
                "beads_root": Path("/beads"),
                "cwd": Path("/repo"),
                "include_closed": False,
            },
        ),
    ]


def test_render_startup_overview_caps_deferred_epic_scan(monkeypatch) -> None:
    module = _load_script()
    monkeypatch.setenv("ATELIER_STARTUP_DEFERRED_EPIC_SCAN_LIMIT", "1")
    monkeypatch.setattr(module.beads, "list_inbox_messages", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(module.beads, "list_queue_messages", lambda **_kwargs: [])
    scanned_epics: list[str] = []

    def _fake_list_descendant_changesets(parent_id: str, **_kwargs):
        scanned_epics.append(parent_id)
        return [{"id": f"{parent_id}.1", "title": "Deferred child", "status": "deferred"}]

    monkeypatch.setattr(
        module.beads, "list_descendant_changesets", _fake_list_descendant_changesets
    )
    monkeypatch.setattr(
        module.planner_overview,
        "list_epics",
        lambda **_kwargs: [
            {"id": "at-1", "title": "Epic one", "status": "open"},
            {"id": "at-2", "title": "Epic two", "status": "in_progress"},
            {"id": "at-3", "title": "Epic three", "status": "blocked"},
        ],
    )
    monkeypatch.setattr(
        module.planner_overview,
        "render_epics",
        lambda issues, *, show_drafts: "Epics by state:\n- at-1 [open] Example",
    )

    rendered = module._render_startup_overview(
        "atelier/planner/example",
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
    )

    assert scanned_epics == ["at-1"]
    assert rendered.splitlines() == [
        "Planner startup overview",
        "No unread messages.",
        "No queued messages.",
        "Deferred changesets under open/in-progress/blocked epics:",
        "- at-1 [open] Epic one",
        "  - at-1.1 [deferred] Deferred child",
        "Deferred changeset scan limited to first 1 active epics; skipped 2.",
        "Epics by state:",
        "- at-1 [open] Example",
    ]

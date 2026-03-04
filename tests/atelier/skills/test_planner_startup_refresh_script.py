from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


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


def _parity_ok() -> SimpleNamespace:
    return SimpleNamespace(
        active_top_level_work_count=0,
        indexed_active_epic_count=0,
        missing_executable_identity=(),
        missing_from_index=(),
        in_parity=True,
    )


def _startup_result(
    module,
    *,
    inbox: list[dict[str, object]],
    queued: list[dict[str, object]],
    epics: list[dict[str, object]],
    parity: object,
):
    return module.StartupCommandResult(
        inbox_messages=inbox,
        queued_messages=queued,
        epics=epics,
        parity_report=parity,
    )


def test_render_startup_overview_reports_empty_sections(monkeypatch) -> None:
    module = _load_script()
    monkeypatch.setattr(
        module,
        "execute_startup_command_plan",
        lambda *_args, **_kwargs: _startup_result(
            module,
            inbox=[],
            queued=[],
            epics=[],
            parity=_parity_ok(),
        ),
    )
    monkeypatch.setattr(
        module.StartupBeadsInvocationHelper,
        "list_descendant_changesets",
        lambda *_args, **_kwargs: [],
    )
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
        "- Beads root: /beads",
        "No unread messages.",
        "No queued messages.",
        "- Total epics: 0",
        "- Active top-level work (open/in_progress/blocked): 0",
        "- Indexed active epics (at:epic discovery): 0",
        "Epic discovery parity: ok",
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

    def _fake_list_descendant_changesets(_self, parent_id: str, *, include_closed: bool):
        calls.setdefault("descendant_calls", []).append((parent_id, include_closed))
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

    monkeypatch.setattr(
        module.StartupBeadsInvocationHelper,
        "list_descendant_changesets",
        _fake_list_descendant_changesets,
    )
    monkeypatch.setattr(
        module,
        "execute_startup_command_plan",
        lambda *_args, **_kwargs: _startup_result(
            module,
            inbox=inbox,
            queued=queued,
            epics=[
                {"id": "at-1", "title": "Epic one", "status": "open"},
                {"id": "at-2", "title": "Epic blocked", "status": "blocked"},
                {"id": "at-3", "title": "Epic closed", "status": "closed"},
            ],
            parity=SimpleNamespace(
                active_top_level_work_count=2,
                indexed_active_epic_count=2,
                missing_executable_identity=(),
                missing_from_index=(),
                in_parity=True,
            ),
        ),
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
        "- Beads root: /beads",
        "Unread messages:",
        "- at-msg-1 Alpha",
        "- at-msg-2 Beta",
        "Queued messages:",
        "- at-q-1 [planner] First | claim: unclaimed",
        "- at-q-2 [planner] Second | claim: claimed by atelier/worker/agent",
        "- Total epics: 3",
        "- Active top-level work (open/in_progress/blocked): 2",
        "- Indexed active epics (at:epic discovery): 2",
        "Epic discovery parity: ok",
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
    assert calls["descendant_calls"] == [
        ("at-1", False),
        ("at-2", False),
    ]


def test_render_startup_overview_caps_deferred_epic_scan(monkeypatch) -> None:
    module = _load_script()
    monkeypatch.setenv("ATELIER_STARTUP_DEFERRED_EPIC_SCAN_LIMIT", "1")
    monkeypatch.setattr(
        module,
        "execute_startup_command_plan",
        lambda *_args, **_kwargs: _startup_result(
            module,
            inbox=[],
            queued=[],
            epics=[
                {"id": "at-1", "title": "Epic one", "status": "open"},
                {"id": "at-2", "title": "Epic two", "status": "in_progress"},
                {"id": "at-3", "title": "Epic three", "status": "blocked"},
            ],
            parity=SimpleNamespace(
                active_top_level_work_count=3,
                indexed_active_epic_count=3,
                missing_executable_identity=(),
                missing_from_index=(),
                in_parity=True,
            ),
        ),
    )
    monkeypatch.setattr(
        module.StartupBeadsInvocationHelper,
        "list_descendant_changesets",
        lambda _self, parent_id, *, include_closed: (
            scanned_epics.append(parent_id)
            or [{"id": f"{parent_id}.1", "title": "Deferred child", "status": "deferred"}]
        ),
    )
    scanned_epics: list[str] = []
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
        "- Beads root: /beads",
        "No unread messages.",
        "No queued messages.",
        "- Total epics: 3",
        "- Active top-level work (open/in_progress/blocked): 3",
        "- Indexed active epics (at:epic discovery): 3",
        "Epic discovery parity: ok",
        "Deferred changesets under open/in-progress/blocked epics:",
        "- at-1 [open] Epic one",
        "  - at-1.1 [deferred] Deferred child",
        "Deferred changeset scan limited to first 1 active epics; skipped 2.",
        "Epics by state:",
        "- at-1 [open] Example",
    ]


def test_main_emits_override_warning(monkeypatch, capsys, tmp_path: Path) -> None:
    module = _load_script()
    beads_root = tmp_path / "override-beads"
    beads_root.mkdir()

    monkeypatch.setattr(
        module,
        "_resolve_context",
        lambda **_kwargs: (beads_root, Path("/repo"), "warning: override mismatch"),
    )
    monkeypatch.setattr(
        module,
        "_render_startup_overview",
        lambda *_args, **_kwargs: "Planner startup overview",
    )
    monkeypatch.setattr(
        module.sys,
        "argv",
        ["refresh_overview.py", "--agent-id", "atelier/planner/example"],
    )

    module.main()

    captured = capsys.readouterr()
    assert "warning: override mismatch" in captured.err


@pytest.mark.parametrize("repo_dir_value", ["/repo/canonical", "./worktree"])
def test_resolve_context_passes_runtime_repo_hint_to_beads_context(
    monkeypatch,
    repo_dir_value: str,
) -> None:
    module = _load_script()
    captured_repo_hints: list[str | None] = []
    beads_root = Path("/beads")

    def _fake_context(*, beads_dir: str | None, repo_dir: str | None):
        _ = beads_dir
        captured_repo_hints.append(repo_dir)
        return SimpleNamespace(
            beads_root=beads_root,
            repo_root=Path("/resolved-repo"),
            override_warning=None,
        )

    monkeypatch.setattr(module, "resolve_skill_beads_context", _fake_context)

    resolved_beads_root, resolved_repo_root, warning = module._resolve_context(
        beads_dir=None,
        repo_dir=repo_dir_value,
    )

    assert captured_repo_hints == [repo_dir_value]
    assert resolved_beads_root == beads_root
    assert resolved_repo_root == Path("/resolved-repo")
    assert warning is None


def test_render_startup_overview_reports_identity_guardrail_remediation(monkeypatch) -> None:
    module = _load_script()
    monkeypatch.setattr(
        module,
        "execute_startup_command_plan",
        lambda *_args, **_kwargs: _startup_result(
            module,
            inbox=[],
            queued=[],
            epics=[],
            parity=SimpleNamespace(
                active_top_level_work_count=1,
                indexed_active_epic_count=0,
                missing_executable_identity=(
                    SimpleNamespace(
                        issue_id="at-missing",
                        status="open",
                        issue_type="epic",
                        labels=(),
                        remediation_command="bd update at-missing --type epic --add-label at:epic",
                    ),
                ),
                missing_from_index=(),
                in_parity=False,
            ),
        ),
    )
    monkeypatch.setattr(
        module.StartupBeadsInvocationHelper,
        "list_descendant_changesets",
        lambda *_args, **_kwargs: [],
    )
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

    assert "Identity guardrail violations (deterministic remediation):" in rendered
    assert "remediation: bd update at-missing --type epic --add-label at:epic" in rendered
    assert "bd --beads-dir" not in rendered


def test_render_startup_overview_passes_agent_id_to_command_plan(monkeypatch) -> None:
    module = _load_script()
    captured_agent_ids: list[str] = []

    def _fake_execute(agent_id: str, **_kwargs):
        captured_agent_ids.append(agent_id)
        return _startup_result(
            module,
            inbox=[],
            queued=[],
            epics=[],
            parity=_parity_ok(),
        )

    monkeypatch.setattr(module, "execute_startup_command_plan", _fake_execute)
    monkeypatch.setattr(
        module.StartupBeadsInvocationHelper,
        "list_descendant_changesets",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        module.planner_overview,
        "render_epics",
        lambda issues, *, show_drafts: "Epics by state:\n- (none)",
    )

    module._render_startup_overview(
        "atelier/planner/example",
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
    )

    assert captured_agent_ids == ["atelier/planner/example"]


def test_render_startup_overview_falls_back_to_deterministic_output(monkeypatch) -> None:
    module = _load_script()
    monkeypatch.setattr(
        module,
        "execute_startup_command_plan",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("command failed: bd list --label at:message")
        ),
    )
    monkeypatch.setattr(
        module.planner_overview,
        "render_epics",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("epic renderer should not run in fallback path")
        ),
    )

    rendered = module._render_startup_overview(
        "atelier/planner/example",
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
    )

    assert rendered.splitlines() == [
        "Planner startup overview",
        "- Beads root: /beads",
        "Startup collection fallback (deterministic):",
        "- phase=render_startup_overview error=RuntimeError detail=command failed: bd list --label "
        "at:message",
        "No unread messages.",
        "No queued messages.",
        "- Total epics: 0",
        "- Active top-level work (open/in_progress/blocked): 0",
        "- Indexed active epics (at:epic discovery): 0",
        "No deferred changesets under open/in-progress/blocked epics.",
        "Epics by state:",
        "- unavailable (startup triage failed before epic rendering)",
    ]


def test_render_startup_overview_does_not_swallow_system_exit(monkeypatch) -> None:
    module = _load_script()
    monkeypatch.setattr(
        module,
        "execute_startup_command_plan",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(SystemExit(7)),
    )

    try:
        module._render_startup_overview(
            "atelier/planner/example",
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
        )
    except SystemExit as exc:
        assert exc.code == 7
    else:
        raise AssertionError("expected SystemExit to propagate")

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


def _load_script_module():
    script_path = (
        Path(__file__).resolve().parents[3]
        / "src"
        / "atelier"
        / "skills"
        / "plan-create-epic"
        / "scripts"
        / "create_epic.py"
    )
    spec = importlib.util.spec_from_file_location("create_epic_script", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_create_epic_defaults_to_deferred_status(monkeypatch, tmp_path: Path) -> None:
    module = _load_script_module()
    captured: dict[str, object] = {}
    context = SimpleNamespace(
        project_dir=tmp_path / "project",
        beads_root=tmp_path / ".beads",
    )

    monkeypatch.setattr(
        module.auto_export,
        "resolve_auto_export_context",
        lambda **_kwargs: context,
    )

    class FakeStore:
        async def create_epic(self, request):
            captured["request"] = request
            return SimpleNamespace(id="at-epic-1")

    monkeypatch.setattr(module, "_build_store", lambda **_kwargs: FakeStore())
    monkeypatch.setattr(
        module.auto_export,
        "auto_export_issue",
        lambda issue_id, *, context: module.auto_export.AutoExportResult(
            status="skipped",
            issue_id=issue_id,
            provider=None,
            message="auto-export disabled for test",
        ),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "create_epic.py",
            "--title",
            "Lifecycle migration",
            "--scope",
            "Move readiness semantics to deferred/open statuses.",
            "--acceptance",
            "Planner transitions use status-only lifecycle.",
            "--changeset-strategy",
            "Keep review scope under 400 LOC.",
            "--design",
            "Document the promotion invariants.",
            "--no-export",
        ],
    )

    module.main()

    request = captured["request"]
    assert request.title == "Lifecycle migration"
    assert request.description == (
        "Move readiness semantics to deferred/open statuses.\n\n"
        "Changeset strategy:\n"
        "Keep review scope under 400 LOC."
    )
    assert request.acceptance_criteria == "Planner transitions use status-only lifecycle."
    assert request.design == "Document the promotion invariants."
    assert request.labels == ("ext:no-export",)
    assert request.initial_status.value == "deferred"


def test_create_epic_surfaces_store_fail_closed_error(
    monkeypatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    module = _load_script_module()
    export_calls: list[str] = []
    context = SimpleNamespace(
        project_dir=tmp_path / "project",
        beads_root=tmp_path / ".beads",
    )

    monkeypatch.setattr(
        module.auto_export,
        "resolve_auto_export_context",
        lambda **_kwargs: context,
    )

    class FakeStore:
        async def create_epic(self, request):
            del request
            raise RuntimeError(
                "created epic at-epic-1 but failed to set status=deferred after 5 "
                "attempts; auto-closed to fail closed (simulated update failure)"
            )

    monkeypatch.setattr(module, "_build_store", lambda **_kwargs: FakeStore())
    monkeypatch.setattr(
        module.auto_export,
        "auto_export_issue",
        lambda issue_id, *, context: export_calls.append(issue_id),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "create_epic.py",
            "--title",
            "Lifecycle migration",
            "--scope",
            "Move readiness semantics to deferred/open statuses.",
            "--acceptance",
            "Planner transitions use status-only lifecycle.",
        ],
    )

    with pytest.raises(SystemExit) as excinfo:
        module.main()

    captured = capsys.readouterr()
    assert excinfo.value.code == 1
    assert "auto-closed to fail closed" in captured.err
    assert export_calls == []


def test_create_epic_rejects_low_information_payload(
    monkeypatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    module = _load_script_module()
    context = SimpleNamespace(
        project_dir=tmp_path / "project",
        beads_root=tmp_path / ".beads",
    )

    monkeypatch.setattr(
        module.auto_export,
        "resolve_auto_export_context",
        lambda **_kwargs: context,
    )
    monkeypatch.setattr(
        module,
        "_build_store",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("store create must not run when payload validation fails")
        ),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "create_epic.py",
            "--title",
            "/",
            "--scope",
            "/",
            "--acceptance",
            "Validation should reject placeholder payloads.",
        ],
    )

    with pytest.raises(SystemExit) as excinfo:
        module.main()

    captured = capsys.readouterr()
    assert excinfo.value.code == 1
    assert "invalid executable work payload for epic creation" in captured.err
    assert "- title: [placeholder_value]" in captured.err
    assert "- scope: [placeholder_value]" in captured.err
    assert "planner-context: NEEDS-DECISION" in captured.err

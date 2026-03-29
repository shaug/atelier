from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace


def _load_script_module():
    script_path = (
        Path(__file__).resolve().parents[3]
        / "src"
        / "atelier"
        / "skills"
        / "plan-split-tasks"
        / "scripts"
        / "split_tasks.py"
    )
    spec = importlib.util.spec_from_file_location("split_tasks_script", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_split_tasks_propagates_inherited_refinement_from_parent(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_script_module()
    created_requests: list[object] = []
    parent_notes = (
        "planning_refinement.v1\n"
        "authoritative: true\n"
        "mode: requested\n"
        "required: true\n"
        "lineage_root: at-epic\n"
        "approval_status: approved\n"
        "approval_source: operator\n"
        "approved_by: planner-user\n"
        "approved_at: 2026-03-29T12:00:00Z\n"
        "plan_edit_rounds_max: 6\n"
        "post_impl_review_rounds_max: 10\n"
        "latest_verdict: READY\n"
    )
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
        async def get_changeset(self, issue_id):
            return SimpleNamespace(id=issue_id, epic_id="at-epic", notes=parent_notes)

        async def create_changeset(self, request):
            created_requests.append(request)
            child_index = len(created_requests)
            return SimpleNamespace(id=f"at-epic.{child_index + 1}")

        async def append_notes(self, request):  # pragma: no cover - defensive
            raise AssertionError(request)

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
            "split_tasks.py",
            "--parent-id",
            "at-epic.1",
            "--task",
            "Split API contract::API surface is independently testable.",
            "--task",
            "Split worker integration::Worker integration preserves claim behavior.",
        ],
    )

    module.main()

    assert len(created_requests) == 2
    for request in created_requests:
        note = request.notes[0]
        assert note.startswith("planning_refinement.v1")
        assert "mode: inherited" in note
        assert "required: true" in note
        assert "lineage_root: at-epic" in note
        assert "plan_edit_rounds_max: 6" in note
        assert "post_impl_review_rounds_max: 10" in note


def test_split_tasks_leaves_unrefined_lineage_unmarked(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_script_module()
    created_requests: list[object] = []
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
        async def get_changeset(self, issue_id):
            return SimpleNamespace(id=issue_id, epic_id="at-epic", notes="")

        async def create_changeset(self, request):
            created_requests.append(request)
            return SimpleNamespace(id="at-epic.2")

        async def append_notes(self, request):  # pragma: no cover - defensive
            raise AssertionError(request)

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
            "split_tasks.py",
            "--parent-id",
            "at-epic.1",
            "--task",
            "Split API contract::API surface is independently testable.",
        ],
    )

    module.main()

    assert len(created_requests) == 1
    assert created_requests[0].notes == ()

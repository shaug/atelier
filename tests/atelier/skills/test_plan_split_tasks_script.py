from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from atelier.lib.beads import ShowIssueRequest
from atelier.store import ChangesetQuery
from tests.atelier.skills.h1_store_harness import issue_builder, make_store_for_backend


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


def test_split_tasks_fails_closed_when_parent_required_refinement_is_malformed(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    module = _load_script_module()
    created_requests: list[object] = []
    parent_notes = (
        "planning_refinement.v1\n"
        "authoritative: true\n"
        "required: true\n"
        "approval_status: approved\n"
        "approval_source: operator\n"
        "approved_by: planner-user\n"
        "approved_at: 2026-03-29T12:00:00Z\n"
        "latest_verdict: NOT_READY\n"
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
            return SimpleNamespace(id="at-epic.2")

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

    with pytest.raises(SystemExit) as excinfo:
        module.main()

    captured = capsys.readouterr()
    assert excinfo.value.code == 1
    assert "required parent refinement metadata is malformed" in captured.err
    assert created_requests == []


@pytest.mark.parametrize(
    ("parent_notes", "expect_inherited"),
    [
        (
            (
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
            ),
            True,
        ),
        ("", False),
    ],
)
def test_split_tasks_h1_integration_preserves_refinement_lineage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    parent_notes: str,
    expect_inherited: bool,
) -> None:
    import atelier.lib.beads as beads_lib

    module = _load_script_module()
    context = SimpleNamespace(project_dir=tmp_path / "repo", beads_root=tmp_path / ".beads")
    context.project_dir.mkdir(parents=True, exist_ok=True)
    context.beads_root.mkdir(parents=True, exist_ok=True)
    _client, store = make_store_for_backend(
        "in-memory",
        issues=(
            issue_builder.issue(
                "at-epic",
                title="Parent epic",
                issue_type="epic",
                status="open",
                labels=("at:epic",),
            ),
            issue_builder.issue(
                "at-epic.1",
                title="Parent changeset",
                issue_type="task",
                status="open",
                labels=("at:changeset",),
                parent="at-epic",
                extra_fields={"notes": parent_notes} if parent_notes else None,
            ),
        ),
    )

    monkeypatch.setattr(module, "_build_store", lambda **_kwargs: store)
    monkeypatch.setattr(beads_lib, "SubprocessBeadsClient", lambda **_kwargs: _client)
    monkeypatch.setattr(
        module.auto_export, "resolve_auto_export_context", lambda **_kwargs: context
    )
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
            "One::Acceptance one",
            "--task",
            "Two::Acceptance two",
        ],
    )

    module.main()

    created = asyncio.run(store.list_changesets(ChangesetQuery(epic_id="at-epic")))
    created_ids = sorted(item.id for item in created if item.id != "at-epic.1")
    assert len(created_ids) == 2
    for child_id in created_ids:
        child_issue = asyncio.run(_client.show(ShowIssueRequest(issue_id=child_id)))
        notes_blob = str(getattr(child_issue, "description", "") or "")
        if expect_inherited:
            assert "planning_refinement.v1" in notes_blob
            assert "mode: inherited" in notes_blob
            assert "required: true" in notes_blob
        else:
            assert "planning_refinement.v1" not in notes_blob

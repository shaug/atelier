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
        / "plan-set-refinement"
        / "scripts"
        / "set_refinement.py"
    )
    spec = importlib.util.spec_from_file_location("set_refinement_script", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("lifecycle", ["deferred", "open", "in_progress", "blocked"])
def test_set_refinement_accepts_any_active_lifecycle_state(
    monkeypatch: pytest.MonkeyPatch,
    lifecycle: str,
) -> None:
    module = _load_script_module()
    captured: list[tuple[str, tuple[str, ...]]] = []

    class FakeStore:
        async def get_epic(self, issue_id: str):
            return SimpleNamespace(id=issue_id, lifecycle=lifecycle)

        async def get_changeset(self, issue_id: str):
            del issue_id
            raise LookupError("not a changeset")

        async def append_notes(self, request):
            captured.append((request.issue_id, request.notes))
            return SimpleNamespace(id=request.issue_id)

    monkeypatch.setattr(module, "_build_store", lambda **_kwargs: FakeStore())
    monkeypatch.setattr(
        module, "_resolve_context", lambda **_kwargs: (Path("/tmp/.beads"), Path("/tmp"), None)
    )
    monkeypatch.setattr(sys, "argv", ["set_refinement.py", "--issue-id", "at-123"])

    module.main()

    assert captured
    issue_id, notes = captured[0]
    assert issue_id == "at-123"
    assert len(notes) == 1
    assert notes[0].startswith("planning_refinement.v1")


def test_set_refinement_requires_approval_evidence_when_required(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_script_module()
    appended = []

    class FakeStore:
        async def get_epic(self, issue_id: str):
            return SimpleNamespace(id=issue_id, lifecycle="open")

        async def get_changeset(self, issue_id: str):
            del issue_id
            raise LookupError("not a changeset")

        async def append_notes(self, request):
            appended.append(request)
            return SimpleNamespace(id=request.issue_id)

    monkeypatch.setattr(module, "_build_store", lambda **_kwargs: FakeStore())
    monkeypatch.setattr(
        module, "_resolve_context", lambda **_kwargs: (Path("/tmp/.beads"), Path("/tmp"), None)
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "set_refinement.py",
            "--issue-id",
            "at-123",
            "--required",
        ],
    )

    with pytest.raises(SystemExit) as excinfo:
        module.main()

    captured = capsys.readouterr()
    assert excinfo.value.code == 1
    assert "approval evidence" in captured.err
    assert appended == []


def test_set_refinement_records_inherited_lineage_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_script_module()
    captured: list[str] = []

    class FakeStore:
        async def get_epic(self, issue_id: str):
            del issue_id
            raise LookupError("not an epic")

        async def get_changeset(self, issue_id: str):
            return SimpleNamespace(id=issue_id, lifecycle="in_progress")

        async def append_notes(self, request):
            captured.extend(request.notes)
            return SimpleNamespace(id=request.issue_id)

    monkeypatch.setattr(module, "_build_store", lambda **_kwargs: FakeStore())
    monkeypatch.setattr(
        module, "_resolve_context", lambda **_kwargs: (Path("/tmp/.beads"), Path("/tmp"), None)
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "set_refinement.py",
            "--issue-id",
            "at-456",
            "--mode",
            "inherited",
            "--lineage-root",
            "at-123",
            "--plan-edit-rounds-max",
            "7",
            "--post-impl-review-rounds-max",
            "9",
        ],
    )

    module.main()

    assert captured
    note = captured[0]
    assert "mode: inherited" in note
    assert "lineage_root: at-123" in note
    assert "plan_edit_rounds_max: 7" in note
    assert "post_impl_review_rounds_max: 9" in note


def test_set_refinement_project_policy_mode_auto_records_approval_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_script_module()
    captured: list[str] = []

    class FakeStore:
        async def get_epic(self, issue_id: str):
            return SimpleNamespace(id=issue_id, lifecycle="open")

        async def get_changeset(self, issue_id: str):
            del issue_id
            raise LookupError("not a changeset")

        async def append_notes(self, request):
            captured.extend(request.notes)
            return SimpleNamespace(id=request.issue_id)

    monkeypatch.setattr(module, "_build_store", lambda **_kwargs: FakeStore())
    monkeypatch.setattr(
        module, "_resolve_context", lambda **_kwargs: (Path("/tmp/.beads"), Path("/tmp"), None)
    )
    monkeypatch.setattr(
        module,
        "_resolve_refinement_policy",
        lambda **_kwargs: SimpleNamespace(
            required_by_default=True,
            plan_edit_rounds_max=13,
            post_impl_review_rounds_max=21,
        ),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "set_refinement.py",
            "--issue-id",
            "at-123",
            "--mode",
            "project_policy",
            "--required",
        ],
    )

    module.main()

    assert captured
    note = captured[0]
    assert "mode: project_policy" in note
    assert "approval_status: approved" in note
    assert "approval_source: project_policy" in note
    assert "approved_by: project_policy" in note
    assert "approved_at:" in note
    assert "plan_edit_rounds_max: 13" in note
    assert "post_impl_review_rounds_max: 21" in note


def test_set_refinement_project_policy_mode_fails_when_policy_not_configured(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_script_module()

    class FakeStore:
        async def get_epic(self, issue_id: str):
            return SimpleNamespace(id=issue_id, lifecycle="open")

        async def get_changeset(self, issue_id: str):
            del issue_id
            raise LookupError("not a changeset")

        async def append_notes(self, request):  # pragma: no cover - defensive
            raise AssertionError(request)

    monkeypatch.setattr(module, "_build_store", lambda **_kwargs: FakeStore())
    monkeypatch.setattr(
        module, "_resolve_context", lambda **_kwargs: (Path("/tmp/.beads"), Path("/tmp"), None)
    )
    monkeypatch.setattr(
        module,
        "_resolve_refinement_policy",
        lambda **_kwargs: SimpleNamespace(
            required_by_default=False,
            plan_edit_rounds_max=5,
            post_impl_review_rounds_max=8,
        ),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "set_refinement.py",
            "--issue-id",
            "at-123",
            "--mode",
            "project_policy",
            "--required",
        ],
    )

    with pytest.raises(SystemExit) as excinfo:
        module.main()

    captured = capsys.readouterr()
    assert excinfo.value.code == 1
    assert "project_policy mode requires configured policy" in captured.err

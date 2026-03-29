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
        / "plan-changesets"
        / "scripts"
        / "create_changeset.py"
    )
    spec = importlib.util.spec_from_file_location("create_changeset_script", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_create_changeset_defaults_to_deferred_status(monkeypatch, tmp_path: Path) -> None:
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
        async def create_changeset(self, request):
            captured["request"] = request
            return SimpleNamespace(id="at-123")

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
            "create_changeset.py",
            "--epic-id",
            "at-epic",
            "--title",
            "Draft changeset",
            "--acceptance",
            "Acceptance text",
            "--description",
            "Keep scope under 300 LOC.",
            "--notes",
            "Record decomposition rationale.",
            "--no-export",
        ],
    )

    module.main()

    request = captured["request"]
    assert request.epic_id == "at-epic"
    assert request.title == "Draft changeset"
    assert request.acceptance_criteria == "Acceptance text"
    assert request.description == "Keep scope under 300 LOC."
    assert request.notes == ("Record decomposition rationale.",)
    assert request.labels == ("ext:no-export",)
    assert request.initial_status.value == "deferred"


def test_create_changeset_accepts_open_status_override(
    monkeypatch,
    tmp_path: Path,
) -> None:
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
        async def create_changeset(self, request):
            captured["request"] = request
            return SimpleNamespace(id="at-123")

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
            "create_changeset.py",
            "--epic-id",
            "at-epic",
            "--title",
            "Ready changeset",
            "--acceptance",
            "Acceptance text",
            "--status",
            "open",
        ],
    )

    module.main()

    assert captured["request"].initial_status.value == "open"


def test_create_changeset_surfaces_store_fail_closed_error(
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
        async def create_changeset(self, request):
            del request
            raise RuntimeError(
                "created changeset at-123 but failed to set status=deferred after 5 "
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
            "create_changeset.py",
            "--epic-id",
            "at-epic",
            "--title",
            "Draft changeset",
            "--acceptance",
            "Acceptance text",
        ],
    )

    with pytest.raises(SystemExit) as excinfo:
        module.main()

    captured = capsys.readouterr()
    assert excinfo.value.code == 1
    assert "auto-closed to fail closed" in captured.err
    assert export_calls == []


def test_create_changeset_rejects_low_information_description(
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
            "create_changeset.py",
            "--epic-id",
            "at-epic",
            "--title",
            "Prevent malformed work beads",
            "--acceptance",
            "Malformed executable work records are rejected before create.",
            "--description",
            "/",
        ],
    )

    with pytest.raises(SystemExit) as excinfo:
        module.main()

    captured = capsys.readouterr()
    assert excinfo.value.code == 1
    assert "invalid executable work payload for changeset creation" in captured.err
    assert "- description: [placeholder_value]" in captured.err
    assert "planner-context: NEEDS-DECISION" in captured.err


@pytest.mark.parametrize(
    ("incident_id", "title", "description"),
    [
        ("at-5j4z", "/", "/"),
        ("at-adjt", "/", "Investigate dependency drift in planner handoff"),
        ("at-b22t", "Fix worker startup contract", "/"),
        ("at-dc89", "x", "y"),
    ],
)
def test_create_changeset_rejects_incident_placeholder_shapes(
    incident_id: str,
    title: str,
    description: str,
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
            AssertionError(
                f"incident {incident_id} should fail validation before any store mutation"
            )
        ),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "create_changeset.py",
            "--epic-id",
            "at-epic",
            "--title",
            title,
            "--acceptance",
            f"Regression guard for {incident_id} malformed payload shape.",
            "--description",
            description,
        ],
    )

    with pytest.raises(SystemExit) as excinfo:
        module.main()

    captured = capsys.readouterr()
    assert excinfo.value.code == 1
    assert "invalid executable work payload for changeset creation" in captured.err
    assert "planner-context: NEEDS-DECISION" in captured.err


def test_create_changeset_inherits_required_refinement_from_parent(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_script_module()
    captured_request: dict[str, object] = {}
    context = SimpleNamespace(
        project_dir=tmp_path / "project",
        beads_root=tmp_path / ".beads",
    )
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
        "plan_edit_rounds_max: 7\n"
        "post_impl_review_rounds_max: 9\n"
        "latest_verdict: READY\n"
    )

    monkeypatch.setattr(
        module.auto_export,
        "resolve_auto_export_context",
        lambda **_kwargs: context,
    )

    class FakeStore:
        async def create_changeset(self, request):
            captured_request["request"] = request
            return SimpleNamespace(id="at-epic.1")

        async def get_epic(self, epic_id):
            return SimpleNamespace(id=epic_id, notes=parent_notes)

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
            "create_changeset.py",
            "--epic-id",
            "at-epic",
            "--title",
            "Inherited refinement changeset",
            "--acceptance",
            "Child changesets preserve required refinement lineage.",
        ],
    )

    module.main()

    request = captured_request["request"]
    assert request.notes
    note = request.notes[0]
    assert note.startswith("planning_refinement.v1")
    assert "authoritative: true" in note
    assert "mode: inherited" in note
    assert "required: true" in note
    assert "lineage_root: at-epic" in note
    assert "plan_edit_rounds_max: 7" in note
    assert "post_impl_review_rounds_max: 9" in note


def test_create_changeset_unrefined_control_keeps_notes_unchanged(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_script_module()
    captured_request: dict[str, object] = {}
    context = SimpleNamespace(
        project_dir=tmp_path / "project",
        beads_root=tmp_path / ".beads",
    )
    parent_notes = (
        "planning_refinement.v1\n"
        "authoritative: true\n"
        "mode: requested\n"
        "required: false\n"
        "approval_status: missing\n"
        "latest_verdict: REVISED\n"
    )

    monkeypatch.setattr(
        module.auto_export,
        "resolve_auto_export_context",
        lambda **_kwargs: context,
    )

    class FakeStore:
        async def create_changeset(self, request):
            captured_request["request"] = request
            return SimpleNamespace(id="at-epic.2")

        async def get_epic(self, epic_id):
            return SimpleNamespace(id=epic_id, notes=parent_notes)

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
            "create_changeset.py",
            "--epic-id",
            "at-epic",
            "--title",
            "Unrefined control changeset",
            "--acceptance",
            "Unrefined parents do not add inherited refinement notes.",
            "--notes",
            "preserve original operator note",
        ],
    )

    module.main()

    request = captured_request["request"]
    assert request.notes == ("preserve original operator note",)


def test_create_changeset_fails_closed_when_parent_notes_lookup_errors(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    import atelier.lib.beads as beads_lib

    module = _load_script_module()
    context = SimpleNamespace(
        project_dir=tmp_path / "project",
        beads_root=tmp_path / ".beads",
    )
    created_requests: list[object] = []

    monkeypatch.setattr(
        module.auto_export,
        "resolve_auto_export_context",
        lambda **_kwargs: context,
    )

    class FakeStore:
        async def create_changeset(self, request):
            created_requests.append(request)
            return SimpleNamespace(id="at-epic.3")

        async def get_epic(self, epic_id):
            # Omit notes entirely to force fallback lookup via client.show.
            return SimpleNamespace(id=epic_id)

    class ExplodingClient:
        def __init__(self, **_kwargs):
            pass

        async def show(self, _request):
            raise RuntimeError("transient show failure")

    monkeypatch.setattr(module, "_build_store", lambda **_kwargs: FakeStore())
    monkeypatch.setattr(beads_lib, "SubprocessBeadsClient", ExplodingClient)
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
            "create_changeset.py",
            "--epic-id",
            "at-epic",
            "--title",
            "Fail closed lineage read error",
            "--acceptance",
            "Child creation must stop when parent refinement notes are unreadable.",
        ],
    )

    with pytest.raises(SystemExit) as excinfo:
        module.main()

    captured = capsys.readouterr()
    assert excinfo.value.code == 1
    assert "failed to read parent refinement notes" in captured.err
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
                "plan_edit_rounds_max: 7\n"
                "post_impl_review_rounds_max: 9\n"
                "latest_verdict: READY\n"
            ),
            True,
        ),
        ("", False),
    ],
)
def test_create_changeset_h1_integration_refinement_inheritance(
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
            "create_changeset.py",
            "--epic-id",
            "at-epic",
            "--title",
            "Integration inheritance check",
            "--acceptance",
            "Child changesets preserve lineage semantics.",
        ],
    )

    module.main()

    created = asyncio.run(store.list_changesets(ChangesetQuery(epic_id="at-epic")))
    assert len(created) == 1
    created_changeset = asyncio.run(store.get_changeset(created[0].id))
    created_issue = asyncio.run(_client.show(ShowIssueRequest(issue_id=created_changeset.id)))
    notes_blob = str(getattr(created_issue, "description", "") or "")

    if expect_inherited:
        assert "planning_refinement.v1" in notes_blob
        assert "mode: inherited" in notes_blob
        assert "required: true" in notes_blob
    else:
        assert "planning_refinement.v1" not in notes_blob

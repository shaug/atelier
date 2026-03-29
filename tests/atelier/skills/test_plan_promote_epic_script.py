from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.atelier.skills.h1_store_harness import issue_builder, make_store_for_backend


def _load_script_module():
    script_path = (
        Path(__file__).resolve().parents[3]
        / "src"
        / "atelier"
        / "skills"
        / "plan-promote-epic"
        / "scripts"
        / "promote_epic.py"
    )
    spec = importlib.util.spec_from_file_location("plan_promote_epic_script", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _issue(
    issue_id: str,
    *,
    title: str,
    status: str = "deferred",
    description: str = "",
    acceptance: str = "Acceptance text",
    notes: str | tuple[str, ...] | None = None,
    dependencies: tuple[str, ...] = (),
):
    return SimpleNamespace(
        id=issue_id,
        title=title,
        status=status,
        description=description,
        acceptance_criteria=acceptance,
        notes=notes,
        dependencies=tuple(SimpleNamespace(id=dependency) for dependency in dependencies),
    )


def test_promote_epic_preview_requires_confirmation(monkeypatch, capsys, tmp_path: Path) -> None:
    module = _load_script_module()
    transitions: list[object] = []

    monkeypatch.setattr(
        module,
        "_resolve_context",
        lambda **_kwargs: (tmp_path / ".beads", tmp_path / "repo", None),
    )

    epic_issue = _issue(
        "at-epic",
        title="Epic",
        description=(
            "changeset_strategy: Keep review scope small.\n"
            "related_context: at-context\n"
            "promotion_note: ready for confirmation\n"
        ),
    )
    child_issue = _issue(
        "at-epic.1",
        title="Child",
        description=("changeset_note: preserve lifecycle behavior\nrelated_context: at-context\n"),
    )

    class FakeStore:
        async def get_epic(self, epic_id):
            assert epic_id == "at-epic"
            from atelier.store import LifecycleStatus

            return SimpleNamespace(id=epic_id, lifecycle=LifecycleStatus.DEFERRED)

        async def list_changesets(self, query):
            del query
            from atelier.store import LifecycleStatus

            return (SimpleNamespace(id="at-epic.1", lifecycle=LifecycleStatus.DEFERRED),)

        async def transition_lifecycle(self, request):
            transitions.append(request)
            return request

    class FakeClient:
        async def show(self, request):
            return {"at-epic": epic_issue, "at-epic.1": child_issue}[request.issue_id]

    monkeypatch.setattr(
        module, "_build_store_and_client", lambda **_kwargs: (FakeStore(), FakeClient())
    )
    monkeypatch.setattr(sys, "argv", ["promote_epic.py", "--epic-id", "at-epic"])

    module.main()

    captured = capsys.readouterr()
    assert "confirmation_required" in captured.out
    assert transitions == []


def test_promote_epic_applies_store_lifecycle_transitions(monkeypatch, tmp_path: Path) -> None:
    module = _load_script_module()
    transitions: list[object] = []

    monkeypatch.setattr(
        module,
        "_resolve_context",
        lambda **_kwargs: (tmp_path / ".beads", tmp_path / "repo", None),
    )

    epic_issue = _issue(
        "at-epic",
        title="Epic",
        description=(
            "changeset_strategy: Keep review scope small.\n"
            "related_context: at-context\n"
            "promotion_note: ready for confirmation\n"
        ),
    )
    child_issue = _issue(
        "at-epic.1",
        title="Child",
        description=("changeset_note: preserve lifecycle behavior\nrelated_context: at-context\n"),
    )

    class FakeStore:
        async def get_epic(self, epic_id):
            assert epic_id == "at-epic"
            from atelier.store import LifecycleStatus

            return SimpleNamespace(id=epic_id, lifecycle=LifecycleStatus.DEFERRED)

        async def list_changesets(self, query):
            del query
            from atelier.store import LifecycleStatus

            return (SimpleNamespace(id="at-epic.1", lifecycle=LifecycleStatus.DEFERRED),)

        async def transition_lifecycle(self, request):
            transitions.append(request)
            return request

    class FakeClient:
        async def show(self, request):
            return {"at-epic": epic_issue, "at-epic.1": child_issue}[request.issue_id]

    monkeypatch.setattr(
        module, "_build_store_and_client", lambda **_kwargs: (FakeStore(), FakeClient())
    )
    monkeypatch.setattr(sys, "argv", ["promote_epic.py", "--epic-id", "at-epic", "--yes"])

    module.main()

    assert [request.issue_id for request in transitions] == ["at-epic", "at-epic.1"]


def test_promote_epic_preview_reads_canonical_notes_for_epic_and_child(
    monkeypatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    module = _load_script_module()
    transitions: list[object] = []

    monkeypatch.setattr(
        module,
        "_resolve_context",
        lambda **_kwargs: (tmp_path / ".beads", tmp_path / "repo", None),
    )

    epic_issue = _issue(
        "at-epic",
        title="Epic",
        description=("changeset_strategy: Keep review scope small.\nrelated_context: at-context\n"),
        notes="canonical epic note\n- preserves preview readiness",
    )
    child_issue = _issue(
        "at-epic.1",
        title="Child",
        description="related_context: at-context\n",
        notes="canonical child note",
    )

    class FakeStore:
        async def get_epic(self, epic_id):
            assert epic_id == "at-epic"
            from atelier.store import LifecycleStatus

            return SimpleNamespace(id=epic_id, lifecycle=LifecycleStatus.DEFERRED)

        async def list_changesets(self, query):
            del query
            from atelier.store import LifecycleStatus

            return (SimpleNamespace(id="at-epic.1", lifecycle=LifecycleStatus.DEFERRED),)

        async def transition_lifecycle(self, request):
            transitions.append(request)
            return request

    class FakeClient:
        async def show(self, request):
            return {"at-epic": epic_issue, "at-epic.1": child_issue}[request.issue_id]

    monkeypatch.setattr(
        module, "_build_store_and_client", lambda **_kwargs: (FakeStore(), FakeClient())
    )
    monkeypatch.setattr(sys, "argv", ["promote_epic.py", "--epic-id", "at-epic"])

    module.main()

    captured = capsys.readouterr()
    assert "canonical epic note" in captured.out
    assert "canonical child note" in captured.out
    assert "Missing detail sections: notes" not in captured.out
    assert "confirmation_required" in captured.out
    assert transitions == []


def test_render_issue_preview_prefers_canonical_notes_over_description_markers() -> None:
    module = _load_script_module()
    issue = _issue(
        "at-epic",
        title="Epic",
        description="related_context: at-context\npromotion_note: legacy note marker\n",
        notes="canonical notes field",
    )

    preview = module._render_issue_preview(header="EPIC at-epic", issue=issue)

    notes_section = preview.split("Notes:\n", maxsplit=1)[1].split(
        "\nAcceptance Criteria:",
        maxsplit=1,
    )[0]

    assert notes_section == "canonical notes field"
    assert "Missing detail sections: notes" not in preview


def test_promote_epic_fails_when_one_child_has_no_decomposition_rationale(
    monkeypatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    module = _load_script_module()

    monkeypatch.setattr(
        module,
        "_resolve_context",
        lambda **_kwargs: (tmp_path / ".beads", tmp_path / "repo", None),
    )

    epic_issue = _issue(
        "at-epic",
        title="Epic",
        description=("related_context: at-context\npromotion_note: ready for confirmation\n"),
    )
    child_issue = _issue(
        "at-epic.1",
        title="Child",
        description=("changeset_note: preserve lifecycle behavior\nrelated_context: at-context\n"),
    )

    class FakeStore:
        async def get_epic(self, epic_id):
            assert epic_id == "at-epic"
            from atelier.store import LifecycleStatus

            return SimpleNamespace(id=epic_id, lifecycle=LifecycleStatus.DEFERRED)

        async def list_changesets(self, query):
            del query
            from atelier.store import LifecycleStatus

            return (SimpleNamespace(id="at-epic.1", lifecycle=LifecycleStatus.DEFERRED),)

        async def transition_lifecycle(self, request):  # pragma: no cover - defensive
            raise AssertionError(request)

    class FakeClient:
        async def show(self, request):
            return {"at-epic": epic_issue, "at-epic.1": child_issue}[request.issue_id]

    monkeypatch.setattr(
        module, "_build_store_and_client", lambda **_kwargs: (FakeStore(), FakeClient())
    )
    monkeypatch.setattr(sys, "argv", ["promote_epic.py", "--epic-id", "at-epic"])

    with pytest.raises(SystemExit) as excinfo:
        module.main()

    assert excinfo.value.code == 1
    assert (
        "one-child promotion requires explicit decomposition rationale" in capsys.readouterr().err
    )


def test_promote_epic_still_fails_when_notes_are_actually_absent(
    monkeypatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    module = _load_script_module()

    monkeypatch.setattr(
        module,
        "_resolve_context",
        lambda **_kwargs: (tmp_path / ".beads", tmp_path / "repo", None),
    )

    epic_issue = _issue(
        "at-epic",
        title="Epic",
        description=("changeset_strategy: Keep review scope small.\nrelated_context: at-context\n"),
    )
    child_issue = _issue(
        "at-epic.1",
        title="Child",
        description="related_context: at-context\n",
    )

    class FakeStore:
        async def get_epic(self, epic_id):
            assert epic_id == "at-epic"
            from atelier.store import LifecycleStatus

            return SimpleNamespace(id=epic_id, lifecycle=LifecycleStatus.DEFERRED)

        async def list_changesets(self, query):
            del query
            from atelier.store import LifecycleStatus

            return (SimpleNamespace(id="at-epic.1", lifecycle=LifecycleStatus.DEFERRED),)

        async def transition_lifecycle(self, request):  # pragma: no cover - defensive
            raise AssertionError(request)

    class FakeClient:
        async def show(self, request):
            return {"at-epic": epic_issue, "at-epic.1": child_issue}[request.issue_id]

    monkeypatch.setattr(
        module, "_build_store_and_client", lambda **_kwargs: (FakeStore(), FakeClient())
    )
    monkeypatch.setattr(sys, "argv", ["promote_epic.py", "--epic-id", "at-epic"])

    with pytest.raises(SystemExit) as excinfo:
        module.main()

    assert excinfo.value.code == 1
    assert "epic missing detail sections: notes" in capsys.readouterr().err


def test_promote_epic_refinement_requires_ready_verdict(
    monkeypatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    module = _load_script_module()

    monkeypatch.setattr(
        module,
        "_resolve_context",
        lambda **_kwargs: (tmp_path / ".beads", tmp_path / "repo", None),
    )

    epic_issue = _issue(
        "at-epic",
        title="Epic",
        description=("changeset_strategy: Keep review scope small.\nrelated_context: at-context\n"),
        notes="canonical epic note",
    )
    child_issue = _issue(
        "at-epic.1",
        title="Child",
        description=("changeset_note: preserve lifecycle behavior\nrelated_context: at-context\n"),
        notes=(
            "planning_refinement.v1\n"
            "authoritative: true\n"
            "mode: requested\n"
            "required: true\n"
            "lineage_root: at-epic\n"
            "approval_status: approved\n"
            "approval_source: operator\n"
            "approved_by: planner-user\n"
            "approved_at: 2026-03-29T12:00:00Z\n"
            "latest_verdict: REVISED\n"
        ),
    )

    class FakeStore:
        async def get_epic(self, epic_id):
            assert epic_id == "at-epic"
            from atelier.store import LifecycleStatus

            return SimpleNamespace(id=epic_id, lifecycle=LifecycleStatus.DEFERRED)

        async def list_changesets(self, query):
            del query
            from atelier.store import LifecycleStatus

            return (SimpleNamespace(id="at-epic.1", lifecycle=LifecycleStatus.DEFERRED),)

        async def transition_lifecycle(self, request):  # pragma: no cover - defensive
            raise AssertionError(request)

    class FakeClient:
        async def show(self, request):
            return {"at-epic": epic_issue, "at-epic.1": child_issue}[request.issue_id]

    monkeypatch.setattr(
        module, "_build_store_and_client", lambda **_kwargs: (FakeStore(), FakeClient())
    )
    monkeypatch.setattr(sys, "argv", ["promote_epic.py", "--epic-id", "at-epic"])

    with pytest.raises(SystemExit) as excinfo:
        module.main()

    assert excinfo.value.code == 1
    assert "refinement_not_ready" in capsys.readouterr().err


def test_promote_epic_refinement_requires_ready_verdict_even_with_children(
    monkeypatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    module = _load_script_module()

    monkeypatch.setattr(
        module,
        "_resolve_context",
        lambda **_kwargs: (tmp_path / ".beads", tmp_path / "repo", None),
    )

    epic_issue = _issue(
        "at-epic",
        title="Epic",
        description=("changeset_strategy: Keep review scope small.\nrelated_context: at-context\n"),
        notes=(
            "planning_refinement.v1\n"
            "authoritative: true\n"
            "mode: requested\n"
            "required: true\n"
            "lineage_root: at-epic\n"
            "approval_status: approved\n"
            "approval_source: operator\n"
            "approved_by: planner-user\n"
            "approved_at: 2026-03-29T12:00:00Z\n"
            "latest_verdict: REVISED\n"
        ),
    )
    child_issue = _issue(
        "at-epic.1",
        title="Child",
        description=("changeset_note: preserve lifecycle behavior\nrelated_context: at-context\n"),
        notes=(
            "planning_refinement.v1\n"
            "authoritative: true\n"
            "mode: inherited\n"
            "required: true\n"
            "lineage_root: at-epic\n"
            "approval_status: approved\n"
            "approval_source: operator\n"
            "approved_by: planner-user\n"
            "approved_at: 2026-03-29T12:00:00Z\n"
            "latest_verdict: READY\n"
        ),
    )

    class FakeStore:
        async def get_epic(self, epic_id):
            assert epic_id == "at-epic"
            from atelier.store import LifecycleStatus

            return SimpleNamespace(id=epic_id, lifecycle=LifecycleStatus.DEFERRED)

        async def list_changesets(self, query):
            del query
            from atelier.store import LifecycleStatus

            return (SimpleNamespace(id="at-epic.1", lifecycle=LifecycleStatus.DEFERRED),)

        async def transition_lifecycle(self, request):  # pragma: no cover - defensive
            raise AssertionError(request)

    class FakeClient:
        async def show(self, request):
            return {"at-epic": epic_issue, "at-epic.1": child_issue}[request.issue_id]

    monkeypatch.setattr(
        module, "_build_store_and_client", lambda **_kwargs: (FakeStore(), FakeClient())
    )
    monkeypatch.setattr(sys, "argv", ["promote_epic.py", "--epic-id", "at-epic"])

    with pytest.raises(SystemExit) as excinfo:
        module.main()

    assert excinfo.value.code == 1
    assert "at-epic: refinement_not_ready" in capsys.readouterr().err


def test_promote_epic_ignores_non_ready_refinement_for_closed_children(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_script_module()
    transitions: list[object] = []

    monkeypatch.setattr(
        module,
        "_resolve_context",
        lambda **_kwargs: (tmp_path / ".beads", tmp_path / "repo", None),
    )

    epic_issue = _issue(
        "at-epic",
        title="Epic",
        description=(
            "changeset_strategy: Keep review scope small.\n"
            "related_context: at-context\n"
            "promotion_note: ready for confirmation\n"
        ),
        notes="canonical epic note",
    )
    closed_child_issue = _issue(
        "at-epic.1",
        title="Closed child",
        status="closed",
        description=("changeset_note: preserve lifecycle behavior\nrelated_context: at-context\n"),
        notes=(
            "planning_refinement.v1\n"
            "authoritative: true\n"
            "mode: inherited\n"
            "required: true\n"
            "lineage_root: at-epic\n"
            "approval_status: approved\n"
            "approval_source: operator\n"
            "approved_by: planner-user\n"
            "approved_at: 2026-03-29T12:00:00Z\n"
            "latest_verdict: REVISED\n"
        ),
    )

    class FakeStore:
        async def get_epic(self, epic_id):
            assert epic_id == "at-epic"
            from atelier.store import LifecycleStatus

            return SimpleNamespace(id=epic_id, lifecycle=LifecycleStatus.DEFERRED)

        async def list_changesets(self, query):
            del query
            from atelier.store import LifecycleStatus

            return (SimpleNamespace(id="at-epic.1", lifecycle=LifecycleStatus.CLOSED),)

        async def transition_lifecycle(self, request):
            transitions.append(request)
            return request

    class FakeClient:
        async def show(self, request):
            return {"at-epic": epic_issue, "at-epic.1": closed_child_issue}[request.issue_id]

    monkeypatch.setattr(
        module, "_build_store_and_client", lambda **_kwargs: (FakeStore(), FakeClient())
    )
    monkeypatch.setattr(sys, "argv", ["promote_epic.py", "--epic-id", "at-epic", "--yes"])

    module.main()

    assert [request.issue_id for request in transitions] == ["at-epic"]


def test_promote_epic_refinement_requires_ready_verdict_for_epic_only_execution(
    monkeypatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    module = _load_script_module()

    monkeypatch.setattr(
        module,
        "_resolve_context",
        lambda **_kwargs: (tmp_path / ".beads", tmp_path / "repo", None),
    )

    epic_issue = _issue(
        "at-epic",
        title="Epic",
        description=("changeset_strategy: Keep review scope small.\nrelated_context: at-context\n"),
        notes=(
            "planning_refinement.v1\n"
            "authoritative: true\n"
            "mode: requested\n"
            "required: true\n"
            "lineage_root: at-epic\n"
            "approval_status: approved\n"
            "approval_source: operator\n"
            "approved_by: planner-user\n"
            "approved_at: 2026-03-29T12:00:00Z\n"
            "latest_verdict: REVISED\n"
        ),
    )

    class FakeStore:
        async def get_epic(self, epic_id):
            assert epic_id == "at-epic"
            from atelier.store import LifecycleStatus

            return SimpleNamespace(id=epic_id, lifecycle=LifecycleStatus.DEFERRED)

        async def list_changesets(self, query):
            del query
            return ()

        async def transition_lifecycle(self, request):  # pragma: no cover - defensive
            raise AssertionError(request)

    class FakeClient:
        async def show(self, request):
            assert request.issue_id == "at-epic"
            return epic_issue

    monkeypatch.setattr(
        module, "_build_store_and_client", lambda **_kwargs: (FakeStore(), FakeClient())
    )
    monkeypatch.setattr(sys, "argv", ["promote_epic.py", "--epic-id", "at-epic"])

    with pytest.raises(SystemExit) as excinfo:
        module.main()

    assert excinfo.value.code == 1
    assert "at-epic: refinement_not_ready" in capsys.readouterr().err


def test_promote_epic_h1_integration_blocks_refined_epic_only_path(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    module = _load_script_module()
    refinement_notes = (
        "planning_refinement.v1\n"
        "authoritative: true\n"
        "mode: requested\n"
        "required: true\n"
        "lineage_root: at-epic\n"
        "approval_status: approved\n"
        "approval_source: operator\n"
        "approved_by: planner-user\n"
        "approved_at: 2026-03-29T12:00:00Z\n"
        "latest_verdict: REVISED\n"
    )
    client, store = make_store_for_backend(
        "in-memory",
        issues=(
            issue_builder.issue(
                "at-epic",
                title="Epic",
                issue_type="epic",
                status="deferred",
                labels=("at:epic",),
                description=(
                    "changeset_strategy: Keep review scope small.\n"
                    "related_context: at-context\n"
                    "promotion_note: ready for confirmation\n"
                ),
                acceptance_criteria="Acceptance text",
                extra_fields={"notes": refinement_notes},
            ),
        ),
    )

    monkeypatch.setattr(
        module,
        "_resolve_context",
        lambda **_kwargs: (tmp_path / ".beads", tmp_path / "repo", None),
    )
    monkeypatch.setattr(module, "_build_store_and_client", lambda **_kwargs: (store, client))
    monkeypatch.setattr(sys, "argv", ["promote_epic.py", "--epic-id", "at-epic"])

    with pytest.raises(SystemExit) as excinfo:
        module.main()

    assert excinfo.value.code == 1
    assert "at-epic: refinement_not_ready" in capsys.readouterr().err

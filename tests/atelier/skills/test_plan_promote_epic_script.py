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
    dependencies: tuple[str, ...] = (),
):
    return SimpleNamespace(
        id=issue_id,
        title=title,
        status=status,
        description=description,
        acceptance_criteria=acceptance,
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

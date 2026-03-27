from __future__ import annotations

import importlib.util
import json
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


def _valid_refined_contract_json() -> str:
    return json.dumps(
        {
            "objective": "Enforce fail-closed refined promotion gate",
            "non_goals": ["Do not alter non-refined promotion"],
            "acceptance_criteria": [
                {"statement": "Reject invalid refined payloads", "evidence": ["pytest"]}
            ],
            "scope": {
                "includes": ["plan-promote-epic"],
                "excludes": ["worker runtime redesign"],
            },
            "verification_plan": ["uv run pytest tests/atelier/skills -k refined -v"],
            "risks": [{"risk": "over-blocking", "mitigation": "refined-only checks"}],
            "escalation_conditions": ["validator disagreement"],
            "completion_definition": {
                "requires_terminal_pr_state": True,
                "allowed_terminal_pr_states": ["merged", "closed"],
                "allows_integrated_sha_proof": True,
                "allow_close_without_terminal_or_integrated_sha": False,
            },
        },
        separators=(",", ":"),
    )


def _refined_description(*, contract_json: str, stage: str = "planning_in_review") -> str:
    return (
        "related_context: at-context\n"
        "changeset_strategy: Keep review scope small.\n"
        "execution.strategy: refined\n"
        f"planning.stage: {stage}\n"
        f"planning.contract_json: {contract_json}\n"
    )


def test_promote_epic_blocks_refined_target_without_valid_contract(
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
        description=(
            "changeset_strategy: Keep review scope small.\n"
            "related_context: at-context\n"
            "promotion_note: ready for confirmation\n"
        ),
    )
    child_issue = _issue(
        "at-epic.1",
        title="Child",
        description=_refined_description(contract_json="{bad-json}"),
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
    assert "refined readiness failed" in capsys.readouterr().err


def test_promote_epic_records_refined_approval_metadata_for_child_changeset(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_script_module()
    transitions: list[object] = []
    created_messages: list[object] = []
    metadata_updates: dict[str, dict[str, str | None]] = {}

    monkeypatch.setattr(
        module,
        "_resolve_context",
        lambda **_kwargs: (tmp_path / ".beads", tmp_path / "repo", None),
    )
    monkeypatch.setenv("ATELIER_AGENT_ID", "atelier/planner/codex/p1")

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
        description=_refined_description(contract_json=_valid_refined_contract_json()),
        notes="child notes",
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

        async def create_message(self, request):
            created_messages.append(request)
            return SimpleNamespace(id="at-msg.1")

        async def append_notes(self, request):
            return request

        async def transition_lifecycle(self, request):
            transitions.append(request)
            return request

    class FakeClient:
        async def show(self, request):
            return {"at-epic": epic_issue, "at-epic.1": child_issue}[request.issue_id]

    def _record_metadata(
        *,
        client: object,
        issue_id: str,
        fields: dict[str, str],
    ) -> dict[str, object]:
        del client
        metadata_updates[issue_id] = fields
        return {"id": issue_id}

    monkeypatch.setattr(
        module, "_build_store_and_client", lambda **_kwargs: (FakeStore(), FakeClient())
    )
    monkeypatch.setattr(module, "_update_description_metadata_fields", _record_metadata)
    monkeypatch.setattr(sys, "argv", ["promote_epic.py", "--epic-id", "at-epic", "--yes"])

    module.main()

    assert [request.issue_id for request in transitions] == ["at-epic", "at-epic.1"]
    assert created_messages
    assert metadata_updates["at-epic.1"]["planning.stage"] == "approved"
    assert metadata_updates["at-epic.1"]["planning.approved_by"] == "atelier/planner/codex/p1"
    assert metadata_updates["at-epic.1"]["planning.approval_message_id"] == "at-msg.1"
    assert metadata_updates["at-epic.1"]["planning.approved_at"] is not None


def test_promote_epic_requires_explicit_operator_identity_for_refined_approval(
    monkeypatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    module = _load_script_module()
    transitions: list[object] = []
    created_messages: list[object] = []

    monkeypatch.setattr(
        module,
        "_resolve_context",
        lambda **_kwargs: (tmp_path / ".beads", tmp_path / "repo", None),
    )
    monkeypatch.delenv("ATELIER_AGENT_ID", raising=False)

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
        description=_refined_description(contract_json=_valid_refined_contract_json()),
        notes="child notes",
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

        async def create_message(self, request):
            created_messages.append(request)
            return SimpleNamespace(id="at-msg.1")

        async def append_notes(self, request):
            return request

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

    with pytest.raises(SystemExit) as excinfo:
        module.main()

    assert excinfo.value.code == 1
    assert "ATELIER_AGENT_ID must be set for refined approvals" in capsys.readouterr().err
    assert created_messages == []
    assert transitions == []


def test_promote_epic_does_not_transition_lifecycle_when_refined_approval_fails(
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
    monkeypatch.setenv("ATELIER_AGENT_ID", "atelier/planner/codex/p1")

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
        description=_refined_description(contract_json=_valid_refined_contract_json()),
        notes="child notes",
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

        async def create_message(self, request):
            del request
            return SimpleNamespace(id="at-msg.1")

        async def append_notes(self, request):
            del request
            return SimpleNamespace(id="at-note.1")

        async def transition_lifecycle(self, request):
            transitions.append(request)
            return request

    class FakeClient:
        async def show(self, request):
            return {"at-epic": epic_issue, "at-epic.1": child_issue}[request.issue_id]

    monkeypatch.setattr(
        module, "_build_store_and_client", lambda **_kwargs: (FakeStore(), FakeClient())
    )
    monkeypatch.setattr(
        module,
        "_update_description_metadata_fields",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("metadata update failed")),
    )
    monkeypatch.setattr(sys, "argv", ["promote_epic.py", "--epic-id", "at-epic", "--yes"])

    with pytest.raises(SystemExit) as excinfo:
        module.main()

    assert excinfo.value.code == 1
    assert "metadata update failed" in capsys.readouterr().err
    assert transitions == []


def test_promote_epic_records_refined_approval_metadata_for_epic_single_unit(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_script_module()
    created_messages: list[object] = []
    metadata_updates: dict[str, dict[str, str | None]] = {}

    monkeypatch.setattr(
        module,
        "_resolve_context",
        lambda **_kwargs: (tmp_path / ".beads", tmp_path / "repo", None),
    )
    monkeypatch.setenv("ATELIER_AGENT_ID", "atelier/planner/codex/p1")

    epic_issue = _issue(
        "at-epic",
        title="Epic",
        description=_refined_description(contract_json=_valid_refined_contract_json()),
        notes="epic notes",
    )

    class FakeStore:
        async def get_epic(self, epic_id):
            assert epic_id == "at-epic"
            from atelier.store import LifecycleStatus

            return SimpleNamespace(id=epic_id, lifecycle=LifecycleStatus.DEFERRED)

        async def list_changesets(self, query):
            del query
            return ()

        async def create_message(self, request):
            created_messages.append(request)
            return SimpleNamespace(id="at-msg.2")

        async def append_notes(self, request):
            return request

        async def transition_lifecycle(self, request):
            return request

    class FakeClient:
        async def show(self, request):
            assert request.issue_id == "at-epic"
            return epic_issue

    def _record_metadata(
        *,
        client: object,
        issue_id: str,
        fields: dict[str, str],
    ) -> dict[str, object]:
        del client
        metadata_updates[issue_id] = fields
        return {"id": issue_id}

    monkeypatch.setattr(
        module, "_build_store_and_client", lambda **_kwargs: (FakeStore(), FakeClient())
    )
    monkeypatch.setattr(module, "_update_description_metadata_fields", _record_metadata)
    monkeypatch.setattr(sys, "argv", ["promote_epic.py", "--epic-id", "at-epic", "--yes"])

    module.main()

    assert created_messages
    assert metadata_updates["at-epic"]["planning.stage"] == "approved"
    assert metadata_updates["at-epic"]["planning.approval_message_id"] == "at-msg.2"


def test_promote_epic_non_refined_changesets_do_not_write_refined_approval(
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
    )
    child_issue = _issue(
        "at-epic.1",
        title="Child",
        description="related_context: at-context\n",
        notes="child notes",
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

        async def create_message(self, request):  # pragma: no cover - defensive
            raise AssertionError(request)

        async def append_notes(self, request):  # pragma: no cover - defensive
            raise AssertionError(request)

        async def transition_lifecycle(self, request):
            transitions.append(request)
            return request

    class FakeClient:
        async def show(self, request):
            return {"at-epic": epic_issue, "at-epic.1": child_issue}[request.issue_id]

    monkeypatch.setattr(
        module, "_build_store_and_client", lambda **_kwargs: (FakeStore(), FakeClient())
    )
    monkeypatch.setattr(
        module,
        "_update_description_metadata_fields",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError((args, kwargs))),
    )
    monkeypatch.setattr(sys, "argv", ["promote_epic.py", "--epic-id", "at-epic", "--yes"])

    module.main()

    assert [request.issue_id for request in transitions] == ["at-epic", "at-epic.1"]


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

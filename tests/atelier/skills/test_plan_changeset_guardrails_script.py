from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_script_module():
    script_path = (
        Path(__file__).resolve().parents[3]
        / "src"
        / "atelier"
        / "skills"
        / "plan-changeset-guardrails"
        / "scripts"
        / "check_guardrails.py"
    )
    spec = importlib.util.spec_from_file_location("check_guardrails", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_evaluate_guardrails_accepts_single_unit_epic_path() -> None:
    module = _load_script_module()
    epic = {
        "id": "at-epic",
        "labels": ["at:epic", "at:changeset"],
        "description": "LOC estimate: 320",
    }

    report = module._evaluate_guardrails(
        epic_issue=epic,
        child_changesets=[],
        target_changesets=[epic],
    )

    assert "single-unit path" in str(report.path_summary)
    assert report.violations == []


def test_evaluate_guardrails_flags_one_child_without_rationale() -> None:
    module = _load_script_module()
    epic = {"id": "at-epic", "labels": ["at:epic"], "description": "Intent: ship parser update"}
    child = {"id": "at-epic.1", "labels": ["at:changeset"], "description": "LOC estimate: 210"}

    report = module._evaluate_guardrails(
        epic_issue=epic,
        child_changesets=[child],
        target_changesets=[child],
    )

    assert any("one-child anti-pattern" in item for item in report.violations)


def test_evaluate_guardrails_allows_one_child_with_rationale() -> None:
    module = _load_script_module()
    epic = {
        "id": "at-epic",
        "labels": ["at:epic"],
        "notes": "Decomposition rationale: split due to dependency sequencing.",
    }
    child = {"id": "at-epic.1", "labels": ["at:changeset"], "description": "LOC estimate: 260"}

    report = module._evaluate_guardrails(
        epic_issue=epic,
        child_changesets=[child],
        target_changesets=[child],
    )

    assert "with explicit rationale" in str(report.path_summary)
    assert not any("one-child anti-pattern" in item for item in report.violations)


def test_evaluate_guardrails_flags_large_changeset_without_approval() -> None:
    module = _load_script_module()
    child = {
        "id": "at-epic.1",
        "labels": ["at:changeset"],
        "description": "LOC estimate: 920\nGuardrails: data migration",
    }

    report = module._evaluate_guardrails(
        epic_issue=None,
        child_changesets=[],
        target_changesets=[child],
    )

    assert any("exceeds 800 without explicit approval" in item for item in report.violations)


def test_evaluate_guardrails_reports_multi_unit_decomposition() -> None:
    module = _load_script_module()
    epic = {"id": "at-epic", "labels": ["at:epic"]}
    children = [
        {"id": "at-epic.1", "labels": ["at:changeset"], "description": "LOC estimate: 220"},
        {"id": "at-epic.2", "labels": ["at:changeset"], "description": "LOC estimate: 240"},
    ]

    report = module._evaluate_guardrails(
        epic_issue=epic,
        child_changesets=children,
        target_changesets=children,
    )

    assert "multi-unit decomposition" in str(report.path_summary)
    assert report.violations == []

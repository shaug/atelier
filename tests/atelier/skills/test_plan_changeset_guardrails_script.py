from __future__ import annotations

import importlib.util
import subprocess
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


def _planner_contract_text() -> str:
    return (
        "intent: Prevent planner beads from losing execution context.\n"
        "rationale: Workers need stable scope and rationale before implementation.\n"
        "non_goals: Do not change publish or worker runtime behavior.\n"
        "constraints: Keep changesets reviewable and deterministic.\n"
        "edge_cases: Imported tickets may omit key worker-facing context.\n"
        "related_context: at-surch, at-ohj2."
    )


def test_evaluate_guardrails_accepts_single_unit_epic_path() -> None:
    module = _load_script_module()
    epic = {
        "id": "at-epic",
        "labels": ["at:epic"],
        "description": _planner_contract_text(),
        "notes": "LOC estimate: 320",
        "acceptance_criteria": "Done when planner beads expose executable worker context.",
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
    epic = {
        "id": "at-epic",
        "labels": ["at:epic"],
        "description": _planner_contract_text(),
        "acceptance_criteria": "Done when the executable path is actionable.",
    }
    child = {"id": "at-epic.1", "labels": [], "description": "LOC estimate: 210"}

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
        "description": _planner_contract_text(),
        "notes": "Decomposition rationale: split due to dependency sequencing.",
        "acceptance_criteria": "Done when the executable path is actionable.",
    }
    child = {"id": "at-epic.1", "labels": [], "description": "LOC estimate: 260"}

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
        "labels": [],
        "description": _planner_contract_text() + "\nLOC estimate: 920\nGuardrails: data migration",
        "acceptance_criteria": "Done when the large migration scope is fully documented.",
    }

    report = module._evaluate_guardrails(
        epic_issue=None,
        child_changesets=[],
        target_changesets=[child],
    )

    assert any("exceeds 800 without explicit approval" in item for item in report.violations)


def test_evaluate_guardrails_reports_multi_unit_decomposition() -> None:
    module = _load_script_module()
    epic = {
        "id": "at-epic",
        "labels": ["at:epic"],
        "description": _planner_contract_text(),
        "acceptance_criteria": "Done when each child changeset is actionable.",
    }
    children = [
        {"id": "at-epic.1", "labels": [], "description": "LOC estimate: 220"},
        {"id": "at-epic.2", "labels": [], "description": "LOC estimate: 240"},
    ]

    report = module._evaluate_guardrails(
        epic_issue=epic,
        child_changesets=children,
        target_changesets=children,
    )

    assert "multi-unit decomposition" in str(report.path_summary)
    assert report.violations == []


def test_evaluate_guardrails_flags_missing_authoring_contract_fields() -> None:
    module = _load_script_module()
    epic = {
        "id": "at-epic",
        "labels": ["at:epic"],
        "description": (
            "intent: Raise planner bead quality.\n"
            "rationale: Workers need better context.\n"
            "non_goals: Do not change promotion UX.\n"
            "constraints: Keep the change reviewable."
        ),
        "acceptance_criteria": "Done when missing context is caught before promotion.",
    }
    child = {"id": "at-epic.1", "labels": [], "description": "LOC estimate: 180"}

    report = module._evaluate_guardrails(
        epic_issue=epic,
        child_changesets=[child],
        target_changesets=[child],
    )

    assert any(
        "missing planner authoring contract fields (edge_cases, related_context)" in item
        for item in report.violations
    )


def test_evaluate_guardrails_flags_missing_done_definition() -> None:
    module = _load_script_module()
    child = {
        "id": "at-epic.1",
        "labels": [],
        "description": _planner_contract_text() + "\nLOC estimate: 180",
    }

    report = module._evaluate_guardrails(
        epic_issue=None,
        child_changesets=[],
        target_changesets=[child],
    )

    assert any("missing explicit done definition" in item for item in report.violations)


def test_evaluate_guardrails_accepts_block_style_edge_cases_in_design() -> None:
    module = _load_script_module()
    epic = {
        "id": "at-epic",
        "labels": ["at:epic"],
        "description": (
            "intent: Keep planner authoring validation deterministic.\n"
            "rationale: Valid planner fields should not be reported as missing.\n"
            "non_goals: Do not redesign planning workflows.\n"
            "constraints: Preserve explicit authoring rules and deterministic checks.\n"
            "related_context: plan-changeset-guardrails.\n"
            "done_definition: Done when valid planner beads no longer fail validation."
        ),
        "design": (
            "edge_cases:\n"
            "- duplicate fields across description and notes\n"
            "- block-style field values in structured planner docs"
        ),
        "notes": (
            "LOC estimate: 240\n"
            "Invariant impact map:\n"
            "- mutation entry points\n"
            "- recovery paths\n"
            "- external side-effect adapters\n"
            "Re-split triggers:\n"
            "- split if parser repair expands into broader planner-authoring redesign\n"
            "- split if review reveals a new concern domain beyond checker alignment\n"
            "Planner action on split:\n"
            "- capture deferred follow-on work immediately.\n"
            "Review scope growth guidance:\n"
            "- defer unrelated authoring-style cleanups."
        ),
    }

    report = module._evaluate_guardrails(
        epic_issue=epic,
        child_changesets=[],
        target_changesets=[epic],
    )

    assert not any(
        "missing planner authoring contract fields" in item for item in report.violations
    )


def test_evaluate_guardrails_accepts_bulleted_authoring_aliases_in_notes() -> None:
    module = _load_script_module()
    child = {
        "id": "at-epic.1",
        "labels": [],
        "notes": (
            "- intent: Normalize supported planner field variants.\n"
            "- rationale: Historic planner notes may use bullet-prefixed entries.\n"
            "- non-goal: Do not weaken the authoring rules.\n"
            "- constraint: Keep validation deterministic.\n"
            "- edge-case: Structured notes may carry the only executable context.\n"
            "- related-beads: at-e1yzp, at-k0ako.\n"
            "- success-definition: Done when bullet-prefixed aliases validate.\n"
            "LOC estimate: 180"
        ),
    }

    report = module._evaluate_guardrails(
        epic_issue=None,
        child_changesets=[],
        target_changesets=[child],
    )

    assert report.violations == []


def test_evaluate_guardrails_accepts_broad_redesign_resplit_trigger_wording() -> None:
    module = _load_script_module()
    epic = {
        "id": "at-epic",
        "labels": ["at:epic"],
        "title": "Fix planner guardrail literalism",
        "description": _planner_contract_text(),
        "notes": (
            "LOC estimate: 240\n"
            "Invariant impact map:\n"
            "- mutation entry points\n"
            "- recovery paths\n"
            "- external side-effect adapters\n"
            "Re-split triggers:\n"
            "- split if parser repair and planner-authoring contract normalization become "
            "separate review-sized concerns with independent tests.\n"
            "- split if the work expands into broad planner-skill redesign instead of "
            "checker/contract alignment.\n"
            "Planner action on split:\n"
            "- capture deferred follow-on work immediately.\n"
            "Review scope growth guidance:\n"
            "- defer unrelated authoring-style cleanups."
        ),
        "acceptance_criteria": "Done when valid guardrail notes no longer raise false negatives.",
    }

    report = module._evaluate_guardrails(
        epic_issue=epic,
        child_changesets=[],
        target_changesets=[epic],
    )

    assert not any("missing explicit re-split triggers" in item for item in report.violations)


def test_evaluate_guardrails_accepts_underscored_resplit_header_with_tilde_threshold() -> None:
    module = _load_script_module()
    epic = {
        "id": "at-epic",
        "labels": ["at:epic"],
        "title": "Align guardrail checker with authored planner notes",
        "description": _planner_contract_text(),
        "notes": (
            "LOC estimate: 320\n"
            "Invariant impact map:\n"
            "- mutation entry points\n"
            "- recovery paths\n"
            "- external side-effect adapters\n"
            "re_split_triggers:\n"
            "- threshold crossing: split if any active changeset trends above ~400 LOC\n"
            "- threshold crossing: split if review expands a changeset beyond its "
            "declared planner concern domain\n"
            "- new concern domain discovered during review: split if provider-boundary "
            "work or a new store semantic appears\n"
            "planner_action_on_resplit: create deferred follow-on changesets or stack "
            "extensions immediately and keep the active slice scoped.\n"
            "review_scope_growth_guidance: if review feedback uncovers a new planner "
            "concern domain, capture it as deferred follow-on work instead of widening "
            "the active changeset."
        ),
        "acceptance_criteria": "Done when authored re_split trigger notes no longer fail.",
    }

    report = module._evaluate_guardrails(
        epic_issue=epic,
        child_changesets=[],
        target_changesets=[epic],
    )

    assert not any("missing explicit re-split triggers" in item for item in report.violations)


def test_evaluate_guardrails_flags_cross_cutting_guardrail_gaps() -> None:
    module = _load_script_module()
    epic = {
        "id": "at-epic",
        "labels": ["at:epic"],
        "title": "Fix lifecycle invariant regression",
        "description": (
            _planner_contract_text()
            + "\nConcern domains: lifecycle state machine and external provider sync."
        ),
        "acceptance_criteria": "Done when lifecycle fixes are fully reviewable.",
    }
    children = [
        {"id": "at-epic.1", "labels": [], "description": "LOC estimate: 230"},
        {"id": "at-epic.2", "labels": [], "description": "LOC estimate: 260"},
    ]

    report = module._evaluate_guardrails(
        epic_issue=epic,
        child_changesets=children,
        target_changesets=children,
    )

    assert any("missing invariant impact map coverage" in item for item in report.violations)
    assert any("missing explicit re-split triggers" in item for item in report.violations)
    assert any("missing required planner action" in item for item in report.violations)
    assert any(
        "missing review-feedback scope-growth guidance" in item for item in report.violations
    )


def test_evaluate_guardrails_flags_cross_cutting_single_changeset_decomposition_gap() -> None:
    module = _load_script_module()
    epic = {
        "id": "at-epic",
        "labels": ["at:epic"],
        "title": "Fix lifecycle invariant regression",
        "notes": (
            _planner_contract_text() + "\n"
            "Decomposition rationale: split due to dependency sequencing.\n"
            "Invariant impact map:\n"
            "- mutation entry points\n"
            "- recovery paths\n"
            "- external side-effect adapters\n"
            "Re-split trigger: LOC threshold > 400 and new concern domain during review.\n"
            "Planner action: create deferred follow-on changeset or stack extension.\n"
            "Review feedback: scope expansion during review is captured immediately."
        ),
        "description": ("Concern domains: lifecycle state machine and external provider sync."),
        "acceptance_criteria": "Done when lifecycle fixes are fully reviewable.",
    }
    child = {"id": "at-epic.1", "labels": [], "description": "LOC estimate: 300"}

    report = module._evaluate_guardrails(
        epic_issue=epic,
        child_changesets=[child],
        target_changesets=[child],
    )

    assert any("without stacked decomposition" in item for item in report.violations)


def test_evaluate_guardrails_accepts_cross_cutting_guardrails_when_complete() -> None:
    module = _load_script_module()
    epic = {
        "id": "at-epic",
        "labels": ["at:epic"],
        "title": "Fix lifecycle invariant regression",
        "notes": (
            _planner_contract_text() + "\n"
            "Invariant impact map:\n"
            "- mutation entry points\n"
            "- recovery paths\n"
            "- external side-effect adapters\n"
            "Concern domains: lifecycle state machine, external provider sync, dry-run "
            "observability.\n"
            "Re-split trigger: LOC threshold > 400 and new concern domain during review.\n"
            "Planner action: create deferred follow-on changeset or stack extension.\n"
            "Review feedback: scope expansion during review is captured immediately."
        ),
        "acceptance_criteria": "Done when lifecycle fixes are fully reviewable.",
    }
    children = [
        {"id": "at-epic.1", "labels": [], "description": "LOC estimate: 230"},
        {"id": "at-epic.2", "labels": [], "description": "LOC estimate: 260"},
    ]

    report = module._evaluate_guardrails(
        epic_issue=epic,
        child_changesets=children,
        target_changesets=children,
    )

    assert report.violations == []


def test_evaluate_guardrails_detects_numeric_threshold_trigger_without_phrase() -> None:
    module = _load_script_module()
    epic = {
        "id": "at-epic",
        "labels": ["at:epic"],
        "title": "Fix lifecycle invariant regression",
        "notes": (
            _planner_contract_text() + "\n"
            "Invariant impact map:\n"
            "- mutation entry points\n"
            "- recovery paths\n"
            "- external side-effect adapters\n"
            "Concern domains: lifecycle state machine, external provider sync.\n"
            "Resplit criteria: LOC > 400 and new concern domain during review.\n"
            "Planner action: create deferred follow-on changeset or stack extension.\n"
            "Review feedback: scope expansion during review is captured immediately."
        ),
        "acceptance_criteria": "Done when lifecycle fixes are fully reviewable.",
    }
    children = [
        {"id": "at-epic.1", "labels": [], "description": "LOC estimate: 230"},
        {"id": "at-epic.2", "labels": [], "description": "LOC estimate: 260"},
    ]

    report = module._evaluate_guardrails(
        epic_issue=epic,
        child_changesets=children,
        target_changesets=children,
    )

    assert not any("missing explicit re-split triggers" in item for item in report.violations)


def test_matched_concern_domains_ignores_standalone_external_token() -> None:
    module = _load_script_module()
    text = (
        "This bug touches lifecycle state machine behavior and documents external "
        "side-effect adapters."
    )

    domains = module._matched_concern_domains(text)

    assert domains == ["lifecycle-state-machine"]


def test_run_bd_json_defaults_to_direct_mode(monkeypatch) -> None:
    module = _load_script_module()
    captured: dict[str, list[str]] = {}

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["command"] = command
        return subprocess.CompletedProcess(args=command, returncode=0, stdout="[]", stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    payload = module._run_bd_json(["list", "--json"], beads_dir=None)

    assert payload == []
    assert captured["command"] == ["bd", "list", "--json"]


def test_evaluate_guardrails_flags_refinement_contract_gaps() -> None:
    module = _load_script_module()
    child = {
        "id": "at-epic.1",
        "labels": [],
        "description": _planner_contract_text() + "\nLOC estimate: 220",
        "acceptance_criteria": "Done when refinement gaps are surfaced.",
        "notes": (
            "planning_refinement.v1\n"
            "authoritative: true\n"
            "mode: requested\n"
            "required: true\n"
            "lineage_root: at-epic\n"
            "approval_status: missing\n"
        ),
    }

    report = module._evaluate_guardrails(
        epic_issue=None,
        child_changesets=[],
        target_changesets=[child],
    )

    assert any("refinement evidence incomplete" in item for item in report.violations)


def test_evaluate_guardrails_accepts_complete_required_refinement_contract() -> None:
    module = _load_script_module()
    child = {
        "id": "at-epic.1",
        "labels": [],
        "description": _planner_contract_text() + "\nLOC estimate: 220",
        "acceptance_criteria": "Done when refinement contract checks pass.",
        "notes": (
            "planning_refinement.v1\n"
            "authoritative: true\n"
            "mode: requested\n"
            "required: true\n"
            "lineage_root: at-epic\n"
            "approval_status: approved\n"
            "approval_source: operator\n"
            "approved_by: planner-user\n"
            "approved_at: 2026-03-29T12:00:00Z\n"
            "latest_verdict: READY\n"
        ),
    }

    report = module._evaluate_guardrails(
        epic_issue=None,
        child_changesets=[],
        target_changesets=[child],
    )

    assert not any("refinement evidence incomplete" in item for item in report.violations)


def test_evaluate_guardrails_checks_required_refinement_when_notes_are_tuple() -> None:
    module = _load_script_module()
    child = {
        "id": "at-epic.1",
        "labels": [],
        "description": _planner_contract_text() + "\nLOC estimate: 220",
        "acceptance_criteria": "Done when tuple-backed notes are checked.",
        "notes": (
            "planning_refinement.v1",
            "authoritative: true",
            "mode: requested",
            "required: true",
            "lineage_root: at-epic",
            "approval_status: missing",
        ),
    }

    report = module._evaluate_guardrails(
        epic_issue=None,
        child_changesets=[],
        target_changesets=[child],
    )

    assert any("refinement evidence incomplete" in item for item in report.violations)

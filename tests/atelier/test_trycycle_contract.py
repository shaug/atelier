import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from atelier import trycycle_contract
from atelier.worker import work_startup_runtime


def _valid_contract_json(
    *,
    escalation_conditions: list[str] | None = None,
    acceptance_evidence: list[str] | None = None,
    completion_allow_unsafe_close: bool = False,
) -> str:
    escalation = (
        ["validator disagreement"] if escalation_conditions is None else escalation_conditions
    )
    evidence = ["tests"] if acceptance_evidence is None else acceptance_evidence
    return (
        '{"objective":"Ship fail-closed trycycle gating",'
        '"non_goals":["Do not alter non-trycycle flows"],'
        '"acceptance_criteria":[{"statement":"Gate invalid changesets","evidence":'
        f"{json.dumps(evidence)}"
        "}],"
        '"scope":{"includes":["worker startup"],"excludes":["CLI redesign"]},'
        '"verification_plan":["uv run pytest tests/atelier/worker/test_session_startup.py -v"],'
        '"risks":[{"risk":"Over-broad blocking","mitigation":"targeted-only gate"}],'
        f'"escalation_conditions":{json.dumps(escalation)},'
        '"completion_definition":{"requires_terminal_pr_state":true,'
        '"allowed_terminal_pr_states":["merged","closed"],'
        '"allows_integrated_sha_proof":true,'
        '"allow_close_without_terminal_or_integrated_sha":'
        f"{'true' if completion_allow_unsafe_close else 'false'}"
        "}}"
    )


def _load_guardrails_script_module():
    script_path = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "atelier"
        / "skills"
        / "plan-changeset-guardrails"
        / "scripts"
        / "check_guardrails.py"
    )
    spec = importlib.util.spec_from_file_location("check_guardrails_parity", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_promote_epic_script_module():
    script_path = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "atelier"
        / "skills"
        / "plan-promote-epic"
        / "scripts"
        / "promote_epic.py"
    )
    spec = importlib.util.spec_from_file_location("promote_epic_parity", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _planner_contract_text() -> str:
    return (
        "intent: Keep targeted startup selections fail-closed.\n"
        "rationale: Workers need deterministic claim eligibility.\n"
        "non_goals: Do not alter non-trycycle startup behavior.\n"
        "constraints: Preserve lifecycle invariants and explicit audits.\n"
        "edge_cases: Missing metadata must not silently bypass gates.\n"
        "related_context: at-719.\n"
        "LOC estimate: 220\n"
        "done_definition: Done when startup/promotion parity checks pass.\n"
    )


def _targeted_description(
    *,
    contract_json: str,
    stage: str,
    approved_by: str | None = None,
    approved_at: str | None = None,
    approval_message_id: str | None = None,
) -> str:
    lines = [
        "trycycle.targeted: true",
        f"trycycle.plan_stage: {stage}",
        f"trycycle.contract_json: {contract_json}",
    ]
    if approved_by is not None:
        lines.append(f"trycycle.approved_by: {approved_by}")
    if approved_at is not None:
        lines.append(f"trycycle.approved_at: {approved_at}")
    if approval_message_id is not None:
        lines.append(f"trycycle.approval_message_id: {approval_message_id}")
    return _planner_contract_text() + "\n".join(lines) + "\n"


def _guardrails_issue(issue_id: str, description: str) -> dict[str, object]:
    return {
        "id": issue_id,
        "title": issue_id,
        "description": description,
        "notes": "notes: parity harness",
        "acceptance_criteria": "Done when parity checks are deterministic.",
    }


def test_validate_contract_accepts_complete_payload() -> None:
    issue = {
        "description": (
            "trycycle.targeted: true\n"
            "trycycle.plan_stage: planning_in_review\n"
            f"trycycle.contract_json: {_valid_contract_json()}\n"
        )
    }

    result = trycycle_contract.evaluate_issue_trycycle_readiness(issue)

    assert result.ok is True
    assert result.targeted is True
    assert result.claim_eligible is False
    assert result.claim_blockers == (
        "targeted changesets require trycycle.plan_stage=approved before worker claim",
    )


def test_validate_contract_rejects_malformed_json() -> None:
    issue = {
        "description": (
            "trycycle.targeted: true\n"
            "trycycle.plan_stage: planning_in_review\n"
            "trycycle.contract_json: {not-json}\n"
        )
    }

    result = trycycle_contract.evaluate_issue_trycycle_readiness(issue)

    assert result.ok is False
    assert "trycycle.contract_json must be valid JSON" in result.summary


def test_validate_contract_rejects_missing_escalation_conditions() -> None:
    issue = {
        "description": (
            "trycycle.targeted: true\n"
            "trycycle.plan_stage: planning_in_review\n"
            f"trycycle.contract_json: {_valid_contract_json(escalation_conditions=[])}\n"
        )
    }

    result = trycycle_contract.evaluate_issue_trycycle_readiness(issue)

    assert result.ok is False
    assert "escalation_conditions" in result.summary


def test_validate_contract_rejects_non_testable_acceptance_criteria() -> None:
    issue = {
        "description": (
            "trycycle.targeted: true\n"
            "trycycle.plan_stage: planning_in_review\n"
            f"trycycle.contract_json: {_valid_contract_json(acceptance_evidence=[])}\n"
        )
    }

    result = trycycle_contract.evaluate_issue_trycycle_readiness(issue)

    assert result.ok is False
    assert "evidence" in result.summary


def test_validate_contract_rejects_completion_definition_conflicts() -> None:
    issue = {
        "description": (
            "trycycle.targeted: true\n"
            "trycycle.plan_stage: planning_in_review\n"
            "trycycle.contract_json: "
            f"{_valid_contract_json(completion_allow_unsafe_close=True)}\n"
        )
    }

    result = trycycle_contract.evaluate_issue_trycycle_readiness(issue)

    assert result.ok is False
    assert "completion_definition conflicts" in result.summary


def test_validate_contract_approved_stage_requires_full_evidence_fields() -> None:
    issue = {
        "description": (
            "trycycle.targeted: true\n"
            "trycycle.plan_stage: approved\n"
            f"trycycle.contract_json: {_valid_contract_json()}\n"
            "trycycle.approved_by: operator\n"
        )
    }

    result = trycycle_contract.evaluate_issue_trycycle_readiness(issue)

    assert result.ok is False
    assert "trycycle.approved_at" in result.summary
    assert "trycycle.approval_message_id" in result.summary


def test_validate_contract_rejects_malformed_approved_timestamp() -> None:
    issue = {
        "description": (
            "trycycle.targeted: true\n"
            "trycycle.plan_stage: approved\n"
            f"trycycle.contract_json: {_valid_contract_json()}\n"
            "trycycle.approved_by: atelier/planner/codex/p1\n"
            "trycycle.approved_at: yesterday\n"
            "trycycle.approval_message_id: at-msg.1\n"
        )
    }

    result = trycycle_contract.evaluate_issue_trycycle_readiness(issue)

    assert result.ok is False
    assert "trycycle.approved_at must be an ISO-8601 timestamp" in result.summary


def test_validate_contract_rejects_date_only_approved_timestamp() -> None:
    issue = {
        "description": (
            "trycycle.targeted: true\n"
            "trycycle.plan_stage: approved\n"
            f"trycycle.contract_json: {_valid_contract_json()}\n"
            "trycycle.approved_by: atelier/planner/codex/p1\n"
            "trycycle.approved_at: 2026-03-27\n"
            "trycycle.approval_message_id: at-msg.1\n"
        )
    }

    result = trycycle_contract.evaluate_issue_trycycle_readiness(issue)

    assert result.ok is False
    assert "trycycle.approved_at must be an ISO-8601 timestamp" in result.summary


def test_validate_contract_rejects_naive_approved_timestamp() -> None:
    issue = {
        "description": (
            "trycycle.targeted: true\n"
            "trycycle.plan_stage: approved\n"
            f"trycycle.contract_json: {_valid_contract_json()}\n"
            "trycycle.approved_by: atelier/planner/codex/p1\n"
            "trycycle.approved_at: 2026-03-27T01:00:00\n"
            "trycycle.approval_message_id: at-msg.1\n"
        )
    }

    result = trycycle_contract.evaluate_issue_trycycle_readiness(issue)

    assert result.ok is False
    assert "trycycle.approved_at must be an ISO-8601 timestamp" in result.summary


def test_validate_contract_rejects_malformed_approval_message_id() -> None:
    issue = {
        "description": (
            "trycycle.targeted: true\n"
            "trycycle.plan_stage: approved\n"
            f"trycycle.contract_json: {_valid_contract_json()}\n"
            "trycycle.approved_by: atelier/planner/codex/p1\n"
            "trycycle.approved_at: 2026-03-27T01:00:00Z\n"
            "trycycle.approval_message_id: bad id\n"
        )
    }

    result = trycycle_contract.evaluate_issue_trycycle_readiness(issue)

    assert result.ok is False
    assert "trycycle.approval_message_id must be an identifier" in result.summary


def test_trycycle_readiness_parity_across_entrypoints() -> None:
    guardrails = _load_guardrails_script_module()
    promote_epic = _load_promote_epic_script_module()
    worker_service = work_startup_runtime._StartupContractService(  # pyright: ignore[reportPrivateUsage]
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
    )

    conflict_payload = json.loads(_valid_contract_json())
    conflict_payload["completion_definition"]["allow_close_without_terminal_or_integrated_sha"] = (
        True
    )
    cases = (
        (
            "valid_approved",
            _targeted_description(
                contract_json=_valid_contract_json(),
                stage="approved",
                approved_by="atelier/planner/codex/p1",
                approved_at="2026-03-27T01:00:00Z",
                approval_message_id="at-msg.1",
            ),
        ),
        (
            "valid_unapproved",
            _targeted_description(
                contract_json=_valid_contract_json(),
                stage="planning_in_review",
            ),
        ),
        (
            "malformed_json",
            _targeted_description(
                contract_json="{bad-json}",
                stage="planning_in_review",
            ),
        ),
        (
            "missing_contract",
            _planner_contract_text()
            + "trycycle.targeted: true\ntrycycle.plan_stage: planning_in_review\n",
        ),
        (
            "completion_conflict",
            _targeted_description(
                contract_json=json.dumps(conflict_payload, separators=(",", ":")),
                stage="planning_in_review",
            ),
        ),
    )

    for label, description in cases:
        issue_id = f"at-parity.{label}"
        issue_payload = {"id": issue_id, "description": description}
        readiness = trycycle_contract.evaluate_issue_trycycle_readiness(issue_payload)
        promotion_error = promote_epic._trycycle_validation_error(  # pyright: ignore[reportPrivateUsage]
            SimpleNamespace(id=issue_id, description=description)
        )
        worker_eligible, worker_reason = worker_service.trycycle_claim_eligible(issue_payload)
        report = guardrails._evaluate_guardrails(  # pyright: ignore[reportPrivateUsage]
            epic_issue=None,
            child_changesets=[],
            target_changesets=[_guardrails_issue(issue_id, description)],
        )
        trycycle_violations = tuple(
            violation
            for violation in report.violations
            if violation.startswith(f"{issue_id}:")
            and ("trycycle." in violation or "completion_definition conflicts" in violation)
        )

        assert (promotion_error is None) is readiness.ok
        assert worker_eligible is readiness.claim_eligible
        if not worker_eligible:
            assert worker_reason is not None
        if readiness.ok and readiness.stage == "planning_in_review":
            assert trycycle_violations == ()
        elif readiness.ok and readiness.stage == "approved":
            assert any("planning_in_review" in violation for violation in trycycle_violations)
        else:
            assert trycycle_violations

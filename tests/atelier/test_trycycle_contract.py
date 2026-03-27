import json

from atelier import trycycle_contract


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

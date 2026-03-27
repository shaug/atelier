"""Trycycle planner/worker contract models and readiness validators."""

from __future__ import annotations

import datetime as dt
import json
import re
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from . import beads

_TARGETED_FIELD = "trycycle.targeted"
_CONTRACT_JSON_FIELD = "trycycle.contract_json"
_PLAN_STAGE_FIELD = "trycycle.plan_stage"
_APPROVED_BY_FIELD = "trycycle.approved_by"
_APPROVED_AT_FIELD = "trycycle.approved_at"
_APPROVAL_MESSAGE_ID_FIELD = "trycycle.approval_message_id"
_APPROVAL_MESSAGE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._:-]*$")
_PLANNING_IN_REVIEW = "planning_in_review"
_APPROVED = "approved"


class AcceptanceCriterion(BaseModel):
    """One measurable acceptance criterion for trycycle planning."""

    model_config = ConfigDict(extra="forbid")

    statement: str = Field(min_length=1)
    evidence: tuple[str, ...] = Field(min_length=1)

    @field_validator("statement")
    @classmethod
    def _validate_statement(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("statement must be non-empty")
        return cleaned

    @field_validator("evidence")
    @classmethod
    def _validate_evidence(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(item.strip() for item in value if item.strip())
        if not cleaned:
            raise ValueError("evidence must include at least one testable artifact")
        return cleaned


class ScopeBoundary(BaseModel):
    """Contract scope boundary describing included/excluded surfaces."""

    model_config = ConfigDict(extra="forbid")

    includes: tuple[str, ...] = Field(min_length=1)
    excludes: tuple[str, ...] = Field(min_length=1)

    @field_validator("includes", "excludes")
    @classmethod
    def _validate_lines(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(item.strip() for item in value if item.strip())
        if not cleaned:
            raise ValueError("scope boundaries must include non-empty entries")
        return cleaned


class RiskItem(BaseModel):
    """Risk statement and mitigation plan."""

    model_config = ConfigDict(extra="forbid")

    risk: str = Field(min_length=1)
    mitigation: str = Field(min_length=1)

    @field_validator("risk", "mitigation")
    @classmethod
    def _validate_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("risk and mitigation fields must be non-empty")
        return cleaned


class CompletionDefinition(BaseModel):
    """Completion-rule configuration constrained by worker finalize semantics."""

    model_config = ConfigDict(extra="forbid")

    requires_terminal_pr_state: bool = True
    allowed_terminal_pr_states: tuple[Literal["merged", "closed"], ...] = ("merged", "closed")
    allows_integrated_sha_proof: bool = True
    allow_close_without_terminal_or_integrated_sha: bool = False

    @field_validator("allowed_terminal_pr_states")
    @classmethod
    def _validate_terminal_states(
        cls,
        value: tuple[Literal["merged", "closed"], ...],
    ) -> tuple[Literal["merged", "closed"], ...]:
        if not value:
            raise ValueError("allowed_terminal_pr_states must not be empty")
        return value


class TrycycleContract(BaseModel):
    """Typed trycycle contract payload stored under ``trycycle.contract_json``."""

    model_config = ConfigDict(extra="forbid")

    objective: str = Field(min_length=1)
    non_goals: tuple[str, ...] = Field(min_length=1)
    acceptance_criteria: tuple[AcceptanceCriterion, ...] = Field(min_length=1)
    scope: ScopeBoundary
    verification_plan: tuple[str, ...] = Field(min_length=1)
    risks: tuple[RiskItem, ...] = Field(min_length=1)
    escalation_conditions: tuple[str, ...] = Field(min_length=1)
    completion_definition: CompletionDefinition

    @field_validator("objective")
    @classmethod
    def _validate_objective(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("objective must be non-empty")
        return cleaned

    @field_validator("non_goals", "verification_plan", "escalation_conditions")
    @classmethod
    def _validate_text_arrays(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(item.strip() for item in value if item.strip())
        if not cleaned:
            raise ValueError("list fields must include at least one non-empty item")
        return cleaned


class ReadinessResult(BaseModel):
    """Structured readiness evaluation outcome for one issue payload."""

    model_config = ConfigDict(frozen=True)

    targeted: bool
    contract_present: bool
    stage: str | None
    ok: bool
    approved: bool
    claim_eligible: bool
    errors: tuple[str, ...]
    claim_blockers: tuple[str, ...]

    @property
    def summary(self) -> str:
        """Return deterministic human-readable readiness diagnostics."""

        diagnostics: list[str] = list(self.errors)
        diagnostics.extend(blocker for blocker in self.claim_blockers if blocker not in diagnostics)
        return "; ".join(diagnostics)


def parse_contract_json(raw_contract_json: str) -> TrycycleContract:
    """Parse and validate a serialized ``trycycle.contract_json`` payload.

    Args:
        raw_contract_json: Raw JSON string captured in issue metadata.

    Returns:
        Parsed and validated ``TrycycleContract`` model.

    Raises:
        ValueError: Raised when JSON is malformed or schema validation fails.
    """

    try:
        payload = json.loads(raw_contract_json)
    except json.JSONDecodeError as exc:  # pragma: no cover - exercised via wrapper path
        raise ValueError("trycycle.contract_json must be valid JSON") from exc
    try:
        return TrycycleContract.model_validate(payload)
    except ValidationError as exc:  # pragma: no cover - exercised via wrapper path
        first_error = exc.errors(include_url=False)[0]
        location = ".".join(str(part) for part in first_error.get("loc", ()) if part is not None)
        detail = first_error.get("msg", "invalid contract payload")
        if location:
            raise ValueError(f"trycycle.contract_json invalid at {location}: {detail}") from exc
        raise ValueError(f"trycycle.contract_json invalid: {detail}") from exc


def serialize_contract(contract: TrycycleContract) -> str:
    """Serialize a validated contract for deterministic metadata persistence.

    Args:
        contract: Contract model to serialize.

    Returns:
        JSON string sorted by key for stable audits.
    """

    return json.dumps(contract.model_dump(mode="json"), separators=(",", ":"), sort_keys=True)


def evaluate_issue_trycycle_readiness(issue: Mapping[str, object]) -> ReadinessResult:
    """Evaluate planner/worker trycycle readiness for one issue payload.

    Args:
        issue: Issue-like mapping containing at least an optional description.

    Returns:
        Structured readiness with deterministic validation diagnostics.
    """

    description = issue.get("description")
    fields = beads.parse_description_fields(description if isinstance(description, str) else "")
    targeted = _parse_bool(fields.get(_TARGETED_FIELD))
    if not targeted:
        return ReadinessResult(
            targeted=False,
            contract_present=False,
            stage=None,
            ok=True,
            approved=False,
            claim_eligible=True,
            errors=(),
            claim_blockers=(),
        )

    errors: list[str] = []
    claim_blockers: list[str] = []

    stage_raw = fields.get(_PLAN_STAGE_FIELD)
    stage = _normalize_field(stage_raw)
    if stage not in {_PLANNING_IN_REVIEW, _APPROVED}:
        errors.append(
            "targeted changesets require trycycle.plan_stage set to "
            "'planning_in_review' or 'approved'"
        )

    contract_raw = fields.get(_CONTRACT_JSON_FIELD)
    contract_text = contract_raw.strip() if isinstance(contract_raw, str) else ""
    contract_present = bool(contract_text)
    contract: TrycycleContract | None = None
    if not contract_present:
        errors.append("targeted changesets require trycycle.contract_json")
    else:
        try:
            contract = parse_contract_json(contract_text)
        except ValueError as exc:
            errors.append(str(exc))
    if contract is not None:
        errors.extend(_completion_definition_conflicts(contract.completion_definition))

    approved = stage == _APPROVED
    if approved:
        approval_errors = _approval_errors(fields)
        errors.extend(approval_errors)
    else:
        claim_blockers.append(
            "targeted changesets require trycycle.plan_stage=approved before worker claim"
        )

    ok = not errors
    claim_eligible = ok and approved
    if not claim_eligible and approved and errors:
        claim_blockers.extend(errors)

    return ReadinessResult(
        targeted=True,
        contract_present=contract_present,
        stage=stage,
        ok=ok,
        approved=approved,
        claim_eligible=claim_eligible,
        errors=tuple(errors),
        claim_blockers=tuple(dict.fromkeys(claim_blockers)),
    )


def trycycle_claim_eligible(issue: Mapping[str, object]) -> tuple[bool, str | None]:
    """Return worker-claim eligibility and rejection reason for one issue.

    Args:
        issue: Issue payload to evaluate.

    Returns:
        Tuple ``(eligible, reason)`` where reason is populated only for blocked
        trycycle-targeted changesets.
    """

    readiness = evaluate_issue_trycycle_readiness(issue)
    if not readiness.targeted or readiness.claim_eligible:
        return True, None
    reason = readiness.summary or "targeted changeset is not claim-eligible"
    return False, reason


def approval_evidence_summary(issue: Mapping[str, object]) -> str:
    """Render a concise audit summary for persisted approval metadata.

    Args:
        issue: Issue payload that may contain trycycle approval metadata fields.

    Returns:
        Human-readable approval evidence summary string.
    """

    description = issue.get("description")
    fields = beads.parse_description_fields(description if isinstance(description, str) else "")
    parts = [
        f"stage={_normalize_field(fields.get(_PLAN_STAGE_FIELD)) or '(missing)'}",
        f"approved_by={_normalize_field(fields.get(_APPROVED_BY_FIELD)) or '(missing)'}",
        f"approved_at={_normalize_field(fields.get(_APPROVED_AT_FIELD)) or '(missing)'}",
        "approval_message_id="
        f"{_normalize_field(fields.get(_APPROVAL_MESSAGE_ID_FIELD)) or '(missing)'}",
    ]
    return "trycycle approval evidence: " + ", ".join(parts)


def _parse_bool(raw: str | None) -> bool:
    value = _normalize_field(raw)
    if value is None:
        return False
    return value in {"1", "true", "yes", "on"}


def _normalize_field(raw: str | None) -> str | None:
    if raw is None:
        return None
    cleaned = raw.strip().lower()
    if not cleaned or cleaned == "null":
        return None
    return cleaned


def _approval_errors(fields: Mapping[str, str]) -> list[str]:
    errors: list[str] = []
    approved_by = _normalize_field(fields.get(_APPROVED_BY_FIELD))
    if approved_by is None:
        errors.append("approved stage requires trycycle.approved_by")
    approved_at_raw = _normalize_field(fields.get(_APPROVED_AT_FIELD))
    if approved_at_raw is None:
        errors.append("approved stage requires trycycle.approved_at")
    elif not _is_valid_iso_timestamp(approved_at_raw):
        errors.append("trycycle.approved_at must be an ISO-8601 timestamp")
    approval_message_id = _normalize_field(fields.get(_APPROVAL_MESSAGE_ID_FIELD))
    if approval_message_id is None:
        errors.append("approved stage requires trycycle.approval_message_id")
    elif not _APPROVAL_MESSAGE_ID_PATTERN.fullmatch(approval_message_id):
        errors.append("trycycle.approval_message_id must be an identifier")
    return errors


def _is_valid_iso_timestamp(value: str) -> bool:
    try:
        dt.datetime.fromisoformat(value.replace("z", "+00:00"))
    except ValueError:
        return False
    return True


def _completion_definition_conflicts(definition: CompletionDefinition) -> list[str]:
    conflicts: list[str] = []
    if definition.allow_close_without_terminal_or_integrated_sha:
        conflicts.append(
            "completion_definition conflicts with lifecycle finalize semantics: close without "
            "terminal PR state or integrated SHA proof is not allowed"
        )
    if not definition.requires_terminal_pr_state and not definition.allows_integrated_sha_proof:
        conflicts.append(
            "completion_definition must require terminal PR state or integrated SHA proof"
        )
    if definition.requires_terminal_pr_state and not definition.allowed_terminal_pr_states:
        conflicts.append("completion_definition requires non-empty terminal PR states")
    return conflicts


__all__ = [
    "AcceptanceCriterion",
    "CompletionDefinition",
    "ReadinessResult",
    "RiskItem",
    "ScopeBoundary",
    "TrycycleContract",
    "approval_evidence_summary",
    "evaluate_issue_trycycle_readiness",
    "parse_contract_json",
    "serialize_contract",
    "trycycle_claim_eligible",
]

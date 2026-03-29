"""Utilities for planning refinement note artifacts.

This module parses ``planning_refinement.v1`` note blocks, selects the winning
artifact according to authoritative precedence rules, and evaluates claim-gate
readiness for refined work.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

DEFAULT_PLAN_EDIT_ROUNDS_MAX: Final[int] = 5
DEFAULT_POST_IMPL_REVIEW_ROUNDS_MAX: Final[int] = 8
_REFINEMENT_MARKER: Final[str] = "planning_refinement.v1"
_TRUE_TOKENS: Final[frozenset[str]] = frozenset({"true", "1", "yes"})
_FALSE_TOKENS: Final[frozenset[str]] = frozenset({"false", "0", "no"})

RefinementMode = Literal["requested", "inherited", "project_policy"]
ApprovalStatus = Literal["approved", "missing"]
ApprovalSource = Literal["project_policy", "operator"]
RefinementVerdict = Literal["READY", "REVISED", "USER_DECISION_REQUIRED"]


class PlanningRefinementRecord(BaseModel):
    """Structured ``planning_refinement.v1`` note payload.

    Attributes:
        authoritative: Whether this block is authoritative.
        mode: How refinement was activated.
        required: Whether refinement is required for claimability.
        lineage_root: Origin work item id for inherited lineage.
        approval_status: Approval state for required refinement.
        approval_source: Approval source when approved.
        approved_by: Principal id that approved refinement.
        approved_at: Approval timestamp.
        plan_edit_rounds_max: Maximum refinement edit rounds.
        post_impl_review_rounds_max: Maximum post-implementation review rounds.
        plan_edit_rounds_used: Refinement rounds already consumed.
        latest_verdict: Most recent refinement verdict.
        initial_plan_path: First plan artifact path.
        latest_plan_path: Latest plan artifact path.
        round_log_dir: Round artifact directory path.
    """

    model_config = ConfigDict(extra="forbid")

    authoritative: bool = False
    mode: RefinementMode = "requested"
    required: bool = False
    lineage_root: str | None = None
    approval_status: ApprovalStatus = "missing"
    approval_source: ApprovalSource | None = None
    approved_by: str | None = None
    approved_at: str | None = None
    plan_edit_rounds_max: int = DEFAULT_PLAN_EDIT_ROUNDS_MAX
    post_impl_review_rounds_max: int = DEFAULT_POST_IMPL_REVIEW_ROUNDS_MAX
    plan_edit_rounds_used: int | None = None
    latest_verdict: RefinementVerdict | None = None
    initial_plan_path: str | None = None
    latest_plan_path: str | None = None
    round_log_dir: str | None = None

    @field_validator("authoritative", "required", mode="before")
    @classmethod
    def _normalize_bool_fields(cls, value: object) -> object:
        parsed = _parse_bool_token(value)
        if parsed is None:
            return value
        return parsed

    @field_validator("mode", mode="before")
    @classmethod
    def _normalize_mode(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().lower()
        return value

    @field_validator("approval_status", mode="before")
    @classmethod
    def _normalize_approval_status(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().lower()
        return value

    @field_validator("approval_source", mode="before")
    @classmethod
    def _normalize_approval_source(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip().lower()
            return normalized or None
        return value

    @field_validator("latest_verdict", mode="before")
    @classmethod
    def _normalize_latest_verdict(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip().upper()
            return normalized or None
        return value

    @field_validator(
        "plan_edit_rounds_max",
        "post_impl_review_rounds_max",
        "plan_edit_rounds_used",
        mode="before",
    )
    @classmethod
    def _normalize_ints(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.isdigit():
                return int(stripped)
        return value

    @field_validator("plan_edit_rounds_max", "post_impl_review_rounds_max")
    @classmethod
    def _validate_round_limits(cls, value: int) -> int:
        if value < 1 or value > 64:
            raise ValueError("round limits must be between 1 and 64")
        return value

    @field_validator("plan_edit_rounds_used")
    @classmethod
    def _validate_rounds_used(cls, value: int | None) -> int | None:
        if value is None:
            return None
        if value < 0:
            raise ValueError("plan_edit_rounds_used must be >= 0")
        return value


@dataclass(frozen=True)
class ParsedRefinementBlock:
    """One parsed refinement block extracted from notes.

    Attributes:
        ordinal: 0-based block index in appearance order.
        raw_text: Original block text.
        field_map: Parsed key/value map from the block.
        record: Validated record when parsing succeeded.
        errors: Validation or syntax errors for malformed blocks.
        authoritative_hint: Parsed authoritative flag when present.
        required_hint: Parsed required flag when present.
    """

    ordinal: int
    raw_text: str
    field_map: dict[str, str]
    record: PlanningRefinementRecord | None
    errors: tuple[str, ...]
    authoritative_hint: bool
    required_hint: bool

    @property
    def is_valid(self) -> bool:
        """Return whether this block parsed into a valid record."""
        return self.record is not None


@dataclass(frozen=True)
class RefinementClaimGateDecision:
    """Claim-gate evaluation outcome for refinement requirements.

    Attributes:
        required: Whether refinement requirements are active in scope.
        claimable: Whether the work item is claimable.
        reason: Deterministic rejection reason when unclaimable.
        selected: Winning refinement record when available.
    """

    required: bool
    claimable: bool
    reason: str | None
    selected: PlanningRefinementRecord | None


def parse_refinement_blocks(notes: str | None) -> tuple[ParsedRefinementBlock, ...]:
    """Parse all ``planning_refinement.v1`` blocks from note text.

    Args:
        notes: Notes text containing zero or more refinement blocks.

    Returns:
        Parsed blocks in source order.
    """
    if not notes:
        return tuple()

    lines = notes.splitlines()
    blocks: list[ParsedRefinementBlock] = []
    index = 0
    ordinal = 0
    while index < len(lines):
        if lines[index].strip() != _REFINEMENT_MARKER:
            index += 1
            continue
        start = index
        index += 1
        while index < len(lines) and lines[index].strip() != _REFINEMENT_MARKER:
            index += 1
        raw_lines = lines[start:index]
        raw_text = "\n".join(raw_lines)
        field_map, syntax_errors = _parse_field_map(raw_lines[1:])
        authoritative_hint = _parse_bool_token(field_map.get("authoritative")) is True
        required_hint = _parse_bool_token(field_map.get("required")) is True
        record: PlanningRefinementRecord | None = None
        errors = list(syntax_errors)
        if not errors:
            try:
                record = PlanningRefinementRecord.model_validate(field_map)
            except ValidationError as exc:
                errors.append(str(exc))
        blocks.append(
            ParsedRefinementBlock(
                ordinal=ordinal,
                raw_text=raw_text,
                field_map=field_map,
                record=record,
                errors=tuple(errors),
                authoritative_hint=authoritative_hint,
                required_hint=required_hint,
            )
        )
        ordinal += 1
    return tuple(blocks)


def select_winning_refinement(
    blocks: tuple[ParsedRefinementBlock, ...] | list[ParsedRefinementBlock],
) -> PlanningRefinementRecord | None:
    """Select the winning refinement record from parsed blocks.

    Selection is newest authoritative valid block when authoritative blocks
    exist; otherwise newest valid block across all parsed blocks.

    Args:
        blocks: Parsed refinement blocks.

    Returns:
        Winning valid refinement record, or ``None`` when no valid winner
        exists.
    """
    scope = _select_scope(tuple(blocks))
    for block in reversed(scope):
        if block.record is not None:
            return block.record
    return None


def evaluate_refinement_claim_gate(notes: str | None) -> RefinementClaimGateDecision:
    """Evaluate whether refinement requirements permit worker claim.

    Args:
        notes: Work-item notes text.

    Returns:
        Claim-gate decision with deterministic reason tokens when unclaimable.
    """
    blocks = parse_refinement_blocks(notes)
    scope = _select_scope(blocks)
    required = any(block.required_hint for block in scope)
    selected = select_winning_refinement(blocks)
    if not required:
        return RefinementClaimGateDecision(
            required=False,
            claimable=True,
            reason=None,
            selected=selected,
        )
    if selected is None:
        return RefinementClaimGateDecision(
            required=True,
            claimable=False,
            reason="refinement_metadata_missing_or_malformed",
            selected=None,
        )
    if selected.approval_status != "approved":
        return RefinementClaimGateDecision(
            required=True,
            claimable=False,
            reason="refinement_approval_missing",
            selected=selected,
        )
    if selected.latest_verdict != "READY":
        return RefinementClaimGateDecision(
            required=True,
            claimable=False,
            reason="refinement_not_ready",
            selected=selected,
        )
    return RefinementClaimGateDecision(
        required=True,
        claimable=True,
        reason=None,
        selected=selected,
    )


def _select_scope(blocks: tuple[ParsedRefinementBlock, ...]) -> tuple[ParsedRefinementBlock, ...]:
    authoritative = tuple(block for block in blocks if block.authoritative_hint)
    if authoritative:
        return authoritative
    return blocks


def _parse_field_map(lines: list[str]) -> tuple[dict[str, str], tuple[str, ...]]:
    field_map: dict[str, str] = {}
    errors: list[str] = []
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        if ":" not in line:
            errors.append(f"invalid line without key/value separator: {raw_line!r}")
            continue
        key, value = line.split(":", 1)
        field_map[key.strip()] = value.strip()
    return field_map, tuple(errors)


def _parse_bool_token(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in _TRUE_TOKENS:
            return True
        if normalized in _FALSE_TOKENS:
            return False
    return None


__all__ = [
    "DEFAULT_PLAN_EDIT_ROUNDS_MAX",
    "DEFAULT_POST_IMPL_REVIEW_ROUNDS_MAX",
    "ApprovalSource",
    "ApprovalStatus",
    "ParsedRefinementBlock",
    "PlanningRefinementRecord",
    "RefinementClaimGateDecision",
    "RefinementMode",
    "RefinementVerdict",
    "evaluate_refinement_claim_gate",
    "parse_refinement_blocks",
    "select_winning_refinement",
]

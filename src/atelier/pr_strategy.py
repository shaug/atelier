"""Sequential PR policy normalization and gating decisions."""

from __future__ import annotations

from dataclasses import dataclass

from . import lifecycle

_SEQUENTIAL_POLICY_VALUES = ("sequential",)
_LEGACY_POLICY_ALIASES = (
    "on-ready",
    "on-parent-approved",
    "parallel",
)


def normalize_pr_strategy(value: object) -> str:
    """Normalize PR strategy values to the sequential-only policy.

    Legacy strategy values are accepted and coerced to ``"sequential"`` to
    keep existing project metadata deterministic after policy migration.
    """
    if value is None:
        return "sequential"
    if isinstance(value, str):
        normalized = value.strip().lower().replace("_", "-")
        if not normalized:
            return "sequential"
        if normalized in _SEQUENTIAL_POLICY_VALUES or normalized in _LEGACY_POLICY_ALIASES:
            return "sequential"
    raise ValueError("pr_strategy must be one of: " + ", ".join(_SEQUENTIAL_POLICY_VALUES))


@dataclass(frozen=True)
class PrCreationDecision:
    """Decision for whether a PR may be created under sequential policy."""

    parent_state: str | None
    allow_pr: bool
    reason: str


def pr_creation_decision(*, parent_state: str | None) -> PrCreationDecision:
    """Return the PR creation decision for the sequential-only policy."""
    parent_state_normalized = None
    if isinstance(parent_state, str):
        parent_state_normalized = parent_state.strip().lower() or None

    if parent_state_normalized is None:
        return PrCreationDecision(
            parent_state=None,
            allow_pr=True,
            reason="no-parent",
        )
    if lifecycle.is_integrated_review_state(parent_state_normalized):
        return PrCreationDecision(
            parent_state=parent_state_normalized,
            allow_pr=True,
            reason=f"parent:{parent_state_normalized}",
        )
    return PrCreationDecision(
        parent_state=parent_state_normalized,
        allow_pr=False,
        reason=f"blocked:{parent_state_normalized}",
    )

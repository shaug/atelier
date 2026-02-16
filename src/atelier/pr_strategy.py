"""PR strategy normalization and gating decisions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

PR_STRATEGY_VALUES = ("sequential", "on-ready", "parallel")
PrStrategy = Literal["sequential", "on-ready", "parallel"]

PR_STRATEGY_DEFAULT: PrStrategy = "sequential"


def normalize_pr_strategy(value: object) -> PrStrategy:
    """Normalize a PR strategy value or raise ``ValueError``."""
    if value is None:
        return PR_STRATEGY_DEFAULT
    if isinstance(value, str):
        normalized = value.strip().lower().replace("_", "-")
        if not normalized:
            return PR_STRATEGY_DEFAULT
        if normalized in PR_STRATEGY_VALUES:
            return normalized  # type: ignore[return-value]
    raise ValueError("pr_strategy must be one of: " + ", ".join(PR_STRATEGY_VALUES))


@dataclass(frozen=True)
class PrStrategyDecision:
    """Decision for whether a PR may be created under a strategy."""

    strategy: PrStrategy
    parent_state: str | None
    allow_pr: bool
    reason: str


def pr_strategy_decision(
    strategy: object, *, parent_state: str | None
) -> PrStrategyDecision:
    """Return the PR creation decision for a strategy."""
    normalized = normalize_pr_strategy(strategy)
    if normalized in {"parallel", "on-ready"}:
        return PrStrategyDecision(
            strategy=normalized,
            parent_state=parent_state,
            allow_pr=True,
            reason=f"strategy:{normalized}",
        )

    parent_state_normalized = None
    if isinstance(parent_state, str):
        parent_state_normalized = parent_state.strip().lower() or None

    if parent_state_normalized is None:
        return PrStrategyDecision(
            strategy=normalized,
            parent_state=None,
            allow_pr=True,
            reason="no-parent",
        )
    if parent_state_normalized in {"merged", "closed"}:
        return PrStrategyDecision(
            strategy=normalized,
            parent_state=parent_state_normalized,
            allow_pr=True,
            reason=f"parent:{parent_state_normalized}",
        )
    return PrStrategyDecision(
        strategy=normalized,
        parent_state=parent_state_normalized,
        allow_pr=False,
        reason=f"blocked:{parent_state_normalized}",
    )

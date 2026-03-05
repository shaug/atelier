"""Legacy PR strategy normalization for config compatibility."""

from __future__ import annotations

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

"""Runtime profile registry and validation helpers.

This module defines the Atelier-owned runtime profiles that planner and worker
roles may select. The config layer stores only the selected profile name.
"""

from __future__ import annotations

from typing import Literal

from .io import die

RUNTIME_PROFILE_VALUES = ("standard", "trycycle-bounded")
RuntimeProfileName = Literal["standard", "trycycle-bounded"]


def normalize_runtime_profile(
    value: object,
    *,
    source: str,
) -> RuntimeProfileName:
    """Normalize a runtime profile name or fail with a helpful error.

    Args:
        value: Raw runtime profile value.
        source: Field or flag label for error reporting.

    Returns:
        The normalized runtime profile name.

    Raises:
        SystemExit: If ``value`` is not a supported runtime profile.
    """
    if value is None:
        return "standard"
    if isinstance(value, str):
        normalized = value.strip().lower().replace("_", "-")
        if not normalized:
            return "standard"
        if normalized in RUNTIME_PROFILE_VALUES:
            return normalized  # type: ignore[return-value]
    die(f"{source} must be one of: " + ", ".join(RUNTIME_PROFILE_VALUES))

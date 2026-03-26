"""Planner runtime profile helpers.

This module keeps planner-specific runtime-profile wording and resolution out
of the CLI controller so the planner command stays focused on orchestration.
"""

from __future__ import annotations

from .config import ProjectConfig
from .runtime_profiles import RuntimeProfileName, normalize_runtime_profile


def resolve_planner_runtime_profile(
    project_config: ProjectConfig,
    *,
    runtime_profile_override: object,
) -> RuntimeProfileName:
    """Resolve the planner runtime profile from config and CLI override.

    Args:
        project_config: Current project configuration.
        runtime_profile_override: Optional CLI override.

    Returns:
        The normalized planner runtime profile.
    """
    selected = runtime_profile_override
    if selected is None:
        selected = project_config.runtime.planner.profile
    return normalize_runtime_profile(selected, source="runtime.planner.profile")


def planner_runtime_profile_contract(profile: RuntimeProfileName) -> str:
    """Return planner guidance for the selected runtime profile.

    Args:
        profile: Selected planner runtime profile.

    Returns:
        Planner contract text to render into AGENTS.md.
    """
    if profile == "trycycle-bounded":
        return (
            "Bounded planner contract: every executable bead must record explicit "
            "intent, non-goals, constraints, success criteria, and test "
            "expectations before promotion. Fail closed on missing contract data "
            "instead of letting workers infer policy."
        )
    return (
        "Standard planner contract: follow the default Atelier planning flow and "
        "record clear executable intent before promotion."
    )

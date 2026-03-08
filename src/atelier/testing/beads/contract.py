"""Published contract for the in-memory Beads command harness.

The dispatcher added for ``at-s1vc`` emulates the small slice of command-shape
behavior that Atelier's runtime relies on today: argv-based dispatch,
parseable ``--version`` / ``--help`` responses, and explicit unimplemented
markers for command families whose semantics are added in later changesets.
"""

from __future__ import annotations

from dataclasses import dataclass

from atelier.lib.beads import DEFAULT_MINIMUM_BD_VERSION

IN_MEMORY_BEADS_VERSION = str(DEFAULT_MINIMUM_BD_VERSION)
DEFAULT_UNIMPLEMENTED_RETURN_CODE = 2
SUPPORTED_GLOBAL_FLAGS = (
    "--actor",
    "--allow-stale",
    "--db",
    "--dolt-auto-commit",
    "--profile",
    "--quiet",
    "--readonly",
    "--sandbox",
    "--verbose",
)
_VALUE_GLOBAL_FLAGS = ("--actor", "--db", "--dolt-auto-commit")
BOOLEAN_GLOBAL_FLAGS = tuple(
    flag for flag in SUPPORTED_GLOBAL_FLAGS if flag not in _VALUE_GLOBAL_FLAGS
)


@dataclass(frozen=True)
class InMemoryBeadsCommandRoute:
    """One documented in-memory ``bd`` route.

    Args:
        family_id: Stable command-family identifier used for dispatcher
            handler registration.
        tier: Implementation tier planned for the route family.
        command: Canonical command tokens after the optional ``bd`` executable
            and any leading global flags are stripped.
        summary: Short user-facing purpose text rendered in help output.
        supports_json_output: Whether ``--json`` is part of the command's
            published contract.
    """

    family_id: str
    tier: str
    command: tuple[str, ...]
    summary: str
    supports_json_output: bool = False

    @property
    def command_label(self) -> str:
        """Return the space-joined route label."""

        return " ".join(self.command)


DOCUMENTED_COMMAND_ROUTES = (
    InMemoryBeadsCommandRoute(
        family_id="core-issues",
        tier="tier-0",
        command=("show",),
        summary="Show one issue.",
        supports_json_output=True,
    ),
    InMemoryBeadsCommandRoute(
        family_id="core-issues",
        tier="tier-0",
        command=("list",),
        summary="List issues.",
        supports_json_output=True,
    ),
    InMemoryBeadsCommandRoute(
        family_id="core-issues",
        tier="tier-0",
        command=("ready",),
        summary="List ready issues.",
        supports_json_output=True,
    ),
    InMemoryBeadsCommandRoute(
        family_id="core-issues",
        tier="tier-0",
        command=("create",),
        summary="Create an issue.",
        supports_json_output=True,
    ),
    InMemoryBeadsCommandRoute(
        family_id="core-issues",
        tier="tier-0",
        command=("update",),
        summary="Update an issue.",
        supports_json_output=True,
    ),
    InMemoryBeadsCommandRoute(
        family_id="core-issues",
        tier="tier-0",
        command=("close",),
        summary="Close an issue.",
        supports_json_output=True,
    ),
    InMemoryBeadsCommandRoute(
        family_id="dependency-edges",
        tier="tier-0",
        command=("dep", "add"),
        summary="Add an issue dependency edge.",
        supports_json_output=True,
    ),
    InMemoryBeadsCommandRoute(
        family_id="dependency-edges",
        tier="tier-0",
        command=("dep", "remove"),
        summary="Remove an issue dependency edge.",
        supports_json_output=True,
    ),
    InMemoryBeadsCommandRoute(
        family_id="ownership-slots",
        tier="tier-1",
        command=("slot", "show"),
        summary="Show slot values for an issue.",
        supports_json_output=True,
    ),
    InMemoryBeadsCommandRoute(
        family_id="ownership-slots",
        tier="tier-1",
        command=("slot", "set"),
        summary="Set a slot value for an issue.",
    ),
    InMemoryBeadsCommandRoute(
        family_id="ownership-slots",
        tier="tier-1",
        command=("slot", "clear"),
        summary="Clear a slot value for an issue.",
    ),
    InMemoryBeadsCommandRoute(
        family_id="startup-config",
        tier="tier-2",
        command=("prime",),
        summary="Prime the Beads store.",
    ),
    InMemoryBeadsCommandRoute(
        family_id="startup-config",
        tier="tier-2",
        command=("init",),
        summary="Initialize a Beads store.",
    ),
    InMemoryBeadsCommandRoute(
        family_id="startup-config",
        tier="tier-2",
        command=("config", "get"),
        summary="Read configuration values.",
        supports_json_output=True,
    ),
    InMemoryBeadsCommandRoute(
        family_id="startup-config",
        tier="tier-2",
        command=("config", "set"),
        summary="Write configuration values.",
    ),
    InMemoryBeadsCommandRoute(
        family_id="startup-config",
        tier="tier-2",
        command=("types",),
        summary="List configured issue types.",
        supports_json_output=True,
    ),
    InMemoryBeadsCommandRoute(
        family_id="startup-config",
        tier="tier-2",
        command=("rename-prefix",),
        summary="Rename issue id prefixes.",
    ),
    InMemoryBeadsCommandRoute(
        family_id="runtime-admin",
        tier="tier-3",
        command=("stats",),
        summary="Show runtime store statistics.",
    ),
    InMemoryBeadsCommandRoute(
        family_id="runtime-admin",
        tier="tier-3",
        command=("doctor",),
        summary="Run store diagnostics.",
    ),
    InMemoryBeadsCommandRoute(
        family_id="runtime-admin",
        tier="tier-3",
        command=("migrate",),
        summary="Migrate legacy store state.",
    ),
    InMemoryBeadsCommandRoute(
        family_id="runtime-admin",
        tier="tier-3",
        command=("dolt", "show"),
        summary="Show Dolt backend metadata.",
        supports_json_output=True,
    ),
    InMemoryBeadsCommandRoute(
        family_id="runtime-admin",
        tier="tier-3",
        command=("dolt", "set", "database"),
        summary="Select the active Dolt database.",
    ),
    InMemoryBeadsCommandRoute(
        family_id="runtime-admin",
        tier="tier-3",
        command=("dolt", "commit"),
        summary="Persist pending Dolt changes.",
    ),
    InMemoryBeadsCommandRoute(
        family_id="runtime-admin",
        tier="tier-3",
        command=("vc", "status"),
        summary="Show Dolt working-set status.",
        supports_json_output=True,
    ),
)


def documented_route_index() -> dict[tuple[str, ...], InMemoryBeadsCommandRoute]:
    """Return the route table keyed by normalized command tokens."""

    return {route.command: route for route in DOCUMENTED_COMMAND_ROUTES}


__all__ = [
    "BOOLEAN_GLOBAL_FLAGS",
    "DEFAULT_UNIMPLEMENTED_RETURN_CODE",
    "DOCUMENTED_COMMAND_ROUTES",
    "IN_MEMORY_BEADS_VERSION",
    "SUPPORTED_GLOBAL_FLAGS",
    "InMemoryBeadsCommandRoute",
    "documented_route_index",
]

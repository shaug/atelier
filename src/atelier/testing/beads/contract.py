"""Published contract for the in-memory Beads command harness."""

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


@dataclass(frozen=True)
class InMemoryBeadsCommandRoute:
    """One documented in-memory ``bd`` route."""

    family_id: str
    tier: str
    command: tuple[str, ...]
    summary: str
    supports_json_output: bool = False

    @property
    def command_label(self) -> str:
        """Return the space-joined route label."""

        return " ".join(self.command)


_ROUTE_ROWS = (
    ("core-issues", "tier-0", ("show",), "Show one issue.", True),
    ("core-issues", "tier-0", ("list",), "List issues.", True),
    ("core-issues", "tier-0", ("ready",), "List ready issues.", True),
    ("core-issues", "tier-0", ("create",), "Create an issue.", True),
    ("core-issues", "tier-0", ("update",), "Update an issue.", True),
    ("core-issues", "tier-0", ("close",), "Close an issue.", True),
    ("dependency-edges", "tier-0", ("dep", "add"), "Add an issue dependency edge.", True),
    (
        "dependency-edges",
        "tier-0",
        ("dep", "remove"),
        "Remove an issue dependency edge.",
        True,
    ),
    ("ownership-slots", "tier-1", ("slot", "show"), "Show slot values for an issue.", True),
    ("ownership-slots", "tier-1", ("slot", "set"), "Set a slot value for an issue.", False),
    (
        "ownership-slots",
        "tier-1",
        ("slot", "clear"),
        "Clear a slot value for an issue.",
        False,
    ),
    ("startup-config", "tier-2", ("prime",), "Prime the Beads store.", False),
    ("startup-config", "tier-2", ("init",), "Initialize a Beads store.", False),
    ("startup-config", "tier-2", ("config", "get"), "Read configuration values.", True),
    ("startup-config", "tier-2", ("config", "set"), "Write configuration values.", False),
    ("startup-config", "tier-2", ("types",), "List configured issue types.", True),
    ("startup-config", "tier-2", ("rename-prefix",), "Rename issue id prefixes.", False),
    ("runtime-admin", "tier-3", ("stats",), "Show runtime store statistics.", False),
    ("runtime-admin", "tier-3", ("doctor",), "Run store diagnostics.", False),
    ("runtime-admin", "tier-3", ("migrate",), "Migrate legacy store state.", False),
    ("runtime-admin", "tier-3", ("dolt", "show"), "Show Dolt backend metadata.", True),
    (
        "runtime-admin",
        "tier-3",
        ("dolt", "set", "database"),
        "Select the active Dolt database.",
        False,
    ),
    ("runtime-admin", "tier-3", ("dolt", "commit"), "Persist pending Dolt changes.", False),
    ("runtime-admin", "tier-3", ("vc", "status"), "Show Dolt working-set status.", True),
)

DOCUMENTED_COMMAND_ROUTES = tuple(
    InMemoryBeadsCommandRoute(
        family_id=family_id,
        tier=tier,
        command=command,
        summary=summary,
        supports_json_output=supports_json_output,
    )
    for family_id, tier, command, summary, supports_json_output in _ROUTE_ROWS
)


def documented_route_index() -> dict[tuple[str, ...], InMemoryBeadsCommandRoute]:
    """Return the route table keyed by normalized command tokens."""

    return {route.command: route for route in DOCUMENTED_COMMAND_ROUTES}


__all__ = [
    "DEFAULT_UNIMPLEMENTED_RETURN_CODE",
    "DOCUMENTED_COMMAND_ROUTES",
    "IN_MEMORY_BEADS_VERSION",
    "SUPPORTED_GLOBAL_FLAGS",
    "InMemoryBeadsCommandRoute",
    "documented_route_index",
]

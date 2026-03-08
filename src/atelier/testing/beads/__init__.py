"""Public test-support surface for the in-memory Beads backend."""

from .contract import (
    BOOLEAN_GLOBAL_FLAGS,
    DEFAULT_UNIMPLEMENTED_RETURN_CODE,
    DOCUMENTED_COMMAND_ROUTES,
    IN_MEMORY_BEADS_VERSION,
    SUPPORTED_GLOBAL_FLAGS,
    InMemoryBeadsCommandRoute,
    documented_route_index,
)
from .dispatcher import (
    CommandEnvelope,
    CommandFamilyHandler,
    CommandInvocation,
    InMemoryBeadsCommandBackend,
    InMemoryBeadsDispatcher,
    normalize_invocation,
)
from .fixtures import (
    DEFAULT_FIXTURE_TIMESTAMP,
    IssueFixtureBuilder,
    build_issue_payload,
    build_issue_reference,
)

__all__ = [
    "BOOLEAN_GLOBAL_FLAGS",
    "DEFAULT_FIXTURE_TIMESTAMP",
    "DEFAULT_UNIMPLEMENTED_RETURN_CODE",
    "DOCUMENTED_COMMAND_ROUTES",
    "IN_MEMORY_BEADS_VERSION",
    "SUPPORTED_GLOBAL_FLAGS",
    "CommandEnvelope",
    "CommandFamilyHandler",
    "CommandInvocation",
    "InMemoryBeadsCommandBackend",
    "InMemoryBeadsCommandRoute",
    "InMemoryBeadsDispatcher",
    "IssueFixtureBuilder",
    "build_issue_payload",
    "build_issue_reference",
    "documented_route_index",
    "normalize_invocation",
]

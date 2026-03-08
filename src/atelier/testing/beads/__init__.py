"""Public test-support surface for the in-memory Beads backend."""

from .client import (
    IN_MEMORY_TIER_ZERO_COMPATIBILITY_POLICY,
    InMemoryBeadsClient,
    build_in_memory_beads_client,
    build_in_memory_issue_store,
)
from .contract import (
    DEFAULT_UNIMPLEMENTED_RETURN_CODE,
    DOCUMENTED_COMMAND_ROUTES,
    IN_MEMORY_BEADS_VERSION,
    SUPPORTED_GLOBAL_FLAGS,
    InMemoryBeadsCommandRoute,
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
from .store import InMemoryIssueStore, StoredIssue

__all__ = [
    "DEFAULT_FIXTURE_TIMESTAMP",
    "DEFAULT_UNIMPLEMENTED_RETURN_CODE",
    "DOCUMENTED_COMMAND_ROUTES",
    "IN_MEMORY_BEADS_VERSION",
    "IN_MEMORY_TIER_ZERO_COMPATIBILITY_POLICY",
    "SUPPORTED_GLOBAL_FLAGS",
    "CommandEnvelope",
    "CommandFamilyHandler",
    "CommandInvocation",
    "InMemoryBeadsClient",
    "InMemoryBeadsCommandBackend",
    "InMemoryBeadsCommandRoute",
    "InMemoryBeadsDispatcher",
    "InMemoryIssueStore",
    "IssueFixtureBuilder",
    "StoredIssue",
    "build_in_memory_beads_client",
    "build_in_memory_issue_store",
    "build_issue_payload",
    "build_issue_reference",
    "normalize_invocation",
]

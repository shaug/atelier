"""Public test-support surface for the in-memory Beads backend."""

from .backend import (
    InMemoryBeadsBackend,
    InMemoryBeadsCommandRunner,
    InMemoryOwnershipSlotsHandler,
)
from .client import (
    IN_MEMORY_TIER_ZERO_COMPATIBILITY_POLICY,
    InMemoryBeadsClient,
    build_in_memory_beads_client,
    build_in_memory_dispatcher,
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
from .patch import patch_in_memory_beads
from .store import UNSET_UPDATE_FIELD, InMemoryIssueStore, StoredIssue

__all__ = [
    "DEFAULT_FIXTURE_TIMESTAMP",
    "DEFAULT_UNIMPLEMENTED_RETURN_CODE",
    "DOCUMENTED_COMMAND_ROUTES",
    "IN_MEMORY_BEADS_VERSION",
    "IN_MEMORY_TIER_ZERO_COMPATIBILITY_POLICY",
    "SUPPORTED_GLOBAL_FLAGS",
    "UNSET_UPDATE_FIELD",
    "CommandEnvelope",
    "CommandFamilyHandler",
    "CommandInvocation",
    "InMemoryBeadsBackend",
    "InMemoryBeadsClient",
    "InMemoryBeadsCommandBackend",
    "InMemoryBeadsCommandRoute",
    "InMemoryBeadsCommandRunner",
    "InMemoryBeadsDispatcher",
    "InMemoryIssueStore",
    "InMemoryOwnershipSlotsHandler",
    "IssueFixtureBuilder",
    "StoredIssue",
    "build_in_memory_beads_client",
    "build_in_memory_dispatcher",
    "build_in_memory_issue_store",
    "build_issue_payload",
    "build_issue_reference",
    "normalize_invocation",
    "patch_in_memory_beads",
]

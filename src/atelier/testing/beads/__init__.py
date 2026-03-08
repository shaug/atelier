"""Public test-support surface for the in-memory Beads backend."""

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

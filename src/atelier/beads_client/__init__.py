"""Public contract for the typed Beads client package.

The package defines a transport seam plus typed request, response, error, and
compatibility models. Higher-level Atelier abstractions should depend on this
contract rather than calling ``bd`` directly so future in-memory and alternate
transport implementations can match the same semantics.
"""

from .client import AsyncBeadsClient, BeadsTransport
from .compatibility import (
    DEFAULT_COMPATIBILITY_POLICY,
    DEFAULT_MINIMUM_BD_VERSION,
    CapabilityRule,
    CompatibilityPolicy,
    OperationContract,
)
from .errors import (
    BeadError,
    BeadsCommandError,
    BeadsCompatibilityError,
    BeadsParseError,
    BeadsTimeoutError,
    CapabilityMismatchError,
    UnsupportedOperationError,
    UnsupportedVersionError,
)
from .models import (
    BeadsCapability,
    BeadsCommandRequest,
    BeadsCommandResult,
    BeadsEnvironment,
    CloseIssueRequest,
    CreateIssueRequest,
    DependencyMutationRequest,
    IssueRecord,
    IssueReference,
    ListIssuesRequest,
    OperationOutputMode,
    ReadyIssuesRequest,
    SemanticVersion,
    ShowIssueRequest,
    SupportedOperation,
    UpdateIssueRequest,
    validate_issue_record,
)

__all__ = [
    "DEFAULT_COMPATIBILITY_POLICY",
    "DEFAULT_MINIMUM_BD_VERSION",
    "AsyncBeadsClient",
    "BeadError",
    "BeadsCapability",
    "BeadsCommandError",
    "BeadsCommandRequest",
    "BeadsCommandResult",
    "BeadsCompatibilityError",
    "BeadsEnvironment",
    "BeadsParseError",
    "BeadsTimeoutError",
    "BeadsTransport",
    "CapabilityMismatchError",
    "CapabilityRule",
    "CloseIssueRequest",
    "CompatibilityPolicy",
    "CreateIssueRequest",
    "DependencyMutationRequest",
    "IssueRecord",
    "IssueReference",
    "ListIssuesRequest",
    "OperationContract",
    "OperationOutputMode",
    "ReadyIssuesRequest",
    "SemanticVersion",
    "ShowIssueRequest",
    "SupportedOperation",
    "UnsupportedOperationError",
    "UnsupportedVersionError",
    "UpdateIssueRequest",
    "validate_issue_record",
]

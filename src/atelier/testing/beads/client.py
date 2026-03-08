"""Typed client adapters for the in-memory Beads dispatcher."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from atelier.lib.beads import (
    DEFAULT_COMPATIBILITY_POLICY,
    Beads,
    BeadsCapability,
    BeadsCommandRequest,
    BeadsCommandResult,
    BeadsTransport,
    CompatibilityPolicy,
    OperationContract,
    SubprocessBeadsClient,
    SupportedOperation,
)

from .core_issues import InMemoryCoreIssuesHandler
from .dispatcher import InMemoryBeadsCommandBackend, InMemoryBeadsDispatcher
from .store import InMemoryIssueStore

_TIER_ZERO_OPERATIONS = (
    SupportedOperation.INSPECT_ENVIRONMENT,
    SupportedOperation.SHOW,
    SupportedOperation.LIST,
    SupportedOperation.READY,
    SupportedOperation.CREATE,
    SupportedOperation.UPDATE,
    SupportedOperation.CLOSE,
)

IN_MEMORY_TIER_ZERO_COMPATIBILITY_POLICY = CompatibilityPolicy(
    minimum_version=DEFAULT_COMPATIBILITY_POLICY.minimum_version,
    capability_rules=tuple(
        rule
        for rule in DEFAULT_COMPATIBILITY_POLICY.capability_rules
        if rule.capability
        in {
            BeadsCapability.VERSION_REPORTING,
            BeadsCapability.ISSUE_JSON,
            BeadsCapability.ISSUE_MUTATION,
            BeadsCapability.READY_DISCOVERY,
        }
    ),
    operations=tuple(
        OperationContract.model_validate(contract.model_dump())
        for contract in DEFAULT_COMPATIBILITY_POLICY.operations
        if contract.operation in _TIER_ZERO_OPERATIONS
    ),
)


class InMemoryBeadsTransport(BeadsTransport):
    """Async transport adapter over the in-memory command backend."""

    def __init__(self, backend: InMemoryBeadsCommandBackend) -> None:
        self._backend = backend

    async def execute(self, request: BeadsCommandRequest) -> BeadsCommandResult:
        result = self._backend.run(request.argv, cwd=request.cwd, env=request.env)
        return BeadsCommandResult(
            argv=tuple(str(token) for token in result.args),
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            timed_out=False,
        )


def build_in_memory_dispatcher(
    *,
    issue_store: InMemoryIssueStore | None = None,
) -> InMemoryBeadsDispatcher:
    """Build a dispatcher with the Tier 0 core issue handler installed."""

    store = issue_store or InMemoryIssueStore()
    return InMemoryBeadsDispatcher(
        family_handlers={"core-issues": InMemoryCoreIssuesHandler(store)}
    )


def build_in_memory_issue_store(
    *,
    issues: Iterable[Mapping[str, object]] = (),
    prefix: str = "at",
) -> InMemoryIssueStore:
    """Build a seeded in-memory issue store."""

    return InMemoryIssueStore(issues=issues, prefix=prefix)


def build_in_memory_beads_client(
    *,
    issues: Iterable[Mapping[str, object]] = (),
    prefix: str = "at",
    compatibility_policy: CompatibilityPolicy = IN_MEMORY_TIER_ZERO_COMPATIBILITY_POLICY,
) -> tuple[Beads, InMemoryIssueStore]:
    """Build a typed Beads client backed by the in-memory dispatcher."""

    store = build_in_memory_issue_store(issues=issues, prefix=prefix)
    client = SubprocessBeadsClient(
        transport=InMemoryBeadsTransport(build_in_memory_dispatcher(issue_store=store)),
        compatibility_policy=compatibility_policy,
    )
    return client, store


__all__ = [
    "IN_MEMORY_TIER_ZERO_COMPATIBILITY_POLICY",
    "InMemoryBeadsTransport",
    "build_in_memory_beads_client",
    "build_in_memory_dispatcher",
    "build_in_memory_issue_store",
]

"""Typed client adapters for the in-memory Beads dispatcher.

The dispatcher remains the command-contract seam defined in `at-s1vc.1`. The
typed client adapter intentionally wraps that same dispatcher so argv-level
parity tests and `atelier.lib.beads.Beads` protocol tests share one mutable
store and one set of command semantics rather than drifting into separate
implementations.
"""

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
    """Build a dispatcher with the Tier 0 core issue handler installed.

    Args:
        issue_store: Optional shared issue store. Callers can pass the same
            store to both dispatcher and typed-client helpers when they need to
            assert parity across both entry points.

    Returns:
        Dispatcher backed by the provided or newly created issue store.
    """

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
    """Build a typed Beads client backed by the in-memory dispatcher.

    The typed client is intentionally an adapter over the dispatcher rather than
    a separate backend implementation. That keeps the documented argv contract
    from `at-s1vc.1` and the `atelier.lib.beads.Beads` protocol on top of the
    same store/mutation surface.

    Args:
        issues: Initial issue payloads to seed into the shared store.
        prefix: Prefix used for generated numeric ids.
        compatibility_policy: Supported-operation policy for the typed client.

    Returns:
        Tuple of the typed Beads client and the shared in-memory issue store it
        uses underneath the dispatcher transport.
    """

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

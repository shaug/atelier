"""Store-backed typed Beads client for the Tier 0 in-memory backend."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from atelier.lib.beads import (
    DEFAULT_COMPATIBILITY_POLICY,
    Beads,
    BeadsCapability,
    BeadsEnvironment,
    BeadsStartupState,
    CloseIssueRequest,
    CompatibilityPolicy,
    CreateIssueRequest,
    DependencyMutationRequest,
    IssueRecord,
    ListIssuesRequest,
    OperationContract,
    ReadyIssuesRequest,
    SemanticVersion,
    ShowIssueRequest,
    SupportedOperation,
    UnsupportedOperationError,
    UpdateIssueRequest,
)

from .contract import IN_MEMORY_BEADS_VERSION
from .core_issues import InMemoryCoreIssuesHandler
from .dispatcher import InMemoryBeadsDispatcher
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

_TIER_ZERO_CAPABILITIES = (
    BeadsCapability.VERSION_REPORTING,
    BeadsCapability.ISSUE_JSON,
    BeadsCapability.ISSUE_MUTATION,
    BeadsCapability.READY_DISCOVERY,
)


def _default_startup_state() -> BeadsStartupState:
    return BeadsStartupState(
        classification="in_memory_backend",
        migration_eligible=False,
        has_dolt_store=False,
        has_legacy_sqlite=False,
        dolt_issue_total=None,
        legacy_issue_total=None,
        reason="in_memory_backend_has_no_legacy_startup_storage",
        backend="in-memory",
    )


class InMemoryBeadsClient(Beads):
    """Typed Beads client backed directly by the in-memory issue store."""

    def __init__(
        self,
        *,
        issue_store: InMemoryIssueStore,
        compatibility_policy: CompatibilityPolicy = IN_MEMORY_TIER_ZERO_COMPATIBILITY_POLICY,
        startup_state: BeadsStartupState | None = None,
    ) -> None:
        self._issue_store = issue_store
        self._compatibility_policy = compatibility_policy
        self._environment = BeadsEnvironment(
            version=SemanticVersion.model_validate(IN_MEMORY_BEADS_VERSION),
            capabilities=_TIER_ZERO_CAPABILITIES,
        )
        self._startup_state = startup_state or _default_startup_state()

    @property
    def compatibility_policy(self) -> CompatibilityPolicy:
        return self._compatibility_policy

    async def inspect_environment(self) -> BeadsEnvironment:
        self._compatibility_policy.assert_environment_supports(self._environment)
        for contract in self._compatibility_policy.operations:
            self._compatibility_policy.assert_environment_supports(
                self._environment,
                operation=contract.operation,
            )
        return self._environment

    async def inspect_startup_state(self) -> BeadsStartupState:
        return self._startup_state

    async def show(self, request: ShowIssueRequest) -> IssueRecord:
        await self._ensure_operation_supported(SupportedOperation.SHOW)
        return IssueRecord.model_validate(self._issue_store.show(request.issue_id))

    async def list(self, request: ListIssuesRequest) -> tuple[IssueRecord, ...]:
        await self._ensure_operation_supported(SupportedOperation.LIST)
        return tuple(
            IssueRecord.model_validate(payload)
            for payload in self._issue_store.list(
                parent_id=request.parent_id,
                status=request.status,
                assignee=request.assignee,
                title_query=request.title_query,
                labels=request.labels,
                include_closed=request.include_closed,
                limit=request.limit,
            )
        )

    async def ready(self, request: ReadyIssuesRequest) -> tuple[IssueRecord, ...]:
        await self._ensure_operation_supported(SupportedOperation.READY)
        return tuple(
            IssueRecord.model_validate(payload)
            for payload in self._issue_store.ready(parent_id=request.parent_id)
        )

    async def create(self, request: CreateIssueRequest) -> IssueRecord:
        await self._ensure_operation_supported(SupportedOperation.CREATE)
        if request.status is not None:
            raise UnsupportedOperationError(
                "in-memory Tier 0 create does not support setting status during creation"
            )
        return IssueRecord.model_validate(
            self._issue_store.create(
                title=request.title,
                issue_type=request.issue_type,
                description=request.description,
                design=request.design,
                acceptance_criteria=request.acceptance_criteria,
                assignee=request.assignee,
                parent_id=request.parent_id,
                priority=request.priority,
                estimate=request.estimate,
                labels=request.labels,
            )
        )

    async def update(self, request: UpdateIssueRequest) -> IssueRecord:
        await self._ensure_operation_supported(SupportedOperation.UPDATE)
        if request.labels == ():
            raise UnsupportedOperationError(
                "in-memory Tier 0 update does not support clearing labels"
            )
        return IssueRecord.model_validate(
            self._issue_store.update(
                request.issue_id,
                title=request.title,
                description=request.description,
                design=request.design,
                acceptance_criteria=request.acceptance_criteria,
                status=request.status,
                assignee=request.assignee,
                priority=request.priority,
                estimate=request.estimate,
                labels=request.labels,
            )
        )

    async def close(self, request: CloseIssueRequest) -> IssueRecord:
        await self._ensure_operation_supported(SupportedOperation.CLOSE)
        return IssueRecord.model_validate(
            self._issue_store.close(request.issue_id, reason=request.reason)
        )

    async def add_dependency(self, request: DependencyMutationRequest) -> IssueRecord:
        del request
        await self._ensure_operation_supported(SupportedOperation.DEPENDENCY_ADD)
        raise UnsupportedOperationError("dependency mutation is outside Tier 0 scope")

    async def remove_dependency(self, request: DependencyMutationRequest) -> IssueRecord:
        del request
        await self._ensure_operation_supported(SupportedOperation.DEPENDENCY_REMOVE)
        raise UnsupportedOperationError("dependency mutation is outside Tier 0 scope")

    async def _ensure_operation_supported(self, operation: SupportedOperation) -> None:
        environment = await self.inspect_environment()
        self._compatibility_policy.assert_environment_supports(
            environment,
            operation=operation,
        )


def build_in_memory_dispatcher(
    *,
    issue_store: InMemoryIssueStore | None = None,
) -> InMemoryBeadsDispatcher:
    """Build the optional Tier 0 command harness for route-level tests.

    Args:
        issue_store: Optional shared issue store for command-harness tests.

    Returns:
        Dispatcher backed by the provided or newly created issue store. The
        typed in-memory Beads client does not depend on this helper.
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
    startup_state: BeadsStartupState | None = None,
) -> tuple[Beads, InMemoryIssueStore]:
    """Build a typed Beads client backed directly by the in-memory store.

    Args:
        issues: Initial issue payloads to seed into the shared store.
        prefix: Prefix used for generated numeric ids.
        compatibility_policy: Supported-operation policy for the typed client.
        startup_state: Optional semantic startup state returned directly by the
            typed in-memory Beads client.

    Returns:
        Tuple of the typed Beads client and the shared in-memory issue store it
        mutates directly.
    """

    store = build_in_memory_issue_store(issues=issues, prefix=prefix)
    client = InMemoryBeadsClient(
        issue_store=store,
        compatibility_policy=compatibility_policy,
        startup_state=startup_state,
    )
    return client, store


__all__ = [
    "IN_MEMORY_TIER_ZERO_COMPATIBILITY_POLICY",
    "InMemoryBeadsClient",
    "build_in_memory_beads_client",
    "build_in_memory_dispatcher",
    "build_in_memory_issue_store",
]

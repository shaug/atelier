"""Async-first Atelier store contract above the Beads client contract."""

from __future__ import annotations

from typing import NoReturn

from pydantic import field_validator, model_validator

from .models import (
    ChangesetRecord,
    DependencyRecord,
    EpicRecord,
    HookRecord,
    Identifier,
    LifecycleStatus,
    LifecycleTransition,
    MessageDelivery,
    MessageRecord,
    MessageThreadKind,
    ReviewMetadata,
    StoreModel,
)


def _dedupe_identifiers(values: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    return tuple(value for value in values if not (value in seen or seen.add(value)))


class EpicQuery(StoreModel):
    """Filter for listing epics from the Atelier store."""

    assignee: Identifier | None = None
    include_closed: bool = False


class ChangesetQuery(StoreModel):
    """Filter for listing changesets from the Atelier store."""

    epic_id: Identifier | None = None
    assignee: Identifier | None = None
    lifecycle: LifecycleStatus | None = None
    include_closed: bool = False


class ReadyChangesetQuery(StoreModel):
    """Filter for readiness-aware changeset discovery."""

    epic_id: Identifier | None = None


class MessageQuery(StoreModel):
    """Filter for listing durable coordination messages."""

    thread_id: Identifier | None = None
    queue: Identifier | None = None
    unread_only: bool = False
    audience: tuple[Identifier, ...] = ()

    @field_validator("audience")
    @classmethod
    def _dedupe_audience(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _dedupe_identifiers(value)


class DependencyMutation(StoreModel):
    """Mutation request for one dependency edge."""

    issue_id: Identifier
    depends_on_id: Identifier
    requires_integrated_state: bool = True


class CreateMessageRequest(StoreModel):
    """Mutation request for creating one durable coordination message."""

    title: Identifier
    body: str = ""
    delivery: MessageDelivery = MessageDelivery.WORK_THREADED
    sender: Identifier | None = None
    thread_id: Identifier | None = None
    thread_kind: MessageThreadKind | None = None
    audience: tuple[Identifier, ...] = ()
    kind: Identifier | None = None
    blocking: bool | None = None
    reply_to: Identifier | None = None
    queue: Identifier | None = None

    @field_validator("audience")
    @classmethod
    def _dedupe_audience(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _dedupe_identifiers(value)

    @model_validator(mode="after")
    def _validate_thread_contract(self) -> "CreateMessageRequest":
        if self.delivery == MessageDelivery.WORK_THREADED and self.thread_id is None:
            raise ValueError("work-threaded messages require thread_id")
        if self.delivery == MessageDelivery.WORK_THREADED and self.thread_kind is None:
            raise ValueError("work-threaded messages require thread_kind")
        return self


class ClaimMessageRequest(StoreModel):
    """Mutation request for claiming a queued message."""

    message_id: Identifier
    claimed_by: Identifier


class SetHookRequest(StoreModel):
    """Mutation request for binding an agent to one epic hook."""

    agent_id: Identifier
    epic_id: Identifier
    expected_current_epic_id: Identifier | None = None


class ClearHookRequest(StoreModel):
    """Mutation request for clearing an existing agent hook."""

    agent_id: Identifier
    expected_epic_id: Identifier | None = None


class UpdateReviewRequest(StoreModel):
    """Mutation request for replacing or merging changeset review metadata."""

    changeset_id: Identifier
    review: ReviewMetadata
    preserve_existing: bool = False


class LifecycleTransitionRequest(StoreModel):
    """Mutation request for canonical lifecycle changes."""

    issue_id: Identifier
    target_status: LifecycleStatus
    expected_current: LifecycleStatus | None = None
    reason: Identifier | None = None


class AtelierStore:
    """Concrete async store facade for Atelier planning state.

    Downstream planner, worker, and publish code should depend on this single
    store service. Backend choice remains an adapter construction concern below
    this class via the injected Beads implementation, not via multiple peer
    store contracts or subclasses. Follow-on adapter changesets should fill in
    these method bodies on this same facade. Until then, every operation fails
    closed: if the adapter cannot answer or persist one of these requests
    without lossy inference, it must raise instead of silently approximating
    the result.
    """

    def __init__(self, beads_backend: object) -> None:
        self._beads_backend = beads_backend

    @property
    def beads_backend(self) -> object:
        """Return the injected Beads backend used by this store service."""

        return self._beads_backend

    def _raise_deferred(self, operation: str) -> NoReturn:
        raise NotImplementedError(
            f"AtelierStore.{operation} is deferred to the follow-on store adapter changesets"
        )

    async def get_epic(self, epic_id: str) -> EpicRecord:
        """Load one epic record by stable Atelier id.

        Args:
            epic_id: Stable Atelier epic identifier.

        Returns:
            The hydrated epic record for the requested id.

        Raises:
            LookupError: If no matching epic exists.
        """
        del epic_id
        self._raise_deferred("get_epic")

    async def list_epics(
        self,
        query: EpicQuery = EpicQuery(),
    ) -> tuple[EpicRecord, ...]:
        """List epics that satisfy one store-native query.

        Args:
            query: Optional assignee/closed-state filters.

        Returns:
            Matching epic records in backend-defined stable order.
        """
        del query
        self._raise_deferred("list_epics")

    async def get_changeset(self, changeset_id: str) -> ChangesetRecord:
        """Load one changeset record by stable Atelier id.

        Args:
            changeset_id: Stable Atelier changeset identifier.

        Returns:
            The hydrated changeset record for the requested id.

        Raises:
            LookupError: If no matching changeset exists.
        """
        del changeset_id
        self._raise_deferred("get_changeset")

    async def list_changesets(
        self,
        query: ChangesetQuery = ChangesetQuery(),
    ) -> tuple[ChangesetRecord, ...]:
        """List changesets that satisfy one store-native query.

        Args:
            query: Optional epic, assignee, lifecycle, and closed-state filters.

        Returns:
            Matching changeset records in backend-defined stable order.
        """
        del query
        self._raise_deferred("list_changesets")

    async def list_ready_changesets(
        self,
        query: ReadyChangesetQuery = ReadyChangesetQuery(),
    ) -> tuple[ChangesetRecord, ...]:
        """List unblocked changesets ready for execution.

        Args:
            query: Optional epic scope for readiness-aware discovery.

        Returns:
            Changesets that the backend can prove are ready without widening
            Atelier readiness semantics.
        """
        del query
        self._raise_deferred("list_ready_changesets")

    async def list_messages(
        self,
        query: MessageQuery = MessageQuery(),
    ) -> tuple[MessageRecord, ...]:
        """List durable coordination messages through store-owned filters.

        Args:
            query: Optional thread, queue, audience, and unread filters.

        Returns:
            Matching durable message records in backend-defined stable order.
        """
        del query
        self._raise_deferred("list_messages")

    async def get_agent_hook(self, agent_id: str) -> HookRecord | None:
        """Load the current epic hook, if any, for one agent.

        Args:
            agent_id: Stable Atelier agent identifier.

        Returns:
            The current hook binding, or `None` when the agent is unhooked.
        """
        del agent_id
        self._raise_deferred("get_agent_hook")

    async def add_dependency(self, mutation: DependencyMutation) -> DependencyRecord:
        """Persist one dependency edge as an Atelier-owned mutation.

        Args:
            mutation: Dependency edge to add.

        Returns:
            The persisted dependency record.
        """
        del mutation
        self._raise_deferred("add_dependency")

    async def remove_dependency(
        self,
        mutation: DependencyMutation,
    ) -> DependencyRecord | None:
        """Remove one dependency edge if it exists.

        Args:
            mutation: Dependency edge to remove.

        Returns:
            The removed dependency record, or `None` when no such edge existed.
        """
        del mutation
        self._raise_deferred("remove_dependency")

    async def create_message(self, request: CreateMessageRequest) -> MessageRecord:
        """Persist one durable work-threaded coordination message.

        Args:
            request: Message payload and threaded routing metadata to persist.

        Returns:
            The persisted message record on its epic or changeset thread.
        """
        del request
        self._raise_deferred("create_message")

    async def claim_message(self, request: ClaimMessageRequest) -> MessageRecord:
        """Persist queue-claim metadata for one durable message.

        Args:
            request: Message id plus claiming agent identity.

        Returns:
            The updated message record after the claim mutation.
        """
        del request
        self._raise_deferred("claim_message")

    async def set_agent_hook(self, request: SetHookRequest) -> HookRecord:
        """Bind one agent to one epic hook.

        Args:
            request: Hook identity plus optional compare-and-swap expectation.

        Returns:
            The persisted hook record after the binding succeeds.
        """
        del request
        self._raise_deferred("set_agent_hook")

    async def clear_agent_hook(self, request: ClearHookRequest) -> HookRecord | None:
        """Clear one agent hook when the current binding matches expectations.

        Args:
            request: Agent identity plus optional expected epic id.

        Returns:
            The cleared hook record, or `None` when nothing was cleared.
        """
        del request
        self._raise_deferred("clear_agent_hook")

    async def update_review(self, request: UpdateReviewRequest) -> ChangesetRecord:
        """Replace or merge review metadata for one changeset.

        Args:
            request: Review payload plus merge behavior for existing metadata.

        Returns:
            The updated changeset record after review metadata persists.
        """
        del request
        self._raise_deferred("update_review")

    async def transition_lifecycle(
        self,
        request: LifecycleTransitionRequest,
    ) -> LifecycleTransition:
        """Apply one canonical lifecycle transition.

        Args:
            request: Target lifecycle state plus optional current-state guard.

        Returns:
            The applied lifecycle transition record.
        """
        del request
        self._raise_deferred("transition_lifecycle")


AsyncAtelierStore = AtelierStore

__all__ = [
    "AsyncAtelierStore",
    "AtelierStore",
    "ChangesetQuery",
    "ClaimMessageRequest",
    "ClearHookRequest",
    "CreateMessageRequest",
    "DependencyMutation",
    "EpicQuery",
    "LifecycleTransitionRequest",
    "MessageQuery",
    "ReadyChangesetQuery",
    "SetHookRequest",
    "UpdateReviewRequest",
]

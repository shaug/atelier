"""Async-first Atelier store protocol above the Beads client contract."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import Field, field_validator, model_validator

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

    assignee: Identifier | None = None
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
    assignee: Identifier | None = None
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


@runtime_checkable
class AtelierStore(Protocol):
    """Backend-neutral async store contract for Atelier planning state."""

    async def get_epic(self, epic_id: str) -> EpicRecord: ...

    async def list_epics(self, query: EpicQuery = EpicQuery()) -> tuple[EpicRecord, ...]: ...

    async def get_changeset(self, changeset_id: str) -> ChangesetRecord: ...

    async def list_changesets(
        self,
        query: ChangesetQuery = ChangesetQuery(),
    ) -> tuple[ChangesetRecord, ...]: ...

    async def list_ready_changesets(
        self,
        query: ReadyChangesetQuery = ReadyChangesetQuery(),
    ) -> tuple[ChangesetRecord, ...]: ...

    async def list_messages(
        self,
        query: MessageQuery = MessageQuery(),
    ) -> tuple[MessageRecord, ...]: ...

    async def get_agent_hook(self, agent_id: str) -> HookRecord | None: ...

    async def add_dependency(self, mutation: DependencyMutation) -> DependencyRecord: ...

    async def remove_dependency(self, mutation: DependencyMutation) -> DependencyRecord | None: ...

    async def create_message(self, request: CreateMessageRequest) -> MessageRecord: ...

    async def claim_message(self, request: ClaimMessageRequest) -> MessageRecord: ...

    async def set_agent_hook(self, request: SetHookRequest) -> HookRecord: ...

    async def clear_agent_hook(self, request: ClearHookRequest) -> HookRecord | None: ...

    async def update_review(self, request: UpdateReviewRequest) -> ChangesetRecord: ...

    async def transition_lifecycle(
        self,
        request: LifecycleTransitionRequest,
    ) -> LifecycleTransition: ...


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

"""Typed Atelier store request and query models."""

from __future__ import annotations

from pydantic import field_validator, model_validator

from .models import (
    Identifier,
    LifecycleStatus,
    MessageDelivery,
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


class AppendNotesRequest(StoreModel):
    """Mutation request for appending durable notes to one work item."""

    issue_id: Identifier
    notes: tuple[str, ...]

    @field_validator("notes")
    @classmethod
    def _normalize_notes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized: list[str] = []
        seen: set[str] = set()
        for note in value:
            cleaned = note.strip()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            normalized.append(cleaned)
        if not normalized:
            raise ValueError("append notes requires at least one non-empty note")
        return tuple(normalized)


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


__all__ = [
    "AppendNotesRequest",
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

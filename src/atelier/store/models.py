"""Atelier-owned models for the planning store contract."""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from ..external_tickets import (
    ExternalTicketRef,
    normalize_direction,
    normalize_identifier,
    normalize_on_close,
    normalize_optional_string,
    normalize_relation,
    normalize_slug,
    normalize_state,
    normalize_sync_mode,
    normalize_timestamp,
)

Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, strict=True)]


def _dedupe_identifiers(values: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    return tuple(value for value in values if not (value in seen or seen.add(value)))


class StoreModel(BaseModel):
    """Base model for the Atelier-owned store contract."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class LifecycleStatus(str, Enum):
    """Canonical lifecycle states owned by Atelier business logic."""

    DEFERRED = "deferred"
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    CLOSED = "closed"


class WorkItemKind(str, Enum):
    """Atelier work item kinds exposed by the store contract."""

    EPIC = "epic"
    CHANGESET = "changeset"


class ReviewState(str, Enum):
    """Canonical PR lifecycle states tracked for changesets."""

    PUSHED = "pushed"
    DRAFT_PR = "draft-pr"
    PR_OPEN = "pr-open"
    IN_REVIEW = "in-review"
    APPROVED = "approved"
    MERGED = "merged"
    CLOSED = "closed"


class MessageDelivery(str, Enum):
    """Delivery modes for coordination messages."""

    WORK_THREADED = "work-threaded"


class MessageThreadKind(str, Enum):
    """Allowed work-thread scopes for durable messages."""

    CHANGESET = "changeset"
    EPIC = "epic"


class WorkRef(StoreModel):
    """Stable reference to an Atelier work item."""

    id: Identifier
    title: Identifier | None = None
    kind: WorkItemKind | None = None


class DependencyRecord(StoreModel):
    """Dependency relation and satisfaction state for one work item edge."""

    issue_id: Identifier
    depends_on_id: Identifier
    satisfied: bool | None = None
    requires_integrated_state: bool = True
    status: LifecycleStatus | None = None


class ReviewMetadata(StoreModel):
    """Normalized review and integration metadata for a changeset."""

    pr_url: Identifier | None = None
    pr_number: int | None = Field(default=None, ge=1)
    pr_state: ReviewState | None = None
    review_owner: Identifier | None = None
    integrated_sha: Identifier | None = None


class ExternalTicketLink(StoreModel):
    """Store-owned persisted metadata for one external ticket link."""

    provider: Identifier
    ticket_id: Identifier
    url: str | None = None
    title: str | None = None
    summary: str | None = None
    body: str | None = None
    notes: str | None = None
    relation: Literal["primary", "secondary", "context", "derived"] | None = None
    direction: Literal["imported", "exported", "linked"] | None = None
    sync_mode: Literal["manual", "import", "export", "sync"] | None = None
    state: Literal["open", "in_progress", "blocked", "in_review", "closed", "unknown"] | None = None
    raw_state: str | None = None
    state_updated_at: str | None = None
    parent_id: Identifier | None = None
    on_close: Literal["none", "comment", "close", "sync"] | None = None
    content_updated_at: str | None = None
    notes_updated_at: str | None = None
    last_synced_at: str | None = None

    @field_validator("provider", mode="before")
    @classmethod
    def _normalize_provider(cls, value: object) -> object:
        return normalize_slug(value)

    @field_validator("ticket_id", "parent_id", mode="before")
    @classmethod
    def _normalize_identifiers(cls, value: object) -> object:
        return normalize_identifier(value)

    @field_validator(
        "url",
        "title",
        "summary",
        "body",
        "notes",
        "raw_state",
        mode="before",
    )
    @classmethod
    def _normalize_optional_strings(cls, value: object) -> object:
        return normalize_optional_string(value)

    @field_validator("relation", mode="before")
    @classmethod
    def _normalize_relation(cls, value: object) -> object:
        return normalize_relation(value)

    @field_validator("direction", mode="before")
    @classmethod
    def _normalize_direction(cls, value: object) -> object:
        return normalize_direction(value)

    @field_validator("sync_mode", mode="before")
    @classmethod
    def _normalize_sync_mode(cls, value: object) -> object:
        return normalize_sync_mode(value)

    @field_validator("state", mode="before")
    @classmethod
    def _normalize_state(cls, value: object) -> object:
        return normalize_state(value)

    @field_validator("on_close", mode="before")
    @classmethod
    def _normalize_on_close(cls, value: object) -> object:
        return normalize_on_close(value)

    @field_validator(
        "state_updated_at",
        "content_updated_at",
        "notes_updated_at",
        "last_synced_at",
        mode="before",
    )
    @classmethod
    def _normalize_timestamps(cls, value: object) -> object:
        return normalize_timestamp(value)

    @classmethod
    def from_external_ref(cls, ref: ExternalTicketRef) -> "ExternalTicketLink":
        """Build a store model from one compatibility-layer ticket reference."""

        return cls(
            provider=ref.provider,
            ticket_id=ref.ticket_id,
            url=ref.url,
            title=ref.title,
            summary=ref.summary,
            body=ref.body,
            notes=ref.notes,
            relation=cast(
                Literal["primary", "secondary", "context", "derived"] | None,
                ref.relation,
            ),
            direction=cast(
                Literal["imported", "exported", "linked"] | None,
                ref.direction,
            ),
            sync_mode=cast(
                Literal["manual", "import", "export", "sync"] | None,
                ref.sync_mode,
            ),
            state=cast(
                Literal["open", "in_progress", "blocked", "in_review", "closed", "unknown"] | None,
                ref.state,
            ),
            raw_state=ref.raw_state,
            state_updated_at=ref.state_updated_at,
            parent_id=ref.parent_id,
            on_close=cast(
                Literal["none", "comment", "close", "sync"] | None,
                ref.on_close,
            ),
            content_updated_at=ref.content_updated_at,
            notes_updated_at=ref.notes_updated_at,
            last_synced_at=ref.last_synced_at,
        )

    def to_external_ref(self) -> ExternalTicketRef:
        """Project the store model into the compatibility ticket shape."""

        return ExternalTicketRef(
            provider=self.provider,
            ticket_id=self.ticket_id,
            url=self.url,
            title=self.title,
            summary=self.summary,
            body=self.body,
            notes=self.notes,
            relation=self.relation,
            direction=self.direction,
            sync_mode=self.sync_mode,
            state=self.state,
            raw_state=self.raw_state,
            state_updated_at=self.state_updated_at,
            parent_id=self.parent_id,
            on_close=self.on_close,
            content_updated_at=self.content_updated_at,
            notes_updated_at=self.notes_updated_at,
            last_synced_at=self.last_synced_at,
        )


class ChangesetBranches(StoreModel):
    """Branch metadata needed to publish and reconcile one changeset."""

    root_branch: Identifier | None = None
    parent_branch: Identifier | None = None
    work_branch: Identifier | None = None
    root_base: Identifier | None = None
    parent_base: Identifier | None = None


class EpicRecord(StoreModel):
    """Atelier-owned representation of an epic."""

    kind: Literal[WorkItemKind.EPIC] = WorkItemKind.EPIC
    id: Identifier
    title: Identifier
    lifecycle: LifecycleStatus
    assignee: Identifier | None = None
    root_branch: Identifier | None = None
    labels: tuple[Identifier, ...] = ()
    changesets: tuple[WorkRef, ...] = ()
    dependencies: tuple[DependencyRecord, ...] = ()

    @field_validator("labels")
    @classmethod
    def _dedupe_labels(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _dedupe_identifiers(value)


class ChangesetRecord(StoreModel):
    """Atelier-owned representation of a changeset."""

    kind: Literal[WorkItemKind.CHANGESET] = WorkItemKind.CHANGESET
    id: Identifier
    title: Identifier
    lifecycle: LifecycleStatus
    epic_id: Identifier | None = None
    assignee: Identifier | None = None
    labels: tuple[Identifier, ...] = ()
    dependencies: tuple[DependencyRecord, ...] = ()
    branches: ChangesetBranches | None = None
    review: ReviewMetadata = Field(default_factory=ReviewMetadata)

    @field_validator("labels")
    @classmethod
    def _dedupe_labels(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _dedupe_identifiers(value)


class MessageRecord(StoreModel):
    """Atelier-owned representation of a durable coordination message."""

    id: Identifier
    title: Identifier
    body: str = ""
    delivery: MessageDelivery
    status: LifecycleStatus | None = None
    sender: Identifier | None = None
    thread_id: Identifier | None = None
    thread_kind: MessageThreadKind | None = None
    audience: tuple[Identifier, ...] = ()
    kind: Identifier | None = None
    blocking: bool | None = None
    reply_to: Identifier | None = None
    queue: Identifier | None = None
    claimed_by: Identifier | None = None
    claimed_at: Identifier | None = None

    @field_validator("audience")
    @classmethod
    def _dedupe_identifiers(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _dedupe_identifiers(value)

    @model_validator(mode="after")
    def _validate_thread_contract(self) -> "MessageRecord":
        if self.thread_id is None:
            raise ValueError("work-threaded messages require thread_id")
        if self.thread_kind is None:
            raise ValueError("work-threaded messages require thread_kind")
        return self


class StartupMessageRecord(StoreModel):
    """Startup-specific message projection for routing and gating reads."""

    id: Identifier
    title: Identifier
    body: str = ""
    thread_id: Identifier | None = None
    thread_kind: MessageThreadKind | None = None
    audience: tuple[Identifier, ...] = ()
    kind: Identifier | None = None
    queue: Identifier | None = None
    claimed_by: Identifier | None = None
    blocking_roles: tuple[Identifier, ...] = ()

    @field_validator("audience", "blocking_roles")
    @classmethod
    def _dedupe_startup_roles(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _dedupe_identifiers(value)


class HookRecord(StoreModel):
    """Agent-to-epic hook ownership tracked by the store contract."""

    agent_id: Identifier
    epic_id: Identifier


class LifecycleTransition(StoreModel):
    """Lifecycle transition requested or applied through the store."""

    issue_id: Identifier
    issue_kind: WorkItemKind
    from_status: LifecycleStatus | None = None
    to_status: LifecycleStatus
    reason: Identifier | None = None


class EpicIdentityViolation(StoreModel):
    """Active top-level work missing executable epic identity metadata."""

    issue_id: Identifier
    status: LifecycleStatus | None = None
    issue_type: Identifier | None = None
    labels: tuple[Identifier, ...] = ()
    remediation_command: str

    @field_validator("labels")
    @classmethod
    def _dedupe_violation_labels(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _dedupe_identifiers(value)


class EpicDiscoveryParity(StoreModel):
    """Indexed epic discovery parity diagnostics."""

    active_top_level_work_count: int = Field(ge=0, default=0)
    indexed_active_epic_count: int = Field(ge=0, default=0)
    missing_executable_identity: tuple[EpicIdentityViolation, ...] = ()
    missing_from_index: tuple[Identifier, ...] = ()

    @property
    def in_parity(self) -> bool:
        """Return whether startup epic discovery is in parity."""

        return not self.missing_executable_identity and not self.missing_from_index


__all__ = [
    "ChangesetBranches",
    "ChangesetRecord",
    "DependencyRecord",
    "EpicDiscoveryParity",
    "EpicIdentityViolation",
    "EpicRecord",
    "ExternalTicketLink",
    "HookRecord",
    "Identifier",
    "LifecycleStatus",
    "LifecycleTransition",
    "MessageDelivery",
    "MessageRecord",
    "MessageThreadKind",
    "ReviewMetadata",
    "ReviewState",
    "StartupMessageRecord",
    "StoreModel",
    "WorkItemKind",
    "WorkRef",
]

"""Atelier-owned models for the planning store contract."""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
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
    "HookRecord",
    "Identifier",
    "LifecycleStatus",
    "LifecycleTransition",
    "MessageDelivery",
    "MessageRecord",
    "MessageThreadKind",
    "ReviewMetadata",
    "ReviewState",
    "StoreModel",
    "WorkItemKind",
    "WorkRef",
]

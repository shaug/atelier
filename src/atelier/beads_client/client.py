"""Async-first public client interfaces for Beads operations."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .compatibility import CompatibilityPolicy
from .models import (
    BeadsCommandRequest,
    BeadsCommandResult,
    BeadsEnvironment,
    CloseIssueRequest,
    CreateIssueRequest,
    DependencyMutationRequest,
    IssueRecord,
    ListIssuesRequest,
    ReadyIssuesRequest,
    ShowIssueRequest,
    UpdateIssueRequest,
)


@runtime_checkable
class BeadsTransport(Protocol):
    """Low-level async transport used by process-backed or in-memory clients."""

    async def execute(self, request: BeadsCommandRequest) -> BeadsCommandResult:
        """Execute a low-level Beads command request."""

        ...


@runtime_checkable
class AsyncBeadsClient(Protocol):
    """Async-first client contract for supported ``bd`` operations."""

    @property
    def compatibility_policy(self) -> CompatibilityPolicy:
        """Return the bounded compatibility policy for this client."""

        ...

    async def inspect_environment(self) -> BeadsEnvironment:
        """Return the active ``bd`` environment and detected capabilities."""

        ...

    async def show(self, request: ShowIssueRequest) -> IssueRecord:
        """Load a single issue by id."""

        ...

    async def list(self, request: ListIssuesRequest) -> tuple[IssueRecord, ...]:
        """List issues matching the provided filters."""

        ...

    async def ready(self, request: ReadyIssuesRequest) -> tuple[IssueRecord, ...]:
        """Return issues that are ready to execute or review."""

        ...

    async def create(self, request: CreateIssueRequest) -> IssueRecord:
        """Create an issue and return its normalized record."""

        ...

    async def update(self, request: UpdateIssueRequest) -> IssueRecord:
        """Mutate an issue and return its normalized record."""

        ...

    async def close(self, request: CloseIssueRequest) -> IssueRecord:
        """Close an issue and return its normalized record."""

        ...

    async def add_dependency(self, request: DependencyMutationRequest) -> IssueRecord:
        """Add a dependency edge and return the refreshed issue."""

        ...

    async def remove_dependency(self, request: DependencyMutationRequest) -> IssueRecord:
        """Remove a dependency edge and return the refreshed issue."""

        ...

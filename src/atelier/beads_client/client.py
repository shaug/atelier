"""Async-first Beads client and transport protocols."""

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
    """Low-level async transport for process-backed or in-memory clients."""

    async def execute(self, request: BeadsCommandRequest) -> BeadsCommandResult: ...


@runtime_checkable
class AsyncBeadsClient(Protocol):
    """Async-first contract for the supported Beads operations."""

    @property
    def compatibility_policy(self) -> CompatibilityPolicy: ...

    async def inspect_environment(self) -> BeadsEnvironment: ...

    async def show(self, request: ShowIssueRequest) -> IssueRecord: ...

    async def list(self, request: ListIssuesRequest) -> tuple[IssueRecord, ...]: ...

    async def ready(self, request: ReadyIssuesRequest) -> tuple[IssueRecord, ...]: ...

    async def create(self, request: CreateIssueRequest) -> IssueRecord: ...

    async def update(self, request: UpdateIssueRequest) -> IssueRecord: ...

    async def close(self, request: CloseIssueRequest) -> IssueRecord: ...

    async def add_dependency(self, request: DependencyMutationRequest) -> IssueRecord: ...

    async def remove_dependency(self, request: DependencyMutationRequest) -> IssueRecord: ...

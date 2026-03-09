"""Synchronous wrappers over the async-first Beads client."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Protocol, runtime_checkable

from .client import Beads
from .compatibility import CompatibilityPolicy
from .models import (
    BeadsEnvironment,
    BeadsStartupState,
    CloseIssueRequest,
    CreateIssueRequest,
    DependencyMutationRequest,
    IssueRecord,
    ListIssuesRequest,
    ReadyIssuesRequest,
    ShowIssueRequest,
    UpdateIssueRequest,
)
from .process import SubprocessBeadsClient


@runtime_checkable
class SyncBeadsProtocol(Protocol):
    """Structural contract for synchronous Beads adopters."""

    def inspect_environment(self) -> BeadsEnvironment: ...

    def inspect_startup_state(self) -> BeadsStartupState: ...

    def show(self, request: ShowIssueRequest) -> IssueRecord: ...

    def list(self, request: ListIssuesRequest) -> tuple[IssueRecord, ...]: ...

    def ready(self, request: ReadyIssuesRequest) -> tuple[IssueRecord, ...]: ...

    def create(self, request: CreateIssueRequest) -> IssueRecord: ...

    def update(self, request: UpdateIssueRequest) -> IssueRecord: ...

    def close(self, request: CloseIssueRequest) -> IssueRecord: ...

    def add_dependency(self, request: DependencyMutationRequest) -> IssueRecord: ...

    def remove_dependency(self, request: DependencyMutationRequest) -> IssueRecord: ...


class SyncBeadsClient:
    """Run the async Beads client behind a synchronous facade.

    Args:
        async_client: Async-first Beads client to execute.

    Raises:
        RuntimeError: Raised by ``asyncio.run`` when called from an active
            event loop.
    """

    def __init__(self, async_client: Beads) -> None:
        self._async_client = async_client

    @property
    def compatibility_policy(self) -> CompatibilityPolicy:
        return self._async_client.compatibility_policy

    def inspect_environment(self) -> BeadsEnvironment:
        return asyncio.run(self._async_client.inspect_environment())

    def inspect_startup_state(self) -> BeadsStartupState:
        return asyncio.run(self._async_client.inspect_startup_state())

    def show(self, request: ShowIssueRequest) -> IssueRecord:
        return asyncio.run(self._async_client.show(request))

    def list(self, request: ListIssuesRequest) -> tuple[IssueRecord, ...]:
        return asyncio.run(self._async_client.list(request))

    def ready(self, request: ReadyIssuesRequest) -> tuple[IssueRecord, ...]:
        return asyncio.run(self._async_client.ready(request))

    def create(self, request: CreateIssueRequest) -> IssueRecord:
        return asyncio.run(self._async_client.create(request))

    def update(self, request: UpdateIssueRequest) -> IssueRecord:
        return asyncio.run(self._async_client.update(request))

    def close(self, request: CloseIssueRequest) -> IssueRecord:
        return asyncio.run(self._async_client.close(request))

    def add_dependency(self, request: DependencyMutationRequest) -> IssueRecord:
        return asyncio.run(self._async_client.add_dependency(request))

    def remove_dependency(self, request: DependencyMutationRequest) -> IssueRecord:
        return asyncio.run(self._async_client.remove_dependency(request))


def build_sync_beads_client(
    *,
    cwd: Path,
    beads_root: Path,
    readonly: bool = False,
) -> SyncBeadsClient:
    """Build a sync Beads client for low-level boundary helpers.

    Args:
        cwd: Repository-local working directory for ``bd`` subprocesses.
        beads_root: Root of the Beads store to target.
        readonly: Whether to prepend ``--readonly`` to every ``bd`` command.

    Returns:
        A synchronous facade over the subprocess-backed Beads client.
    """

    global_args: tuple[str, ...] = ("--readonly",) if readonly else ()
    return SyncBeadsClient(
        SubprocessBeadsClient(
            cwd=cwd,
            beads_root=beads_root,
            env={"BEADS_DIR": str(beads_root)},
            global_args=global_args,
        )
    )

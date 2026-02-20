"""Worker runtime data models."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StartupContractResult:
    epic_id: str | None
    changeset_id: str | None
    should_exit: bool
    reason: str
    reassign_from: str | None = None


@dataclass(frozen=True)
class WorkerRunSummary:
    started: bool
    reason: str
    epic_id: str | None = None
    changeset_id: str | None = None


@dataclass(frozen=True)
class FinalizeResult:
    continue_running: bool
    reason: str


@dataclass(frozen=True)
class ReconcileResult:
    scanned: int
    actionable: int
    reconciled: int
    failed: int


@dataclass(frozen=True)
class PublishSignalDiagnostics:
    local_branch_exists: bool
    remote_branch_exists: bool
    worktree_path: Path | None
    dirty_entries: tuple[str, ...]

    @property
    def has_recoverable_local_state(self) -> bool:
        return self.local_branch_exists or bool(self.dirty_entries)

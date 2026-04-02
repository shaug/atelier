"""Shared event-history overflow recovery helpers for Beads clients."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class EventHistoryOverflowRepairResult:
    """Structured result for event-history overflow repair attempts."""

    issue_id: str
    repaired: bool
    verified_mutable: bool
    snapshot_bytes_before: int
    snapshot_bytes_after: int
    retained_notes_chars: int


@runtime_checkable
class AsyncEventHistoryOverflowRecovery(Protocol):
    """Async Beads capability for overflow detection and repair."""

    def is_event_history_overflow_detail(self, detail: str | None) -> bool: ...

    async def repair_event_history_overflow(
        self, issue_id: str
    ) -> EventHistoryOverflowRepairResult: ...


@runtime_checkable
class SyncEventHistoryOverflowRecovery(Protocol):
    """Sync Beads capability for overflow detection and repair."""

    def is_event_history_overflow_detail(self, detail: str | None) -> bool: ...

    def repair_event_history_overflow(self, issue_id: str) -> EventHistoryOverflowRepairResult: ...


def event_history_overflow_operator_guidance(issue_id: str) -> str:
    """Return the explicit operator recovery action for overflowed issues."""

    return (
        f"run `atelier repair-event-history-overflow {issue_id}` to compact "
        "the overflowed event history, verify mutability, and print "
        "backend-specific recovery guidance for inspecting the pre-repair "
        "content"
    )


def overflow_repair_result_proves_convergence(
    issue_id: str, result: EventHistoryOverflowRepairResult
) -> bool:
    """Return whether a repair result proves the target issue is mutable."""

    return result.issue_id == issue_id and result.verified_mutable is True


async def maybe_repair_after_event_history_overflow(
    client: AsyncEventHistoryOverflowRecovery,
    *,
    issue_id: str,
    failure: BaseException,
    mutation_label: str,
    already_repaired: bool,
) -> bool:
    """Repair one known overflow failure and signal whether to retry."""

    detail = str(failure).strip()
    if not client.is_event_history_overflow_detail(detail):
        return False
    if already_repaired:
        raise RuntimeError(
            f"{mutation_label} for {issue_id} still hit event-history overflow "
            "after deterministic repair; "
            f"{event_history_overflow_operator_guidance(issue_id)}"
        ) from failure
    try:
        repair_result = await client.repair_event_history_overflow(issue_id)
    except Exception as repair_error:
        raise RuntimeError(
            f"event-history overflow blocked the mutation for {issue_id} ({detail}); "
            f"repair unavailable: {repair_error}; "
            f"{event_history_overflow_operator_guidance(issue_id)}"
        ) from failure
    if not overflow_repair_result_proves_convergence(issue_id, repair_result):
        raise RuntimeError(
            f"{mutation_label} for {issue_id} hit event-history overflow, "
            "but repair evidence did not prove convergence; "
            f"{event_history_overflow_operator_guidance(issue_id)}"
        ) from failure
    return True


def maybe_repair_after_event_history_overflow_sync(
    client: SyncEventHistoryOverflowRecovery,
    *,
    issue_id: str,
    failure: BaseException,
    mutation_label: str,
    already_repaired: bool,
) -> bool:
    """Sync equivalent of ``maybe_repair_after_event_history_overflow``."""

    detail = str(failure).strip()
    if not client.is_event_history_overflow_detail(detail):
        return False
    if already_repaired:
        raise RuntimeError(
            f"{mutation_label} for {issue_id} still hit event-history overflow "
            "after deterministic repair; "
            f"{event_history_overflow_operator_guidance(issue_id)}"
        ) from failure
    try:
        repair_result = client.repair_event_history_overflow(issue_id)
    except Exception as repair_error:
        raise RuntimeError(
            f"event-history overflow blocked the mutation for {issue_id} ({detail}); "
            f"repair unavailable: {repair_error}; "
            f"{event_history_overflow_operator_guidance(issue_id)}"
        ) from failure
    if not overflow_repair_result_proves_convergence(issue_id, repair_result):
        raise RuntimeError(
            f"{mutation_label} for {issue_id} hit event-history overflow, "
            "but repair evidence did not prove convergence; "
            f"{event_history_overflow_operator_guidance(issue_id)}"
        ) from failure
    return True

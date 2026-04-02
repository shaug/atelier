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
    verified_mutation_classes: tuple[str, ...]
    convergence_evidence: tuple[str, ...]


_REQUIRED_MUTATION_CLASSES = frozenset({"notes_append", "status_transition"})


def _parse_convergence_evidence(
    result: EventHistoryOverflowRepairResult,
) -> dict[str, str] | None:
    raw_evidence = getattr(result, "convergence_evidence", None)
    if not isinstance(raw_evidence, tuple) or not raw_evidence:
        return None
    parsed: dict[str, str] = {}
    for entry in raw_evidence:
        if not isinstance(entry, str) or "=" not in entry:
            return None
        key, value = entry.split("=", 1)
        if not key or not value or key in parsed:
            return None
        parsed[key] = value
    return parsed


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
    if result.issue_id != issue_id or result.verified_mutable is not True:
        return False
    classes = getattr(result, "verified_mutation_classes", None)
    if not isinstance(classes, tuple) or not _REQUIRED_MUTATION_CLASSES.issubset(classes):
        return False
    evidence = _parse_convergence_evidence(result)
    if evidence is None:
        return False
    try:
        before = int(evidence["snapshot_bytes_before"])
        after = int(evidence["snapshot_bytes_after"])
        target = int(evidence["safe_snapshot_target_bytes"])
    except (KeyError, ValueError):
        return False
    if before != result.snapshot_bytes_before or after != result.snapshot_bytes_after:
        return False
    if evidence.get("verified_mutation_classes") != ",".join(classes):
        return False
    return after <= target


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

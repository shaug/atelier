"""Explicit compatibility seam for external-ticket metadata repair."""

from __future__ import annotations

from pathlib import Path

from . import beads

ExternalTicketMetadataRepairResult = beads.ExternalTicketMetadataRepairResult


def repair_external_ticket_metadata_from_history(
    *,
    beads_root: Path,
    repo_root: Path,
    issue_ids: list[str] | None = None,
    apply: bool = False,
) -> list[ExternalTicketMetadataRepairResult]:
    """Repair missing external ticket metadata through the retained helper."""

    return beads.repair_external_ticket_metadata_from_history(
        beads_root=beads_root,
        cwd=repo_root,
        issue_ids=issue_ids,
        apply=apply,
    )


__all__ = [
    "ExternalTicketMetadataRepairResult",
    "repair_external_ticket_metadata_from_history",
]

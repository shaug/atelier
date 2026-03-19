"""Compatibility-only reopen reconciliation for exported GitHub tickets."""

from __future__ import annotations

from pathlib import Path

from .. import beads


def reconcile_reopened_exported_github_tickets(
    issue_id: str,
    *,
    beads_root: Path,
    repo_root: Path,
) -> beads.ExternalTicketReconcileResult:
    """Reconcile exported GitHub tickets after reopening one issue.

    Args:
        issue_id: Issue whose exported ticket state should be reopened.
        beads_root: Project Beads data directory.
        repo_root: Repository root used for provider-side commands.

    Returns:
        The legacy Beads reopen-reconciliation result for the issue.
    """

    return beads.reconcile_reopened_issue_exported_github_tickets(
        issue_id,
        beads_root=beads_root,
        cwd=repo_root,
    )


__all__ = ["reconcile_reopened_exported_github_tickets"]

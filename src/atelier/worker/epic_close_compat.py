"""Explicit compatibility seam for epic-close flows.

This module keeps the remaining composite epic-close behavior out of
``atelier.beads`` call sites while the richer store-owned finalization semantic
remains deferred.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from .. import beads
from . import store_adapter as worker_store


def close_epic_if_complete(
    epic_id: str,
    agent_bead_id: str | None,
    *,
    beads_root: Path,
    repo_root: Path,
    confirm: Callable[[beads.ChangesetSummary], bool] | None = None,
    dry_run: bool = False,
    dry_run_log: Callable[[str], None] | None = None,
) -> bool:
    """Close one epic through the retained legacy compatibility helper."""

    return beads.close_epic_if_complete(
        epic_id,
        agent_bead_id,
        beads_root=beads_root,
        cwd=repo_root,
        confirm=confirm,
        dry_run=dry_run,
        dry_run_log=dry_run_log,
    )


def direct_close_epic(
    epic_id: str,
    agent_bead_id: str,
    *,
    beads_root: Path,
    repo_root: Path,
) -> None:
    """Close one epic immediately and clear the current worker hook."""

    beads.close_issue(epic_id, beads_root=beads_root, cwd=repo_root)
    worker_store.clear_agent_hook(
        agent_bead_id,
        beads_root=beads_root,
        repo_root=repo_root,
        expected_hook=epic_id,
    )


__all__ = ["close_epic_if_complete", "direct_close_epic"]

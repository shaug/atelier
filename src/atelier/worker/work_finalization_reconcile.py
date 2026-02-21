"""Reconcile entrypoints for worker runtime."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from .. import config
from ..worker import reconcile_service as worker_reconcile_service
from ..worker.models import ReconcileResult
from .work_finalization_integration import finalize_epic_if_complete
from .work_finalization_pipeline import finalize_changeset
from .work_finalization_state import (
    changeset_integration_signal,
    epic_root_integrated_into_parent,
    resolve_epic_id_for_changeset,
)
from .work_runtime_common import is_closed_status, issue_dependency_ids, issue_labels


def list_reconcile_epic_candidates(
    *,
    project_config: config.ProjectConfig,
    beads_root: Path,
    repo_root: Path,
    git_path: str | None = None,
) -> dict[str, list[str]]:
    """List reconcile epic candidates.

    Args:
        project_config: Value for `project_config`.
        beads_root: Value for `beads_root`.
        repo_root: Value for `repo_root`.
        git_path: Value for `git_path`.

    Returns:
        Function result.
    """
    return worker_reconcile_service.list_reconcile_epic_candidates(
        project_config=project_config,
        beads_root=beads_root,
        repo_root=repo_root,
        git_path=git_path,
        changeset_integration_signal=changeset_integration_signal,
        resolve_epic_id_for_changeset=resolve_epic_id_for_changeset,
        is_closed_status=is_closed_status,
        epic_root_integrated_into_parent=epic_root_integrated_into_parent,
    )


def reconcile_blocked_merged_changesets(
    *,
    agent_id: str,
    agent_bead_id: str | None,
    project_config: config.ProjectConfig,
    project_data_dir: Path | None,
    beads_root: Path,
    repo_root: Path,
    git_path: str | None = None,
    epic_filter: str | None = None,
    changeset_filter: set[str] | None = None,
    dry_run: bool = False,
    log: Callable[[str], None] | None = None,
) -> ReconcileResult:
    """Reconcile blocked merged changesets.

    Args:
        agent_id: Value for `agent_id`.
        agent_bead_id: Value for `agent_bead_id`.
        project_config: Value for `project_config`.
        project_data_dir: Value for `project_data_dir`.
        beads_root: Value for `beads_root`.
        repo_root: Value for `repo_root`.
        git_path: Value for `git_path`.
        epic_filter: Value for `epic_filter`.
        changeset_filter: Value for `changeset_filter`.
        dry_run: Value for `dry_run`.
        log: Value for `log`.

    Returns:
        Function result.
    """
    return worker_reconcile_service.reconcile_blocked_merged_changesets(
        agent_id=agent_id,
        agent_bead_id=agent_bead_id,
        project_config=project_config,
        project_data_dir=project_data_dir,
        beads_root=beads_root,
        repo_root=repo_root,
        git_path=git_path,
        epic_filter=epic_filter,
        changeset_filter=changeset_filter,
        dry_run=dry_run,
        log=log,
        resolve_epic_id_for_changeset=resolve_epic_id_for_changeset,
        changeset_integration_signal=changeset_integration_signal,
        issue_dependency_ids=issue_dependency_ids,
        issue_labels=issue_labels,
        finalize_changeset=finalize_changeset,
        finalize_epic_if_complete=finalize_epic_if_complete,
    )


__all__ = ["list_reconcile_epic_candidates", "reconcile_blocked_merged_changesets"]

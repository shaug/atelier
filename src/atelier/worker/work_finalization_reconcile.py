"""Reconcile entrypoints for worker runtime."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from .. import config
from ..worker import reconcile_service as worker_reconcile_service
from ..worker.models import ReconcileResult
from .work_finalization_integration import _finalize_epic_if_complete
from .work_finalization_pipeline import _finalize_changeset
from .work_finalization_state import (
    _changeset_integration_signal,
    _epic_root_integrated_into_parent,
    _issue_labels,
    _resolve_epic_id_for_changeset,
)
from .work_runtime_common import _is_closed_status, _issue_dependency_ids


def list_reconcile_epic_candidates(
    *,
    project_config: config.ProjectConfig,
    beads_root: Path,
    repo_root: Path,
    git_path: str | None = None,
) -> dict[str, list[str]]:
    return worker_reconcile_service.list_reconcile_epic_candidates(
        project_config=project_config,
        beads_root=beads_root,
        repo_root=repo_root,
        git_path=git_path,
        changeset_integration_signal=_changeset_integration_signal,
        resolve_epic_id_for_changeset=_resolve_epic_id_for_changeset,
        is_closed_status=_is_closed_status,
        epic_root_integrated_into_parent=_epic_root_integrated_into_parent,
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
        resolve_epic_id_for_changeset=_resolve_epic_id_for_changeset,
        changeset_integration_signal=_changeset_integration_signal,
        issue_dependency_ids=_issue_dependency_ids,
        issue_labels=_issue_labels,
        finalize_changeset=_finalize_changeset,
        finalize_epic_if_complete=_finalize_epic_if_complete,
    )


__all__ = [
    name
    for name in globals()
    if name.startswith("_")
    or name in {"list_reconcile_epic_candidates", "reconcile_blocked_merged_changesets"}
]

"""Reconcile helpers for merged/blocked changesets and epic resolution."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from .. import beads, config
from . import reconcile as worker_reconcile
from .models import FinalizeResult, ReconcileResult

Issue = dict[str, object]


def resolve_epic_id_for_changeset(
    issue: Issue,
    *,
    beads_root: Path,
    repo_root: Path,
    issue_labels: Callable[[Issue], set[str]],
    issue_parent_id: Callable[[Issue], str | None],
) -> str | None:
    current = issue
    current_id = issue.get("id")
    if not isinstance(current_id, str) or not current_id.strip():
        return None
    visited: set[str] = set()
    while True:
        issue_id = current_id.strip()
        if not issue_id or issue_id in visited:
            return None
        visited.add(issue_id)
        labels = issue_labels(current)
        if "at:epic" in labels:
            return issue_id
        parent_id = issue_parent_id(current)
        if not parent_id:
            if current is issue:
                loaded = beads.run_bd_json(
                    ["show", issue_id], beads_root=beads_root, cwd=repo_root
                )
                if loaded:
                    refreshed = loaded[0]
                    refreshed_parent = issue_parent_id(refreshed)
                    if refreshed_parent:
                        current = refreshed
                        parent_id = refreshed_parent
                        current_id = issue_id
            if not parent_id:
                return issue_id
        parent_issues = beads.run_bd_json(
            ["show", parent_id], beads_root=beads_root, cwd=repo_root
        )
        if not parent_issues:
            return parent_id
        current = parent_issues[0]
        current_id = parent_id


def list_reconcile_epic_candidates(
    *,
    project_config: config.ProjectConfig,
    beads_root: Path,
    repo_root: Path,
    git_path: str | None = None,
    changeset_integration_signal: Callable[..., tuple[bool, str | None]],
    resolve_epic_id_for_changeset: Callable[..., str | None],
    is_closed_status: Callable[[object], bool],
    epic_root_integrated_into_parent: Callable[..., bool],
) -> dict[str, list[str]]:
    return worker_reconcile.list_reconcile_epic_candidates(
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
    resolve_epic_id_for_changeset: Callable[..., str | None],
    changeset_integration_signal: Callable[..., tuple[bool, str | None]],
    issue_dependency_ids: Callable[[Issue], tuple[str, ...]],
    issue_labels: Callable[[Issue], set[str]],
    finalize_changeset: Callable[..., FinalizeResult],
    finalize_epic_if_complete: Callable[..., FinalizeResult],
) -> ReconcileResult:
    return worker_reconcile.reconcile_blocked_merged_changesets(
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

"""Changeset state/finalization helper functions for worker orchestration."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from pathlib import Path

from .. import beads, messages
from . import changeset_state as worker_changeset_state


def mark_changeset_in_progress(changeset_id: str, *, beads_root: Path, repo_root: Path) -> None:
    worker_changeset_state.mark_changeset_in_progress(
        changeset_id,
        beads_root=beads_root,
        repo_root=repo_root,
    )


def mark_changeset_closed(changeset_id: str, *, beads_root: Path, repo_root: Path) -> None:
    worker_changeset_state.mark_changeset_closed(
        changeset_id,
        beads_root=beads_root,
        repo_root=repo_root,
    )


def mark_changeset_merged(changeset_id: str, *, beads_root: Path, repo_root: Path) -> None:
    worker_changeset_state.mark_changeset_merged(
        changeset_id,
        beads_root=beads_root,
        repo_root=repo_root,
    )


def mark_changeset_abandoned(changeset_id: str, *, beads_root: Path, repo_root: Path) -> None:
    worker_changeset_state.mark_changeset_abandoned(
        changeset_id,
        beads_root=beads_root,
        repo_root=repo_root,
    )


def mark_changeset_blocked(
    changeset_id: str, *, beads_root: Path, repo_root: Path, reason: str
) -> None:
    worker_changeset_state.mark_changeset_blocked(
        changeset_id,
        beads_root=beads_root,
        repo_root=repo_root,
        reason=reason,
    )


def mark_changeset_children_in_progress(
    changeset_id: str, *, beads_root: Path, repo_root: Path
) -> None:
    worker_changeset_state.mark_changeset_children_in_progress(
        changeset_id,
        beads_root=beads_root,
        repo_root=repo_root,
    )


def close_completed_container_changesets(
    epic_id: str,
    *,
    beads_root: Path,
    repo_root: Path,
    has_open_descendant_changesets: Callable[[str], bool],
) -> list[str]:
    return worker_changeset_state.close_completed_container_changesets(
        epic_id,
        beads_root=beads_root,
        repo_root=repo_root,
        has_open_descendant_changesets=has_open_descendant_changesets,
    )


def promote_planned_descendant_changesets(
    changeset_id: str, *, beads_root: Path, repo_root: Path
) -> list[str]:
    return worker_changeset_state.promote_planned_descendant_changesets(
        changeset_id, beads_root=beads_root, repo_root=repo_root
    )


def list_child_issues(
    parent_id: str, *, beads_root: Path, repo_root: Path, include_closed: bool = False
) -> list[dict[str, object]]:
    return worker_changeset_state.list_child_issues(
        parent_id,
        beads_root=beads_root,
        repo_root=repo_root,
        include_closed=include_closed,
    )


def find_invalid_changeset_labels(
    root_id: str,
    *,
    beads_root: Path,
    repo_root: Path,
) -> list[str]:
    return worker_changeset_state.find_invalid_changeset_labels(
        root_id,
        beads_root=beads_root,
        repo_root=repo_root,
    )


def has_blocking_messages(
    *,
    thread_ids: set[str],
    started_at: dt.datetime,
    beads_root: Path,
    repo_root: Path,
    parse_issue_time: Callable[[object], dt.datetime | None],
) -> bool:
    issues = beads.run_bd_json(
        ["list", "--label", "at:message", "--label", "at:unread"],
        beads_root=beads_root,
        cwd=repo_root,
    )
    for issue in issues:
        created_at = parse_issue_time(issue.get("created_at"))
        if created_at is not None and created_at < started_at:
            continue
        description = issue.get("description")
        payload = messages.parse_message(description if isinstance(description, str) else "")
        thread = payload.metadata.get("thread")
        if isinstance(thread, str) and thread in thread_ids:
            return True
    return False

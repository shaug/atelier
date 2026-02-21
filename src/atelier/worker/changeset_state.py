"""Changeset label/state transition helpers."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from pathlib import Path

from .. import beads


def issue_labels(issue: dict[str, object]) -> set[str]:
    labels = issue.get("labels")
    if not isinstance(labels, list):
        return set()
    return {str(label) for label in labels if label is not None}


def list_child_issues(
    parent_id: str, *, beads_root: Path, repo_root: Path, include_closed: bool = False
) -> list[dict[str, object]]:
    args = ["list", "--parent", parent_id]
    if include_closed:
        args.append("--all")
    return beads.run_bd_json(args, beads_root=beads_root, cwd=repo_root)


def find_invalid_changeset_labels(
    root_id: str,
    *,
    beads_root: Path,
    repo_root: Path,
    valid_changeset_state_labels: set[str],
) -> list[str]:
    invalid: list[str] = []
    seen: set[str] = set()
    queue = [root_id]
    while queue:
        current = queue.pop(0)
        children = list_child_issues(
            current, beads_root=beads_root, repo_root=repo_root, include_closed=True
        )
        for issue in children:
            issue_id = issue.get("id")
            if not isinstance(issue_id, str) or not issue_id or issue_id in seen:
                continue
            seen.add(issue_id)
            queue.append(issue_id)
            labels = issue_labels(issue)
            has_cs_label = any(label.startswith("cs:") for label in labels)
            invalid_cs_labels = {
                label
                for label in labels
                if label.startswith("cs:") and label not in valid_changeset_state_labels
            }
            if "at:subtask" in labels or (has_cs_label and "at:changeset" not in labels):
                invalid.append(issue_id)
                continue
            if invalid_cs_labels:
                invalid.append(issue_id)
    return invalid


def mark_changeset_in_progress(changeset_id: str, *, beads_root: Path, repo_root: Path) -> None:
    beads.run_bd_command(
        [
            "update",
            changeset_id,
            "--add-label",
            "at:changeset",
            "--remove-label",
            "cs:ready",
            "--remove-label",
            "cs:in_progress",
            "--remove-label",
            "cs:planned",
            "--remove-label",
            "cs:blocked",
            "--remove-label",
            "cs:merged",
            "--remove-label",
            "cs:abandoned",
            "--status",
            "in_progress",
        ],
        beads_root=beads_root,
        cwd=repo_root,
    )


def mark_changeset_closed(changeset_id: str, *, beads_root: Path, repo_root: Path) -> None:
    beads.run_bd_command(
        [
            "update",
            changeset_id,
            "--status",
            "closed",
            "--remove-label",
            "cs:ready",
            "--remove-label",
            "cs:planned",
            "--remove-label",
            "cs:in_progress",
            "--remove-label",
            "cs:blocked",
        ],
        beads_root=beads_root,
        cwd=repo_root,
    )


def mark_changeset_merged(changeset_id: str, *, beads_root: Path, repo_root: Path) -> None:
    beads.run_bd_command(
        [
            "update",
            changeset_id,
            "--add-label",
            "cs:merged",
            "--remove-label",
            "cs:abandoned",
            "--remove-label",
            "cs:ready",
            "--remove-label",
            "cs:planned",
            "--remove-label",
            "cs:in_progress",
            "--remove-label",
            "cs:blocked",
            "--status",
            "closed",
        ],
        beads_root=beads_root,
        cwd=repo_root,
    )


def mark_changeset_abandoned(changeset_id: str, *, beads_root: Path, repo_root: Path) -> None:
    beads.run_bd_command(
        [
            "update",
            changeset_id,
            "--add-label",
            "cs:abandoned",
            "--remove-label",
            "cs:merged",
            "--remove-label",
            "cs:ready",
            "--remove-label",
            "cs:planned",
            "--remove-label",
            "cs:in_progress",
            "--remove-label",
            "cs:blocked",
            "--status",
            "closed",
        ],
        beads_root=beads_root,
        cwd=repo_root,
    )


def mark_changeset_blocked(
    changeset_id: str, *, beads_root: Path, repo_root: Path, reason: str
) -> None:
    timestamp = dt.datetime.now(tz=dt.timezone.utc).isoformat()
    note = f"blocked_at: {timestamp} reason: {reason}"
    beads.run_bd_command(
        [
            "update",
            changeset_id,
            "--remove-label",
            "cs:in_progress",
            "--remove-label",
            "cs:ready",
            "--remove-label",
            "cs:planned",
            "--remove-label",
            "cs:merged",
            "--remove-label",
            "cs:abandoned",
            "--add-label",
            "cs:blocked",
            "--status",
            "blocked",
            "--append-notes",
            note,
        ],
        beads_root=beads_root,
        cwd=repo_root,
    )


def mark_changeset_children_in_progress(
    changeset_id: str, *, beads_root: Path, repo_root: Path
) -> None:
    beads.run_bd_command(
        [
            "update",
            changeset_id,
            "--status",
            "in_progress",
            "--remove-label",
            "cs:ready",
            "--remove-label",
            "cs:in_progress",
            "--remove-label",
            "cs:planned",
            "--remove-label",
            "cs:blocked",
            "--remove-label",
            "cs:merged",
            "--remove-label",
            "cs:abandoned",
        ],
        beads_root=beads_root,
        cwd=repo_root,
    )


def close_completed_container_changesets(
    epic_id: str,
    *,
    beads_root: Path,
    repo_root: Path,
    has_open_descendant_changesets: Callable[[str], bool],
) -> list[str]:
    closed: list[str] = []
    descendants = beads.list_descendant_changesets(
        epic_id,
        beads_root=beads_root,
        cwd=repo_root,
        include_closed=True,
    )
    for issue in descendants:
        issue_id = issue.get("id")
        if not isinstance(issue_id, str) or not issue_id:
            continue
        status = str(issue.get("status") or "").lower()
        if status in {"closed", "done"}:
            continue
        labels = issue_labels(issue)
        if "cs:merged" not in labels and "cs:abandoned" not in labels:
            continue
        if has_open_descendant_changesets(issue_id):
            continue
        mark_changeset_closed(issue_id, beads_root=beads_root, repo_root=repo_root)
        closed.append(issue_id)
    return closed


def promote_planned_descendant_changesets(
    changeset_id: str, *, beads_root: Path, repo_root: Path
) -> list[str]:
    promoted: list[str] = []
    descendants = beads.list_descendant_changesets(
        changeset_id,
        beads_root=beads_root,
        cwd=repo_root,
        include_closed=False,
    )
    for issue in descendants:
        issue_id = issue.get("id")
        if not isinstance(issue_id, str) or not issue_id:
            continue
        labels = issue_labels(issue)
        if "cs:planned" not in labels:
            continue
        beads.run_bd_command(
            [
                "update",
                issue_id,
                "--add-label",
                "cs:ready",
                "--remove-label",
                "cs:planned",
                "--status",
                "open",
            ],
            beads_root=beads_root,
            cwd=repo_root,
        )
        promoted.append(issue_id)
    return promoted

"""Changeset label/state transition helpers."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from pathlib import Path

from .. import beads, lifecycle


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


def _changeset_review_state(issue: dict[str, object]) -> str | None:
    description = issue.get("description")
    text = description if isinstance(description, str) else ""
    fields = beads.parse_description_fields(text)
    return lifecycle.normalize_review_state(fields.get("pr_state"))


def _issue_has_active_pr_lifecycle(issue: dict[str, object]) -> bool:
    return lifecycle.is_active_pr_lifecycle_state(_changeset_review_state(issue))


def _load_changeset_issue(
    changeset_id: str, *, beads_root: Path, repo_root: Path
) -> dict[str, object] | None:
    issues = beads.run_bd_json(["show", changeset_id], beads_root=beads_root, cwd=repo_root)
    if not issues:
        return None
    issue = issues[0]
    if not isinstance(issue, dict):
        return None
    return issue


def _close_guard_allows(
    changeset_id: str,
    *,
    beads_root: Path,
    repo_root: Path,
    issue: dict[str, object] | None = None,
) -> bool:
    candidate = issue
    if candidate is None or "description" not in candidate:
        candidate = _load_changeset_issue(changeset_id, beads_root=beads_root, repo_root=repo_root)
    if candidate is None:
        return True
    if not _issue_has_active_pr_lifecycle(candidate):
        return True
    mark_changeset_in_progress(changeset_id, beads_root=beads_root, repo_root=repo_root)
    return False


def mark_changeset_in_progress(changeset_id: str, *, beads_root: Path, repo_root: Path) -> None:
    beads.run_bd_command(
        ["update", changeset_id, "--status", "in_progress"],
        beads_root=beads_root,
        cwd=repo_root,
    )


def mark_changeset_closed(changeset_id: str, *, beads_root: Path, repo_root: Path) -> None:
    if not _close_guard_allows(changeset_id, beads_root=beads_root, repo_root=repo_root):
        return
    beads.run_bd_command(
        [
            "update",
            changeset_id,
            "--status",
            "closed",
        ],
        beads_root=beads_root,
        cwd=repo_root,
    )
    beads.reconcile_closed_issue_exported_github_tickets(
        changeset_id,
        beads_root=beads_root,
        cwd=repo_root,
    )


def mark_changeset_merged(changeset_id: str, *, beads_root: Path, repo_root: Path) -> None:
    beads.run_bd_command(
        [
            "update",
            changeset_id,
            "--status",
            "closed",
            "--add-label",
            "cs:merged",
            "--remove-label",
            "cs:abandoned",
        ],
        beads_root=beads_root,
        cwd=repo_root,
    )
    beads.reconcile_closed_issue_exported_github_tickets(
        changeset_id,
        beads_root=beads_root,
        cwd=repo_root,
    )


def mark_changeset_abandoned(changeset_id: str, *, beads_root: Path, repo_root: Path) -> None:
    beads.run_bd_command(
        [
            "update",
            changeset_id,
            "--status",
            "closed",
            "--add-label",
            "cs:abandoned",
            "--remove-label",
            "cs:merged",
        ],
        beads_root=beads_root,
        cwd=repo_root,
    )
    beads.reconcile_closed_issue_exported_github_tickets(
        changeset_id,
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
        canonical_status = lifecycle.canonical_lifecycle_status(issue.get("status"))
        if canonical_status != "closed":
            continue
        status = str(issue.get("status") or "").strip().lower()
        if status == "closed":
            continue
        if has_open_descendant_changesets(issue_id):
            continue
        if not _close_guard_allows(
            issue_id,
            beads_root=beads_root,
            repo_root=repo_root,
            issue=issue,
        ):
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
        canonical_status = lifecycle.canonical_lifecycle_status(issue.get("status"))
        if canonical_status != "deferred":
            continue
        beads.run_bd_command(
            [
                "update",
                issue_id,
                "--status",
                "open",
            ],
            beads_root=beads_root,
            cwd=repo_root,
        )
        promoted.append(issue_id)
    return promoted

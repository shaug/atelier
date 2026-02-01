"""Implementation for the ``atelier work`` command.

Starts a worker session by selecting an epic and its next ready changeset.
"""

from __future__ import annotations

import os
from pathlib import Path

from .. import beads, config
from ..io import die, prompt, say
from .resolve import resolve_current_project_with_repo_root

_MODE_VALUES = {"prompt", "auto"}


def _normalize_mode(value: str | None) -> str:
    if value is None:
        value = os.environ.get("ATELIER_MODE", "prompt")
    normalized = value.strip().lower()
    if normalized not in _MODE_VALUES:
        die("mode must be one of: prompt, auto")
    return normalized


def _issue_labels(issue: dict[str, object]) -> set[str]:
    labels = issue.get("labels")
    if not isinstance(labels, list):
        return set()
    return {str(label) for label in labels if label is not None}


def _filter_epics(issues: list[dict[str, object]]) -> list[dict[str, object]]:
    filtered: list[dict[str, object]] = []
    for issue in issues:
        status = str(issue.get("status") or "")
        if status not in {"open", "in_progress"}:
            continue
        labels = _issue_labels(issue)
        if "at:draft" in labels:
            continue
        filtered.append(issue)
    return filtered


def _list_epics(*, beads_root: Path, repo_root: Path) -> list[dict[str, object]]:
    return beads.run_bd_json(
        ["list", "--label", "at:epic"], beads_root=beads_root, cwd=repo_root
    )


def _select_epic_prompt(issues: list[dict[str, object]]) -> str:
    epics = _filter_epics(issues)
    if not epics:
        die("no eligible epics found")
    say("Available epics:")
    for issue in epics:
        issue_id = issue.get("id") or ""
        status = issue.get("status") or "unknown"
        title = issue.get("title") or ""
        say(f"- {issue_id} [{status}] {title}")
    selection = prompt("Epic id")
    selection = selection.strip()
    if not selection:
        die("epic id is required")
    valid_ids = {str(issue.get("id")) for issue in epics if issue.get("id")}
    if selection not in valid_ids:
        die(f"unknown epic id: {selection}")
    return selection


def _select_epic_auto(*, beads_root: Path, repo_root: Path) -> str:
    ready = beads.run_bd_json(
        [
            "list",
            "--label",
            "at:epic",
            "--ready",
            "--no-assignee",
            "--limit",
            "1",
        ],
        beads_root=beads_root,
        cwd=repo_root,
    )
    ready = _filter_epics(ready)
    if ready:
        return str(ready[0].get("id"))
    in_progress = beads.run_bd_json(
        [
            "list",
            "--label",
            "at:epic",
            "--status",
            "in_progress",
            "--limit",
            "1",
        ],
        beads_root=beads_root,
        cwd=repo_root,
    )
    in_progress = _filter_epics(in_progress)
    if in_progress:
        return str(in_progress[0].get("id"))
    die("no eligible epics found")


def _next_changeset(
    *, epic_id: str, beads_root: Path, repo_root: Path
) -> dict[str, object]:
    changesets = beads.run_bd_json(
        ["ready", "--parent", epic_id, "--label", "at:changeset"],
        beads_root=beads_root,
        cwd=repo_root,
    )
    if not changesets:
        die(f"no ready changesets found for epic {epic_id}")
    return changesets[0]


def start_worker(args: object) -> None:
    """Start a worker session by selecting an epic and changeset."""
    project_root, _project_config, _enlistment, repo_root = (
        resolve_current_project_with_repo_root()
    )
    beads_root = config.resolve_beads_root(project_root, repo_root)

    epic_id = getattr(args, "epic_id", None)
    mode = _normalize_mode(getattr(args, "mode", None))

    if epic_id:
        selected_epic = str(epic_id).strip()
        if not selected_epic:
            die("epic id must not be empty")
    elif mode == "auto":
        selected_epic = _select_epic_auto(beads_root=beads_root, repo_root=repo_root)
    else:
        issues = _list_epics(beads_root=beads_root, repo_root=repo_root)
        selected_epic = _select_epic_prompt(issues)

    say(f"Selected epic: {selected_epic}")
    changeset = _next_changeset(
        epic_id=selected_epic, beads_root=beads_root, repo_root=repo_root
    )
    changeset_id = changeset.get("id") or ""
    changeset_title = changeset.get("title") or ""
    say(f"Next changeset: {changeset_id} {changeset_title}")

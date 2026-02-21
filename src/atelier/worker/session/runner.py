"""Worker session runner helpers shared by command orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class ChangesetSelection:
    issue: dict[str, object] | None
    selected_override: str


def select_changeset(
    *,
    selected_epic: str,
    startup_changeset_id: str | None,
    beads_root: Path,
    repo_root: Path,
    repo_slug: str | None,
    branch_pr: bool,
    branch_pr_strategy: object,
    git_path: str | None,
    run_bd_json: Callable[..., list[dict[str, object]]],
    resolve_epic_id_for_changeset: Callable[..., str | None],
    next_changeset: Callable[..., dict[str, object] | None],
) -> ChangesetSelection:
    """Resolve explicit startup changeset override, then fallback to next-ready."""
    selected_override = (
        str(startup_changeset_id).strip() if startup_changeset_id else ""
    )
    changeset: dict[str, object] | None = None
    if selected_override:
        override_issue = run_bd_json(
            ["show", selected_override], beads_root=beads_root, cwd=repo_root
        )
        if override_issue:
            resolved_epic = resolve_epic_id_for_changeset(
                override_issue[0], beads_root=beads_root, repo_root=repo_root
            )
            if resolved_epic == selected_epic:
                changeset = override_issue[0]
    if changeset is None:
        changeset = next_changeset(
            epic_id=selected_epic,
            beads_root=beads_root,
            repo_root=repo_root,
            repo_slug=repo_slug,
            branch_pr=branch_pr,
            branch_pr_strategy=branch_pr_strategy,
            git_path=git_path,
        )
    return ChangesetSelection(issue=changeset, selected_override=selected_override)

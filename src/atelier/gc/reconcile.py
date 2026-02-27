"""Reconcile preview for GC."""

from __future__ import annotations

from pathlib import Path

from .. import beads, worktrees
from .common import issue_integrated_sha, normalize_branch, try_show_issue


def reconcile_preview_lines(
    epic_id: str,
    changesets: list[str],
    *,
    project_dir: Path | None,
    beads_root: Path,
    repo_root: Path,
) -> tuple[str, ...]:
    lines: list[str] = []
    if project_dir is not None:
        mapping = worktrees.load_mapping(worktrees.mapping_path(project_dir, epic_id))
        if mapping is not None:
            branch_values = [mapping.root_branch, *mapping.changesets.values()]
            branches = sorted({value for value in branch_values if value})
            worktree_values = [
                mapping.worktree_path,
                *mapping.changeset_worktrees.values(),
            ]
            worktree_paths = sorted({value for value in worktree_values if value})
            lines.append(
                f"mapped branches ({len(branches)}): "
                + (", ".join(branches) if branches else "(none)")
            )
            lines.append(
                f"mapped worktrees ({len(worktree_paths)}): "
                + (", ".join(worktree_paths) if worktree_paths else "(none)")
            )
    epic_issue = try_show_issue(epic_id, beads_root=beads_root, cwd=repo_root)
    if epic_issue:
        description_raw = epic_issue.get("description")
        description = description_raw if isinstance(description_raw, str) else None
        fields = beads.parse_description_fields(description)
        root_branch = normalize_branch(fields.get("workspace.root_branch"))
        if not root_branch:
            root_branch = normalize_branch(fields.get("changeset.root_branch"))
        parent_branch = normalize_branch(fields.get("workspace.parent_branch"))
        if not parent_branch:
            parent_branch = normalize_branch(fields.get("changeset.parent_branch"))
        if root_branch or parent_branch:
            lines.append(
                f"final integration: {root_branch or 'unset'} -> {parent_branch or 'unset'}"
            )
    if changesets:
        lines.append(f"changesets to reconcile: {', '.join(changesets)}")
    for changeset_id in changesets:
        issue = try_show_issue(changeset_id, beads_root=beads_root, cwd=repo_root)
        if not issue:
            lines.append(f"{changeset_id}: status=unknown integrated_sha=missing")
            continue
        status = str(issue.get("status") or "unknown")
        integrated_sha = issue_integrated_sha(issue) or "missing"
        lines.append(f"{changeset_id}: status={status} integrated_sha={integrated_sha}")
    return tuple(lines)

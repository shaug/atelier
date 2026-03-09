"""Reconcile preview for GC."""

from __future__ import annotations

from pathlib import Path

from .. import beads, config, prs, worktrees
from ..lib.beads import IssueRecord, build_sync_beads_client
from ..worker import stale_pr_lifecycle
from .common import normalize_branch, try_show_issue


def _issue_integrated_sha(issue: IssueRecord) -> str | None:
    fields = beads.parse_description_fields(issue.description)
    integrated = fields.get("changeset.integrated_sha")
    if isinstance(integrated, str):
        value = integrated.strip()
        if value and value.lower() != "null":
            return value
    notes = issue.extra_fields.get("notes")
    if not isinstance(notes, str) or not notes.strip():
        return None
    for line in notes.splitlines():
        if "changeset.integrated_sha" not in line:
            continue
        _prefix, _sep, suffix = line.partition(":")
        value = suffix.strip()
        if value and value.lower() != "null":
            return value
    return None


def reconcile_preview_lines(
    epic_id: str,
    changesets: list[str],
    *,
    project_dir: Path | None,
    beads_root: Path,
    repo_root: Path,
    project_config: config.ProjectConfig | None = None,
    git_path: str | None = None,
) -> tuple[str, ...]:
    lines: list[str] = []
    repo_slug: str | None = None
    if project_config is not None:
        repo_slug = prs.github_repo_slug(
            project_config.project.origin or project_config.project.repo_url
        )
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
    client = build_sync_beads_client(beads_root=beads_root, cwd=repo_root)
    epic_issue = try_show_issue(epic_id, client=client)
    if epic_issue:
        fields = beads.parse_description_fields(epic_issue.description)
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
        issue = try_show_issue(changeset_id, client=client)
        if not issue:
            lines.append(f"{changeset_id}: status=unknown integrated_sha=missing")
            continue
        status = issue.status or "unknown"
        integrated_sha = _issue_integrated_sha(issue) or "missing"
        lines.append(f"{changeset_id}: status={status} integrated_sha={integrated_sha}")
        if project_config is not None and project_config.branch.pr:
            classification = stale_pr_lifecycle.classify_stale_terminal_pr_lifecycle(
                issue.model_dump(mode="json", by_alias=True, exclude_none=True),
                repo_slug=repo_slug,
                repo_root=repo_root,
                branch_pr=True,
                git_path=git_path,
            )
            if classification.is_candidate or classification.is_anomaly:
                lines.append(
                    f"{changeset_id}: {stale_pr_lifecycle.format_operator_triage(classification)}"
                )
    return tuple(lines)

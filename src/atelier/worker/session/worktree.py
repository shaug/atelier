"""Worker session worktree preparation helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ... import beads, changeset_fields, git, worktrees


@dataclass(frozen=True)
class WorktreePreparation:
    epic_worktree_path: Path | None
    changeset_worktree_path: Path | None
    branch: str | None


@dataclass(frozen=True)
class WorktreePreparationContext:
    dry_run: bool
    project_data_dir: Path
    repo_root: Path
    beads_root: Path
    selected_epic: str
    changeset_id: str
    root_branch_value: str
    changeset_parent_branch: str
    allow_parent_branch_override: bool
    git_path: str | None


class WorktreePreparationControl(Protocol):
    """Runtime logging hooks used by worktree preparation."""

    def say(self, message: str) -> None: ...

    def dry_run_log(self, message: str) -> None: ...


def _issue_labels(issue: dict[str, object]) -> set[str]:
    labels = issue.get("labels")
    if not isinstance(labels, list):
        return set()
    return {str(label) for label in labels if label}


def _mapping_ownership_from_beads(
    *, beads_root: Path, repo_root: Path
) -> tuple[dict[str, str], dict[str, str]]:
    owner_by_changeset: dict[str, str] = {}
    epic_root_branches: dict[str, str] = {}
    epic_issues = beads.run_bd_json(
        ["list", "--label", "at:epic", "--all"], beads_root=beads_root, cwd=repo_root
    )
    for issue in epic_issues:
        issue_id = issue.get("id")
        if not isinstance(issue_id, str):
            continue
        epic_id = issue_id.strip()
        if not epic_id:
            continue
        root_branch = beads.extract_workspace_root_branch(issue)
        if root_branch:
            epic_root_branches[epic_id] = root_branch
        labels = _issue_labels(issue)
        if "at:changeset" in labels:
            owner_by_changeset.setdefault(epic_id, epic_id)
        descendants = beads.list_descendant_changesets(
            epic_id,
            beads_root=beads_root,
            cwd=repo_root,
            include_closed=True,
        )
        for descendant in descendants:
            descendant_id = descendant.get("id")
            if not isinstance(descendant_id, str):
                continue
            normalized_descendant = descendant_id.strip()
            if not normalized_descendant:
                continue
            owner_by_changeset.setdefault(normalized_descendant, epic_id)
    return owner_by_changeset, epic_root_branches


def _normalize_branch(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized or normalized.lower() == "null":
        return None
    return normalized


def _reconcile_epic_changeset_lineage(
    *,
    selected_epic: str,
    changeset_id: str,
    canonical_root_branch: str,
    beads_root: Path,
    repo_root: Path,
    control: WorktreePreparationControl,
) -> None:
    issues = beads.run_bd_json(["show", changeset_id], beads_root=beads_root, cwd=repo_root)
    if not issues:
        raise RuntimeError(
            "epic-as-changeset metadata drift blocked: "
            f"unable to load changeset metadata for {changeset_id!r}"
        )
    issue = issues[0]
    workspace_root = _normalize_branch(beads.extract_workspace_root_branch(issue))
    metadata_root = _normalize_branch(changeset_fields.root_branch(issue))
    metadata_work = _normalize_branch(changeset_fields.work_branch(issue))
    canonical = _normalize_branch(canonical_root_branch)
    if canonical is None:
        raise RuntimeError(
            "epic-as-changeset metadata drift blocked: missing canonical root branch metadata"
        )

    if (
        workspace_root is None
        and metadata_root is None
        and metadata_work is not None
        and metadata_work != canonical
    ):
        raise RuntimeError(
            "epic-as-changeset metadata drift blocked: "
            f"workspace.root_branch and changeset.root_branch are unset, "
            f"but changeset.work_branch={metadata_work!r} conflicts with "
            f"canonical root {canonical!r}"
        )

    conflicting_metadata = {
        value
        for value in (metadata_root, metadata_work)
        if value is not None and value != canonical
    }
    if len(conflicting_metadata) > 1:
        raise RuntimeError(
            "epic-as-changeset metadata drift blocked: "
            f"workspace.root_branch={workspace_root!r}, "
            f"changeset.root_branch={metadata_root!r}, "
            f"changeset.work_branch={metadata_work!r}, "
            f"canonical={canonical!r}"
        )

    if workspace_root is None:
        beads.update_workspace_root_branch(
            selected_epic,
            canonical,
            beads_root=beads_root,
            cwd=repo_root,
            allow_override=True,
        )
        control.say(f"Reconciled workspace.root_branch for {selected_epic}: {canonical}")

    if metadata_root != canonical or metadata_work != canonical:
        beads.update_changeset_branch_metadata(
            changeset_id,
            root_branch=canonical,
            parent_branch=None,
            work_branch=canonical,
            beads_root=beads_root,
            cwd=repo_root,
            allow_override=True,
        )
        control.say(
            f"Reconciled epic-as-changeset lineage for {changeset_id}: "
            f"root={canonical}, work={canonical}"
        )


def prepare_worktrees(
    *,
    context: WorktreePreparationContext,
    control: WorktreePreparationControl,
) -> WorktreePreparation:
    """Ensure epic/changeset worktrees and branch metadata exist."""
    dry_run = context.dry_run
    project_data_dir = context.project_data_dir
    repo_root = context.repo_root
    beads_root = context.beads_root
    selected_epic = context.selected_epic
    changeset_id = context.changeset_id
    root_branch_value = context.root_branch_value
    changeset_parent_branch = context.changeset_parent_branch
    allow_parent_branch_override = context.allow_parent_branch_override
    git_path = context.git_path
    epic_worktree_path: Path | None = None
    changeset_worktree_path: Path | None = None
    branch: str | None = None
    epic_is_changeset = bool(changeset_id) and changeset_id == selected_epic

    if dry_run:
        mapping = None
        mapping_path = worktrees.mapping_path(project_data_dir, selected_epic)
        if mapping_path.exists():
            mapping = worktrees.load_mapping(mapping_path)
        epic_worktree_path = (
            project_data_dir / mapping.worktree_path
            if mapping and mapping.worktree_path
            else worktrees.worktree_dir(project_data_dir, selected_epic)
        )
        if epic_is_changeset and root_branch_value:
            branch = root_branch_value
        elif mapping and changeset_id in mapping.changesets:
            branch = mapping.changesets[changeset_id]
        elif root_branch_value:
            branch = worktrees.derive_changeset_branch(root_branch_value, changeset_id)
        if epic_is_changeset:
            changeset_worktree_path = epic_worktree_path
        else:
            changeset_relpath = None
            if mapping and changeset_id in mapping.changeset_worktrees:
                changeset_relpath = mapping.changeset_worktrees[changeset_id]
            elif changeset_id:
                changeset_relpath = worktrees.changeset_worktree_relpath(changeset_id)
            if changeset_relpath:
                changeset_worktree_path = project_data_dir / changeset_relpath
        control.dry_run_log(f"Epic worktree: {epic_worktree_path}")
        if changeset_worktree_path is not None:
            control.dry_run_log(f"Changeset worktree: {changeset_worktree_path}")
        else:
            control.dry_run_log("Changeset worktree: <unknown>")
        control.dry_run_log(f"Changeset branch: {branch or '<unknown>'}")
        if changeset_id:
            control.dry_run_log(
                "Would update changeset branch metadata "
                f"(root={root_branch_value!r}, "
                f"parent={changeset_parent_branch!r}, "
                f"work={branch!r}, "
                f"allow_override={allow_parent_branch_override!r})."
            )
        control.dry_run_log("Would ensure git worktrees and checkout.")
        return WorktreePreparation(
            epic_worktree_path=epic_worktree_path,
            changeset_worktree_path=changeset_worktree_path,
            branch=branch,
        )

    owner_by_changeset, epic_root_branches = _mapping_ownership_from_beads(
        beads_root=beads_root,
        repo_root=repo_root,
    )
    changed_mappings = worktrees.reconcile_mapping_ownership(
        project_data_dir,
        owner_by_changeset=owner_by_changeset,
        epic_root_branches=epic_root_branches,
    )
    if changed_mappings:
        control.say("Reconciled mapping ownership: " + ", ".join(changed_mappings))

    epic_worktree_path = worktrees.ensure_git_worktree(
        project_data_dir,
        repo_root,
        selected_epic,
        root_branch=root_branch_value,
        git_path=git_path,
    )
    branch, mapping = worktrees.ensure_changeset_branch(
        project_data_dir,
        selected_epic,
        changeset_id,
        root_branch=root_branch_value,
        repo_root=repo_root,
        git_path=git_path,
    )
    beads.update_worktree_path(
        selected_epic,
        mapping.worktree_path,
        beads_root=beads_root,
        cwd=repo_root,
    )
    if epic_is_changeset:
        _reconcile_epic_changeset_lineage(
            selected_epic=selected_epic,
            changeset_id=changeset_id,
            canonical_root_branch=root_branch_value,
            beads_root=beads_root,
            repo_root=repo_root,
            control=control,
        )
    if epic_is_changeset:
        changeset_worktree_path = epic_worktree_path
    else:
        changeset_worktree_path = worktrees.ensure_changeset_worktree(
            project_data_dir,
            repo_root,
            selected_epic,
            changeset_id,
            branch=branch,
            root_branch=root_branch_value,
            parent_branch=changeset_parent_branch,
            git_path=git_path,
        )
    worktrees.ensure_changeset_checkout(
        changeset_worktree_path,
        branch,
        root_branch=root_branch_value,
        parent_branch=changeset_parent_branch,
        git_path=git_path,
    )
    if changeset_id:
        root_base = git.git_rev_parse(changeset_worktree_path, root_branch_value, git_path=git_path)
        parent_base = git.git_rev_parse(
            changeset_worktree_path,
            changeset_parent_branch,
            git_path=git_path,
        )
        beads.update_changeset_branch_metadata(
            changeset_id,
            root_branch=root_branch_value,
            parent_branch=changeset_parent_branch,
            work_branch=branch,
            root_base=None if allow_parent_branch_override else root_base,
            parent_base=parent_base,
            beads_root=beads_root,
            cwd=repo_root,
            allow_override=allow_parent_branch_override,
        )
    control.say(f"Epic worktree: {epic_worktree_path}")
    control.say(f"Changeset worktree: {changeset_worktree_path}")
    control.say(f"Changeset branch: {branch}")
    return WorktreePreparation(
        epic_worktree_path=epic_worktree_path,
        changeset_worktree_path=changeset_worktree_path,
        branch=branch,
    )

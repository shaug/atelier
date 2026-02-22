"""Worker session worktree preparation helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ... import beads, git, worktree_hooks, worktrees


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
    git_path: str | None


class WorktreePreparationControl(Protocol):
    """Runtime logging hooks used by worktree preparation."""

    def say(self, message: str) -> None: ...

    def dry_run_log(self, message: str) -> None: ...


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
                f"work={branch!r})."
            )
        control.dry_run_log("Would ensure git worktrees and checkout.")
        control.dry_run_log("Would bootstrap conventional-commit git hooks.")
        return WorktreePreparation(
            epic_worktree_path=epic_worktree_path,
            changeset_worktree_path=changeset_worktree_path,
            branch=branch,
        )

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
    )
    beads.update_worktree_path(
        selected_epic,
        mapping.worktree_path,
        beads_root=beads_root,
        cwd=repo_root,
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
    hook_targets = {epic_worktree_path}
    if changeset_worktree_path is not None:
        hook_targets.add(changeset_worktree_path)
    for hook_target in sorted(hook_targets, key=lambda path: str(path)):
        worktree_hooks.bootstrap_conventional_commit_hook(
            hook_target,
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
            root_base=root_base,
            parent_base=parent_base,
            beads_root=beads_root,
            cwd=repo_root,
        )
    control.say(f"Epic worktree: {epic_worktree_path}")
    control.say(f"Changeset worktree: {changeset_worktree_path}")
    control.say(f"Changeset branch: {branch}")
    return WorktreePreparation(
        epic_worktree_path=epic_worktree_path,
        changeset_worktree_path=changeset_worktree_path,
        branch=branch,
    )

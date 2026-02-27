"""GC operations for orphaned worktrees and resolved epic artifacts."""

from __future__ import annotations

from pathlib import Path

from .. import beads, git, worktrees
from ..io import die, say, select
from .common import (
    branch_integrated_into_target,
    branch_lookup_ref,
    is_merged_closed_changeset,
    issue_labels,
    log_debug,
    normalize_branch,
    run_git_gc_command,
    try_show_issue,
    workspace_branch_from_labels,
)
from .models import GcAction


def collect_resolved_epic_artifacts(
    *,
    project_dir: Path,
    beads_root: Path,
    repo_root: Path,
    git_path: str,
    assume_yes: bool = False,
) -> list[GcAction]:
    actions: list[GcAction] = []
    meta_dir = worktrees.worktrees_root(project_dir) / worktrees.METADATA_DIRNAME
    if not meta_dir.exists():
        return actions
    default_branch = git.git_default_branch(repo_root, git_path=git_path) or ""
    for path in meta_dir.glob("*.json"):
        mapping = worktrees.load_mapping(path)
        if not mapping:
            continue
        epic_id = mapping.epic_id
        if not epic_id:
            continue
        epic = try_show_issue(epic_id, beads_root=beads_root, cwd=repo_root)
        if not epic:
            continue
        status = str(epic.get("status") or "").strip().lower()
        if status not in {"closed", "done"}:
            continue

        description = epic.get("description")
        fields = beads.parse_description_fields(description if isinstance(description, str) else "")
        parent_branch = normalize_branch(fields.get("workspace.parent_branch"))
        if not parent_branch:
            parent_branch = normalize_branch(fields.get("changeset.parent_branch"))
        if not parent_branch:
            parent_branch = normalize_branch(default_branch)
        if not parent_branch:
            continue

        target_local, target_remote = branch_lookup_ref(repo_root, parent_branch, git_path=git_path)
        target_ref = target_local or target_remote
        if not target_ref:
            continue

        branches = {mapping.root_branch, *mapping.changesets.values()}
        prunable_branches = {
            branch
            for branch in branches
            if branch and branch != parent_branch and branch != default_branch
        }
        if any(
            not branch_integrated_into_target(
                repo_root, branch=branch, target_ref=target_ref, git_path=git_path
            )
            for branch in prunable_branches
        ):
            continue

        relpaths = {
            relpath
            for relpath in [
                mapping.worktree_path,
                *mapping.changeset_worktrees.values(),
            ]
            if relpath
        }
        existing_worktrees = []
        for relpath in relpaths:
            worktree_path = Path(relpath)
            if not worktree_path.is_absolute():
                worktree_path = project_dir / worktree_path
            if worktree_path.exists() and (worktree_path / ".git").exists():
                existing_worktrees.append(worktree_path)

        has_prunable_branch_ref = False
        for branch in prunable_branches:
            local_ref, remote_ref = branch_lookup_ref(repo_root, branch, git_path=git_path)
            if local_ref or remote_ref:
                has_prunable_branch_ref = True
                break
        if not existing_worktrees and not has_prunable_branch_ref:
            continue

        description_text = f"Prune resolved epic artifacts for {epic_id}"
        changeset_worktree_summary = ", ".join(sorted(mapping.changeset_worktrees.values()))
        if not changeset_worktree_summary:
            changeset_worktree_summary = "(none)"
        branch_summary = ", ".join(sorted(prunable_branches))
        if not branch_summary:
            branch_summary = "(none)"
        details = (
            f"epic worktree: {mapping.worktree_path}",
            f"changeset worktrees: {changeset_worktree_summary}",
            f"branches to prune: {branch_summary}",
            f"integration target: {target_ref}",
        )

        def _apply_cleanup(
            epic_value: str = epic_id,
            mapping_path: Path = path,
            worktree_paths: list[Path] = list(existing_worktrees),
            branches_to_prune: list[str] = sorted(prunable_branches),
        ) -> None:
            log_debug(
                f"cleanup resolved epic start epic={epic_value} "
                f"worktrees={len(worktree_paths)} branches={len(branches_to_prune)}"
            )
            for worktree_path in worktree_paths:
                status_lines = git.git_status_porcelain(worktree_path, git_path=git_path)
                force_remove = False
                if status_lines:
                    say(f"Resolved worktree has local changes: {worktree_path}")
                    for line in status_lines[:20]:
                        say(f"- {line}")
                    if len(status_lines) > 20:
                        say(f"- ... ({len(status_lines) - 20} more)")
                    if assume_yes:
                        force_remove = True
                    else:
                        choice = select(
                            "Resolved worktree cleanup action",
                            ("force-remove", "exit"),
                            "exit",
                        )
                        if choice != "force-remove":
                            die("gc aborted by user")
                        force_remove = True
                log_debug(f"removing resolved worktree path={worktree_path} force={force_remove}")
                args = ["worktree", "remove"]
                if force_remove:
                    args.append("--force")
                args.append(str(worktree_path))
                ok, detail = run_git_gc_command(args, repo_root=repo_root, git_path=git_path)
                if not ok:
                    die(detail)

            current_branch = git.git_current_branch(repo_root, git_path=git_path)
            for branch in branches_to_prune:
                local_ref, remote_ref = branch_lookup_ref(repo_root, branch, git_path=git_path)
                if remote_ref:
                    log_debug(f"deleting remote branch branch={branch} epic={epic_value}")
                    run_git_gc_command(
                        ["push", "origin", "--delete", branch],
                        repo_root=repo_root,
                        git_path=git_path,
                    )
                if local_ref and current_branch != branch:
                    log_debug(f"deleting local branch branch={branch} epic={epic_value}")
                    run_git_gc_command(
                        ["branch", "-D", branch],
                        repo_root=repo_root,
                        git_path=git_path,
                    )
            mapping_path.unlink(missing_ok=True)
            log_debug(f"cleanup resolved epic complete epic={epic_value}")

        actions.append(
            GcAction(
                description=description_text,
                apply=_apply_cleanup,
                details=details,
            )
        )
    return actions


def collect_closed_workspace_branches_without_mapping(
    *,
    project_dir: Path,
    beads_root: Path,
    repo_root: Path,
    git_path: str,
) -> list[GcAction]:
    actions: list[GcAction] = []
    default_branch = git.git_default_branch(repo_root, git_path=git_path) or ""
    issues = beads.list_all_changesets(
        beads_root=beads_root,
        cwd=repo_root,
        include_closed=True,
    )
    for issue in issues:
        issue_id = issue.get("id")
        if not isinstance(issue_id, str) or not issue_id.strip():
            continue
        status = str(issue.get("status") or "").strip().lower()
        if status not in {"closed", "done"}:
            continue
        labels = issue_labels(issue)
        if not is_merged_closed_changeset(issue):
            continue
        workspace_branch = workspace_branch_from_labels(labels)
        if not workspace_branch:
            continue
        mapping_path = worktrees.mapping_path(project_dir, issue_id.strip())
        if mapping_path.exists():
            continue

        description = issue.get("description")
        fields = beads.parse_description_fields(description if isinstance(description, str) else "")
        root_branch = normalize_branch(fields.get("workspace.root_branch"))
        if not root_branch:
            root_branch = normalize_branch(fields.get("changeset.root_branch"))
        if not root_branch:
            root_branch = normalize_branch(workspace_branch)
        parent_branch = normalize_branch(fields.get("workspace.parent_branch"))
        if not parent_branch:
            parent_branch = normalize_branch(fields.get("changeset.parent_branch"))
        if not parent_branch or parent_branch == root_branch:
            parent_branch = normalize_branch(default_branch) or parent_branch
        if not root_branch or not parent_branch:
            continue

        target_local, target_remote = branch_lookup_ref(repo_root, parent_branch, git_path=git_path)
        target_ref = target_local or target_remote
        if not target_ref:
            continue

        work_branch = normalize_branch(fields.get("changeset.work_branch"))
        candidate_values = [root_branch, work_branch, workspace_branch]
        candidate_branches = {value for value in candidate_values if value}
        prunable_branches = {
            branch
            for branch in candidate_branches
            if branch and branch != parent_branch and branch != default_branch
        }
        if not prunable_branches:
            continue
        if any(
            not branch_integrated_into_target(
                repo_root, branch=branch, target_ref=target_ref, git_path=git_path
            )
            for branch in prunable_branches
        ):
            continue

        has_prunable_branch_ref = False
        for branch in prunable_branches:
            local_ref, remote_ref = branch_lookup_ref(repo_root, branch, git_path=git_path)
            if local_ref or remote_ref:
                has_prunable_branch_ref = True
                break
        if not has_prunable_branch_ref:
            continue

        description_text = f"Prune closed workspace branches for {issue_id.strip()}"
        details = (
            f"workspace branch: {workspace_branch}",
            f"root branch: {root_branch}",
            f"work branch: {work_branch or '(none)'}",
            f"integration target: {target_ref}",
            f"branches to prune: {', '.join(sorted(prunable_branches))}",
        )

        def _apply_cleanup(
            branches_to_prune: list[str] = sorted(prunable_branches),
        ) -> None:
            current_branch = git.git_current_branch(repo_root, git_path=git_path)
            for branch in branches_to_prune:
                local_ref, remote_ref = branch_lookup_ref(repo_root, branch, git_path=git_path)
                if remote_ref:
                    log_debug(f"deleting remote workspace branch branch={branch}")
                    run_git_gc_command(
                        ["push", "origin", "--delete", branch],
                        repo_root=repo_root,
                        git_path=git_path,
                    )
                if local_ref and current_branch != branch:
                    log_debug(f"deleting local workspace branch branch={branch}")
                    run_git_gc_command(
                        ["branch", "-D", branch],
                        repo_root=repo_root,
                        git_path=git_path,
                    )

        actions.append(
            GcAction(
                description=description_text,
                apply=_apply_cleanup,
                details=details,
            )
        )
    return actions


def collect_orphan_worktrees(
    *,
    project_dir: Path,
    beads_root: Path,
    repo_root: Path,
    git_path: str,
    assume_yes: bool = False,
) -> list[GcAction]:
    actions: list[GcAction] = []
    meta_dir = worktrees.worktrees_root(project_dir) / worktrees.METADATA_DIRNAME
    if not meta_dir.exists():
        return actions
    for path in meta_dir.glob("*.json"):
        mapping = worktrees.load_mapping(path)
        if not mapping:
            continue
        epic_id = mapping.epic_id
        if not epic_id:
            continue
        epic = try_show_issue(epic_id, beads_root=beads_root, cwd=repo_root)
        if epic is not None:
            continue
        description = f"Remove orphaned worktree for epic {epic_id}"

        def _apply_remove(
            epic: str = epic_id,
            mapping_path: Path = path,
            mapping_worktree_path: str = mapping.worktree_path,
        ) -> None:
            worktree_path = Path(mapping_worktree_path)
            if not worktree_path.is_absolute():
                worktree_path = project_dir / worktree_path
            status_lines = git.git_status_porcelain(worktree_path, git_path=git_path)
            force_remove = False
            if status_lines:
                say(f"Orphaned worktree has local changes: {worktree_path}")
                for line in status_lines[:20]:
                    say(f"- {line}")
                if len(status_lines) > 20:
                    say(f"- ... ({len(status_lines) - 20} more)")
                if assume_yes:
                    force_remove = True
                else:
                    choice = select(
                        "Orphaned worktree cleanup action",
                        ("force-remove", "exit"),
                        "exit",
                    )
                    if choice != "force-remove":
                        die("gc aborted by user")
                    force_remove = True
            log_debug(
                f"removing orphaned worktree epic={epic} path={worktree_path} force={force_remove}"
            )
            worktrees.remove_git_worktree(
                project_dir,
                repo_root,
                epic,
                git_path=git_path,
                force=force_remove,
            )
            mapping_path.unlink(missing_ok=True)
            log_debug(f"removed orphaned worktree epic={epic}")

        actions.append(
            GcAction(
                description=description,
                apply=_apply_remove,
                details=(
                    f"mapping: {path}",
                    f"worktree: {mapping.worktree_path}",
                ),
            )
        )
    return actions

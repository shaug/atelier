"""Remove Atelier project state for the current repository."""

from __future__ import annotations

import shutil
from pathlib import Path

from .. import config, git, worktrees
from .. import exec as exec_util
from ..io import confirm, die, say
from . import daemon as daemon_cmd
from . import gc as gc_cmd
from .resolve import resolve_current_project_with_repo_root


def _run_git(
    repo_root: Path, args: list[str], *, git_path: str
) -> tuple[bool, str | None]:
    result = exec_util.try_run_command(
        git.git_command(["-C", str(repo_root), *args], git_path=git_path)
    )
    if result is None:
        return False, "missing required command: git"
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        return False, detail or f"command failed: git {' '.join(args)}"
    return True, (result.stdout or "").strip() or None


def _stop_project_daemons(project_dir: Path, *, beads_root: Path) -> tuple[bool, bool]:
    stopped_worker = daemon_cmd._stop_worker(project_dir)
    db_path = daemon_cmd._resolve_beads_db(beads_root)
    stopped_bd = False
    if db_path is not None and project_dir.exists():
        cmd = ["bd", "daemon", "stop", "--db", str(db_path)]
        result = exec_util.try_run_command(
            cmd, cwd=project_dir, env=daemon_cmd.beads.beads_env(beads_root)
        )
        stopped_bd = bool(result and result.returncode == 0)
    return stopped_worker, stopped_bd


def _managed_worktrees_from_git(
    *,
    repo_root: Path,
    project_data_dir: Path,
    git_path: str,
) -> list[Path]:
    managed_root = worktrees.worktrees_root(project_data_dir).resolve()
    ok, output = _run_git(
        repo_root, ["worktree", "list", "--porcelain"], git_path=git_path
    )
    if not ok or not output:
        return []
    found: set[Path] = set()
    for line in output.splitlines():
        if not line.startswith("worktree "):
            continue
        raw = line.split(" ", 1)[1].strip()
        if not raw:
            continue
        candidate = Path(raw).resolve()
        try:
            candidate.relative_to(managed_root)
        except ValueError:
            continue
        found.add(candidate)
    return sorted(found)


def _collect_mapped_branches(project_data_dir: Path) -> set[str]:
    branches: set[str] = set()
    meta_dir = worktrees.worktrees_root(project_data_dir) / worktrees.METADATA_DIRNAME
    if not meta_dir.exists():
        return branches
    for mapping_path in meta_dir.glob("*.json"):
        mapping = worktrees.load_mapping(mapping_path)
        if mapping is None:
            continue
        if mapping.root_branch:
            branches.add(mapping.root_branch)
        branches.update(branch for branch in mapping.changesets.values() if branch)
    return branches


def _remove_worktree(repo_root: Path, worktree_path: Path, *, git_path: str) -> None:
    ok, detail = _run_git(
        repo_root,
        ["worktree", "remove", "--force", str(worktree_path)],
        git_path=git_path,
    )
    if not ok:
        die(
            "failed to remove git worktree "
            f"{worktree_path}: {detail or 'unknown error'}"
        )


def _prune_worktree_registry(repo_root: Path, *, git_path: str) -> None:
    _run_git(repo_root, ["worktree", "prune"], git_path=git_path)


def _delete_branch_refs(
    repo_root: Path,
    branch: str,
    *,
    git_path: str,
) -> None:
    if git.git_ref_exists(
        repo_root, f"refs/remotes/origin/{branch}", git_path=git_path
    ):
        _run_git(repo_root, ["push", "origin", "--delete", branch], git_path=git_path)
    current_branch = git.git_current_branch(repo_root, git_path=git_path)
    if current_branch != branch and git.git_ref_exists(
        repo_root, f"refs/heads/{branch}", git_path=git_path
    ):
        _run_git(repo_root, ["branch", "-D", branch], git_path=git_path)


def remove_project(args: object) -> None:
    """Remove Atelier project state for the current repo."""
    project_root, project_config, _enlistment, repo_root = (
        resolve_current_project_with_repo_root()
    )
    project_data_dir = config.resolve_project_data_dir(project_root, project_config)
    beads_root = config.resolve_beads_root(project_data_dir, repo_root)
    git_path = config.resolve_git_path(project_config)

    yes = bool(getattr(args, "yes", False))
    dry_run = bool(getattr(args, "dry_run", False))
    run_gc = bool(getattr(args, "gc", True))
    reconcile = bool(getattr(args, "reconcile", False))
    prune_branches = bool(getattr(args, "prune_branches", False))

    if not project_data_dir.exists():
        die(f"project data dir not found: {project_data_dir}")

    managed_worktrees = _managed_worktrees_from_git(
        repo_root=repo_root, project_data_dir=project_data_dir, git_path=git_path
    )
    mapped_branches = _collect_mapped_branches(project_data_dir)

    say("Project removal preview:")
    say(f"- Project data dir: {project_data_dir}")
    say(f"- Repo root: {repo_root}")
    say(f"- Managed worktrees to remove: {len(managed_worktrees)}")
    if managed_worktrees:
        for path in managed_worktrees:
            say(f"  - {path}")
    if prune_branches:
        say(f"- Mapped branches to prune: {len(mapped_branches)}")
        for branch in sorted(mapped_branches):
            say(f"  - {branch}")
    else:
        say(
            "- Branch pruning: disabled (use --prune-branches to remove mapped branches)"
        )
    if run_gc:
        say(f"- GC before removal: enabled (reconcile={reconcile})")
    else:
        say("- GC before removal: disabled")

    if dry_run:
        say("DRY-RUN: no changes applied.")
        return

    if not yes and not confirm("Remove this Atelier project now?", default=False):
        say("Cancelled.")
        return

    stopped_worker, stopped_bd = _stop_project_daemons(
        project_data_dir, beads_root=beads_root
    )
    if stopped_worker:
        say("Stopped worker daemon.")
    if stopped_bd:
        say("Stopped bd daemon.")

    if run_gc:
        say("Running GC before removal.")
        gc_cmd.gc(
            type(
                "RemoveGcArgs",
                (),
                {
                    "stale_hours": 0.0,
                    "stale_if_missing_heartbeat": True,
                    "dry_run": False,
                    "reconcile": reconcile,
                    "yes": True,
                },
            )()
        )

    # Refresh in case GC removed some/all worktrees.
    managed_worktrees = _managed_worktrees_from_git(
        repo_root=repo_root, project_data_dir=project_data_dir, git_path=git_path
    )
    for worktree_path in managed_worktrees:
        say(f"Removing worktree: {worktree_path}")
        _remove_worktree(repo_root, worktree_path, git_path=git_path)
    if managed_worktrees:
        _prune_worktree_registry(repo_root, git_path=git_path)

    if prune_branches:
        default_branch = git.git_default_branch(repo_root, git_path=git_path)
        for branch in sorted(mapped_branches):
            if not branch or branch == default_branch:
                continue
            say(f"Pruning branch refs: {branch}")
            _delete_branch_refs(repo_root, branch, git_path=git_path)

    shutil.rmtree(project_data_dir)
    say(f"Removed Atelier project data: {project_data_dir}")

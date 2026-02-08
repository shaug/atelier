"""Changeset integration helpers for non-PR workflows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import beads, git
from . import exec as exec_util
from .io import die


@dataclass(frozen=True)
class IntegrationResult:
    root_branch: str
    work_branch: str
    integrated_sha: str
    previous_root: str | None


def integrate_changeset(
    *,
    changeset_id: str,
    worktree_path: Path,
    repo_root: Path,
    root_branch: str,
    work_branch: str,
    beads_root: Path,
    expected_root_sha: str | None = None,
    git_path: str | None = None,
) -> IntegrationResult:
    """Rebase the work branch onto root and fast-forward root with CAS."""
    if not changeset_id:
        die("changeset id must not be empty")
    if not root_branch or not work_branch:
        die("root branch and work branch must not be empty")
    if not worktree_path.exists():
        die("worktree path missing; run 'atelier work' first")
    if not (worktree_path / ".git").exists():
        die("worktree path is not a git worktree")

    exec_util.run_command(
        git.git_command(
            ["-C", str(worktree_path), "checkout", work_branch], git_path=git_path
        )
    )
    exec_util.run_command(
        git.git_command(
            ["-C", str(worktree_path), "rebase", root_branch], git_path=git_path
        )
    )

    new_head = git.git_rev_parse(worktree_path, work_branch, git_path=git_path)
    if not new_head:
        die("failed to resolve work branch head")

    expected = expected_root_sha.strip() if expected_root_sha else None
    if expected is None:
        expected = git.git_rev_parse(repo_root, root_branch, git_path=git_path)
    if not expected:
        die("failed to resolve root branch head")

    update_ref_args = [
        "-C",
        str(repo_root),
        "update-ref",
        f"refs/heads/{root_branch}",
        new_head,
        expected,
    ]
    result = exec_util.try_run_command(
        git.git_command(update_ref_args, git_path=git_path)
    )
    if result is None:
        die("missing required command: git")
    if result.returncode != 0:
        die("root branch moved; rebase required")

    beads.update_changeset_integrated_sha(
        changeset_id,
        new_head,
        beads_root=beads_root,
        cwd=repo_root,
    )
    return IntegrationResult(
        root_branch=root_branch,
        work_branch=work_branch,
        integrated_sha=new_head,
        previous_root=expected,
    )

"""Interactive helpers for workspace root branch selection."""

from __future__ import annotations

from pathlib import Path

from . import beads, branching, git
from .io import confirm, prompt, say


def prompt_root_branch(
    *,
    title: str,
    branch_prefix: str,
    beads_root: Path,
    repo_root: Path,
) -> str:
    """Prompt for a root branch name with validation and uniqueness checks."""
    suggested = branching.suggest_root_branch(title, branch_prefix)
    while True:
        root_branch = prompt("Root branch", default=suggested or None, required=True)
        root_branch = branching.normalize_root_branch(root_branch)
        if branch_prefix and not root_branch.startswith(branch_prefix):
            if confirm(
                f"Apply branch prefix '{branch_prefix}' to '{root_branch}'?",
                default=True,
            ):
                root_branch = branching.apply_branch_prefix(root_branch, branch_prefix)
        if not branching.is_valid_root_branch(root_branch):
            if not confirm(
                "Root branch is not lowercase hyphenated; use anyway?",
                default=False,
            ):
                continue

        conflicts = beads.find_epics_by_root_branch(
            root_branch, beads_root=beads_root, cwd=repo_root
        )
        blocking: list[dict[str, object]] = []
        reusable: list[dict[str, object]] = []
        for issue in conflicts:
            status = str(issue.get("status") or "").lower()
            if status in {"open", "in_progress", "ready", "planned"} or not status:
                blocking.append(issue)
            else:
                reusable.append(issue)
        if blocking:
            say("Root branch already claimed by active epics:")
            for issue in blocking:
                say(f"- {issue.get('id')} [{issue.get('status')}] {issue.get('title')}")
            say("Choose a different root branch.")
            continue
        if reusable:
            say("Root branch was previously used:")
            for issue in reusable:
                say(f"- {issue.get('id')} [{issue.get('status')}] {issue.get('title')}")
            if not confirm("Reuse this root branch?", default=False):
                continue

        remote_ref = f"refs/remotes/origin/{root_branch}"
        if git.git_ref_exists(repo_root, remote_ref):
            if not confirm(
                f"Branch {root_branch!r} exists on origin. Use anyway?",
                default=False,
            ):
                continue

        return root_branch

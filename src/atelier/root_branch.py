"""Interactive helpers for workspace root branch selection."""

from __future__ import annotations

from pathlib import Path

from . import beads, branching, git
from .io import confirm, die, prompt, say


def prompt_root_branch(
    *,
    title: str,
    branch_prefix: str,
    beads_root: Path,
    repo_root: Path,
    assume_yes: bool = False,
) -> str:
    """Prompt for a root branch name with validation and uniqueness checks."""
    suggested = branching.suggest_root_branch(title, branch_prefix)
    while True:
        if assume_yes:
            root_branch = branching.normalize_root_branch(suggested or "")
            if not root_branch:
                die("unable to choose a default root branch; rerun without --yes")
        else:
            root_branch = prompt("Root branch", default=suggested or None, required=True)
        root_branch = branching.normalize_root_branch(root_branch)
        if branch_prefix and not root_branch.startswith(branch_prefix):
            if assume_yes or confirm(
                f"Apply branch prefix '{branch_prefix}' to '{root_branch}'?",
                default=True,
            ):
                root_branch = branching.apply_branch_prefix(root_branch, branch_prefix)
        if not branching.is_valid_root_branch(root_branch):
            if assume_yes:
                die("default root branch failed validation; rerun without --yes")
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
            if assume_yes:
                die("default root branch is unavailable; rerun without --yes")
            continue
        if reusable:
            say("Root branch was previously used:")
            for issue in reusable:
                say(f"- {issue.get('id')} [{issue.get('status')}] {issue.get('title')}")
            if assume_yes:
                die("default root branch requires confirmation; rerun without --yes")
            if not confirm("Reuse this root branch?", default=False):
                continue

        remote_ref = f"refs/remotes/origin/{root_branch}"
        if git.git_ref_exists(repo_root, remote_ref):
            if assume_yes:
                die("default root branch exists on origin; rerun without --yes")
            if not confirm(
                f"Branch {root_branch!r} exists on origin. Use anyway?",
                default=False,
            ):
                continue

        return root_branch

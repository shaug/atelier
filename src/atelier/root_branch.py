"""Interactive helpers for workspace root branch selection."""

from __future__ import annotations

from pathlib import Path

from . import beads, branching, git, lifecycle
from .io import confirm, die, prompt, say


def partition_root_branch_conflicts(
    issues: list[dict[str, object]],
    *,
    owner_issue_id: str | None = None,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Split root-branch owners into active blockers and reusable history."""
    blocking: list[dict[str, object]] = []
    reusable: list[dict[str, object]] = []
    for issue in issues:
        issue_id = str(issue.get("id") or "").strip()
        if owner_issue_id and issue_id == owner_issue_id:
            continue
        labels = lifecycle.normalized_labels(issue.get("labels"))
        if lifecycle.is_active_root_branch_owner(status=issue.get("status"), labels=labels):
            blocking.append(issue)
            continue
        reusable.append(issue)
    return blocking, reusable


def prompt_root_branch(
    *,
    title: str,
    branch_prefix: str,
    epic_id: str | None = None,
    beads_root: Path,
    repo_root: Path,
    assume_yes: bool = False,
) -> str:
    """Prompt for a root branch name with validation and uniqueness checks."""
    suggested = branching.suggest_root_branch(title, branch_prefix, bead_id=epic_id)
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
        blocking, reusable = partition_root_branch_conflicts(conflicts)
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

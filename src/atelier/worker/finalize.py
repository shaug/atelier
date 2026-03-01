"""Worker finalize helpers for terminal changesets and epic closure."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from .. import beads, git
from .models import FinalizeResult


def finalize_epic_if_complete(
    *,
    epic_id: str,
    agent_id: str,
    agent_bead_id: str,
    branch_pr: bool,
    branch_history: str,
    branch_squash_message: str,
    beads_root: Path,
    repo_root: Path,
    project_data_dir: Path | None,
    squash_message_agent_spec: object | None,
    squash_message_agent_options: list[str] | None,
    squash_message_agent_home: Path | None,
    squash_message_agent_env: dict[str, str] | None,
    git_path: str | None,
    log: Callable[[str], None] | None,
    epic_ready_to_finalize: Callable[[str], bool],
    normalize_branch_value: Callable[[object], str | None],
    extract_changeset_root_branch: Callable[[dict[str, object]], str | None],
    send_planner_notification: Callable[..., None],
    resolve_epic_integration_cwd: Callable[..., Path],
    integrate_epic_root_to_parent: Callable[..., tuple[bool, str | None, str | None]],
    cleanup_epic_branches_and_worktrees: Callable[..., None],
) -> FinalizeResult:
    cleanup_keep_branches: set[str] = set()
    if not epic_ready_to_finalize(epic_id):
        return FinalizeResult(continue_running=True, reason="changeset_complete")

    if not branch_pr:
        issues = beads.run_bd_json(["show", epic_id], beads_root=beads_root, cwd=repo_root)
        if not issues:
            return FinalizeResult(continue_running=False, reason="epic_blocked_missing_metadata")
        issue = issues[0]
        raw_description = issue.get("description")
        description = raw_description if isinstance(raw_description, str) else None
        fields = beads.parse_description_fields(description)
        root_branch = normalize_branch_value(fields.get("workspace.root_branch"))
        if not root_branch:
            root_branch = normalize_branch_value(fields.get("changeset.root_branch"))
        parent_branch = normalize_branch_value(fields.get("workspace.parent_branch"))
        default_branch = git.git_default_branch(repo_root, git_path=git_path)
        if not parent_branch or (root_branch and parent_branch == root_branch):
            parent_branch = default_branch or parent_branch or root_branch

        if not root_branch or not parent_branch:
            send_planner_notification(
                subject=f"NEEDS-DECISION: Missing epic branch metadata ({epic_id})",
                body="Epic is complete but root/parent branch metadata is missing.",
                agent_id=agent_id,
                thread_id=epic_id,
                beads_root=beads_root,
                repo_root=repo_root,
                dry_run=False,
            )
            return FinalizeResult(continue_running=False, reason="epic_blocked_missing_metadata")
        cleanup_keep_branches = {parent_branch}

        beads.update_workspace_parent_branch(
            epic_id,
            parent_branch,
            beads_root=beads_root,
            cwd=repo_root,
            allow_override=True,
        )
        integration_cwd = resolve_epic_integration_cwd(
            project_data_dir=project_data_dir,
            repo_root=repo_root,
            epic_id=epic_id,
            root_branch=root_branch,
            git_path=git_path,
        )

        integrated_ok, _integrated_sha, error = integrate_epic_root_to_parent(
            epic_issue=issue,
            epic_id=epic_id,
            root_branch=root_branch,
            parent_branch=parent_branch,
            history=branch_history,
            squash_message_mode=branch_squash_message,
            squash_message_agent_spec=squash_message_agent_spec,
            squash_message_agent_options=squash_message_agent_options,
            squash_message_agent_home=squash_message_agent_home,
            squash_message_agent_env=squash_message_agent_env,
            integration_cwd=integration_cwd,
            repo_root=repo_root,
            git_path=git_path,
        )
        if not integrated_ok:
            send_planner_notification(
                subject=f"NEEDS-DECISION: Epic finalization failed ({epic_id})",
                body=(
                    "Epic changesets are complete, but final integration of "
                    f"{root_branch} -> {parent_branch} failed.\n"
                    f"Reason: {error or 'unknown error'}"
                ),
                agent_id=agent_id,
                thread_id=epic_id,
                beads_root=beads_root,
                repo_root=repo_root,
                dry_run=False,
            )
            return FinalizeResult(continue_running=False, reason="epic_blocked_finalization")

    closed = beads.close_epic_if_complete(
        epic_id, agent_bead_id, beads_root=beads_root, cwd=repo_root
    )
    if closed:
        if log:
            log(f"finalize epic: {epic_id} closed; pruning mapped artifacts")
        cleanup_epic_branches_and_worktrees(
            project_data_dir=project_data_dir,
            repo_root=repo_root,
            epic_id=epic_id,
            keep_branches=cleanup_keep_branches,
            git_path=git_path,
            log=log,
        )
    return FinalizeResult(continue_running=True, reason="changeset_complete")


def finalize_terminal_changeset(
    *,
    changeset_id: str,
    epic_id: str,
    terminal_state: str,
    integrated_sha: str | None,
    beads_root: Path,
    repo_root: Path,
    mark_changeset_merged: Callable[[str], None],
    mark_changeset_abandoned: Callable[[str], None],
    close_completed_ancestor_container_changesets: Callable[[str], list[str]],
    finalize_epic_if_complete: Callable[[], FinalizeResult],
) -> FinalizeResult:
    if terminal_state == "merged":
        mark_changeset_merged(changeset_id)
        if integrated_sha and integrated_sha.strip():
            beads.update_changeset_integrated_sha(
                changeset_id,
                integrated_sha.strip(),
                beads_root=beads_root,
                cwd=repo_root,
                allow_override=True,
            )
    elif terminal_state == "abandoned":
        mark_changeset_abandoned(changeset_id)
    else:
        raise ValueError(f"unsupported terminal changeset state: {terminal_state!r}")
    close_completed_ancestor_container_changesets(changeset_id)
    return finalize_epic_if_complete()

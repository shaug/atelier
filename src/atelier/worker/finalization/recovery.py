"""Recovery helpers for premature merged changeset state."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from ... import git, prs
from ..models import FinalizeResult


def recover_premature_merged_changeset(
    *,
    issue: dict[str, object],
    changeset_id: str,
    epic_id: str,
    agent_id: str,
    agent_bead_id: str | None,
    branch_pr: bool,
    branch_history: str,
    branch_squash_message: str,
    branch_pr_strategy: object,
    repo_slug: str | None,
    beads_root: Path,
    repo_root: Path,
    project_data_dir: Path,
    squash_message_agent_spec: str | None,
    squash_message_agent_options: list[str],
    squash_message_agent_home: Path | None,
    squash_message_agent_env: dict[str, str] | None,
    git_path: str | None,
    changeset_work_branch: Callable[[dict[str, object]], str],
    lookup_pr_payload: Callable[..., dict[str, object] | None],
    lookup_pr_payload_diagnostic: Callable[
        ..., tuple[dict[str, object] | None, str | None]
    ],
    changeset_integration_signal: Callable[..., tuple[bool, str | None]],
    finalize_terminal_changeset: Callable[..., FinalizeResult],
    mark_changeset_in_progress: Callable[..., None],
    update_changeset_review_from_pr: Callable[..., None],
    handle_pushed_without_pr: Callable[..., FinalizeResult],
    log_warning: Callable[[str], None],
) -> FinalizeResult | None:
    """Recover when a changeset is marked merged before publish/review signals."""
    if not branch_pr:
        return None
    work_branch = changeset_work_branch(issue)
    if not work_branch:
        return None
    pushed = git.git_ref_exists(
        repo_root, f"refs/remotes/origin/{work_branch}", git_path=git_path
    )
    payload = lookup_pr_payload(repo_slug, work_branch)
    lookup_error = None
    if payload is None:
        _payload_check, lookup_error = lookup_pr_payload_diagnostic(
            repo_slug, work_branch
        )
    if lookup_error:
        log_warning(
            "changeset="
            f"{changeset_id} premature-merged recovery failed PR lookup "
            f"for branch={work_branch}: {lookup_error}"
        )
        return FinalizeResult(
            continue_running=False, reason="changeset_pr_status_query_failed"
        )
    if payload:
        pr_state = prs.lifecycle_state(
            payload,
            pushed=pushed,
            review_requested=prs.has_review_requests(payload),
        )
    else:
        pr_state = "pushed" if pushed else "local-only"
    if pr_state in {"draft-pr", "pr-open", "in-review", "approved"}:
        mark_changeset_in_progress(
            changeset_id, beads_root=beads_root, repo_root=repo_root
        )
        update_changeset_review_from_pr(
            changeset_id,
            pr_payload=payload,
            pushed=pushed,
            beads_root=beads_root,
            repo_root=repo_root,
        )
        return FinalizeResult(continue_running=True, reason="changeset_review_pending")
    if pr_state == "merged":
        _integration_ok, integrated_sha = changeset_integration_signal(
            issue, repo_slug=None, repo_root=repo_root, git_path=git_path
        )
        return finalize_terminal_changeset(
            changeset_id=changeset_id,
            epic_id=epic_id,
            agent_id=agent_id,
            agent_bead_id=agent_bead_id,
            terminal_state="merged",
            integrated_sha=integrated_sha,
            branch_pr=branch_pr,
            branch_history=branch_history,
            branch_squash_message=branch_squash_message,
            beads_root=beads_root,
            repo_root=repo_root,
            project_data_dir=project_data_dir,
            squash_message_agent_spec=squash_message_agent_spec,
            squash_message_agent_options=squash_message_agent_options,
            squash_message_agent_home=squash_message_agent_home,
            squash_message_agent_env=squash_message_agent_env,
            git_path=git_path,
        )
    if pr_state == "closed":
        integration_ok, integrated_sha = changeset_integration_signal(
            issue, repo_slug=repo_slug, repo_root=repo_root, git_path=git_path
        )
        return finalize_terminal_changeset(
            changeset_id=changeset_id,
            epic_id=epic_id,
            agent_id=agent_id,
            agent_bead_id=agent_bead_id,
            terminal_state="merged" if integration_ok else "abandoned",
            integrated_sha=integrated_sha if integration_ok else None,
            branch_pr=branch_pr,
            branch_history=branch_history,
            branch_squash_message=branch_squash_message,
            beads_root=beads_root,
            repo_root=repo_root,
            project_data_dir=project_data_dir,
            squash_message_agent_spec=squash_message_agent_spec,
            squash_message_agent_options=squash_message_agent_options,
            squash_message_agent_home=squash_message_agent_home,
            squash_message_agent_env=squash_message_agent_env,
            git_path=git_path,
        )
    if pushed and pr_state in {"pushed", "local-only"}:
        mark_changeset_in_progress(
            changeset_id, beads_root=beads_root, repo_root=repo_root
        )
        return handle_pushed_without_pr(
            issue=issue,
            changeset_id=changeset_id,
            agent_id=agent_id,
            repo_slug=repo_slug,
            repo_root=repo_root,
            beads_root=beads_root,
            branch_pr_strategy=branch_pr_strategy,
            git_path=git_path,
        )
    return None

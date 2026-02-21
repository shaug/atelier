"""Git integration and epic finalization helpers for worker runtime."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from .. import agents, beads
from ..io import die, say
from ..worker import finalize as worker_finalize
from ..worker import integration_service as worker_integration_service
from ..worker.models import FinalizeResult, PublishSignalDiagnostics
from .work_finalization_state import (
    close_completed_container_changesets,
    mark_changeset_abandoned,
    mark_changeset_merged,
    send_planner_notification,
)
from .work_runtime_common import (
    ensure_exec_subcommand_flag,
    extract_changeset_root_branch,
    issue_labels,
    normalize_branch_value,
    strip_flag_with_value,
    with_codex_exec,
)


def _epic_ready_to_finalize(epic_id: str, *, beads_root: Path, repo_root: Path) -> bool:
    issues = beads.run_bd_json(["show", epic_id], beads_root=beads_root, cwd=repo_root)
    if not issues:
        return False
    issue = issues[0]
    labels = issue_labels(issue)
    if "at:changeset" in labels and ("cs:merged" in labels or "cs:abandoned" in labels):
        return True
    summary = beads.epic_changeset_summary(epic_id, beads_root=beads_root, cwd=repo_root)
    return summary.ready_to_close


def _ensure_local_branch(branch: str, *, repo_root: Path, git_path: str | None = None) -> bool:
    return worker_integration_service.ensure_local_branch(
        branch, repo_root=repo_root, git_path=git_path
    )


def _run_git_status(
    args: list[str],
    *,
    repo_root: Path,
    git_path: str | None = None,
    cwd: Path | None = None,
) -> tuple[bool, str]:
    return worker_integration_service.run_git_status(
        args, repo_root=repo_root, git_path=git_path, cwd=cwd
    )


def _resolve_epic_integration_cwd(
    *,
    project_data_dir: Path | None,
    repo_root: Path,
    epic_id: str,
    root_branch: str,
    git_path: str | None = None,
) -> Path:
    return worker_integration_service.resolve_epic_integration_cwd(
        project_data_dir=project_data_dir,
        repo_root=repo_root,
        epic_id=epic_id,
        root_branch=root_branch,
        git_path=git_path,
    )


def _resolve_changeset_worktree_path(
    *,
    project_data_dir: Path | None,
    epic_id: str,
    changeset_id: str,
) -> Path | None:
    return worker_integration_service.resolve_changeset_worktree_path(
        project_data_dir=project_data_dir,
        epic_id=epic_id,
        changeset_id=changeset_id,
    )


def _collect_publish_signal_diagnostics(
    *,
    work_branch: str,
    epic_id: str,
    changeset_id: str,
    project_data_dir: Path | None,
    repo_root: Path,
    git_path: str | None,
) -> PublishSignalDiagnostics:
    return worker_integration_service.collect_publish_signal_diagnostics(
        work_branch=work_branch,
        epic_id=epic_id,
        changeset_id=changeset_id,
        project_data_dir=project_data_dir,
        repo_root=repo_root,
        git_path=git_path,
    )


def _attempt_push_work_branch(
    work_branch: str, *, repo_root: Path, git_path: str | None = None
) -> tuple[bool, str]:
    return worker_integration_service.attempt_push_work_branch(
        work_branch, repo_root=repo_root, git_path=git_path
    )


def _format_publish_diagnostics(
    diagnostics: PublishSignalDiagnostics, *, push_detail: str | None = None
) -> str:
    return worker_integration_service.format_publish_diagnostics(
        diagnostics, push_detail=push_detail
    )


def _ensure_branch_not_checked_out(
    branch: str, *, repo_root: Path, git_path: str | None = None
) -> None:
    worker_integration_service.ensure_branch_not_checked_out(
        branch, repo_root=repo_root, git_path=git_path
    )


def _sync_local_branch_from_remote(
    branch: str, *, repo_root: Path, git_path: str | None = None
) -> bool:
    return worker_integration_service.sync_local_branch_from_remote(
        branch, repo_root=repo_root, git_path=git_path
    )


def _first_external_ticket_id(issue: dict[str, object]) -> str | None:
    return worker_integration_service.first_external_ticket_id(issue)


def _squash_subject(issue: dict[str, object], *, epic_id: str) -> str:
    return worker_integration_service.squash_subject(issue, epic_id=epic_id)


def _normalize_squash_message_mode(value: object) -> str:
    return worker_integration_service.normalize_squash_message_mode(value)


def _parse_squash_subject_output(output: str) -> str | None:
    return worker_integration_service.parse_squash_subject_output(output)


def _agent_generated_squash_subject(
    *,
    epic_issue: dict[str, object],
    epic_id: str,
    root_branch: str,
    parent_branch: str,
    repo_root: Path,
    git_path: str | None,
    agent_spec: agents.AgentSpec | None,
    agent_options: list[str] | None,
    agent_home: Path | None,
    agent_env: dict[str, str] | None,
) -> str | None:
    return worker_integration_service.agent_generated_squash_subject(
        epic_issue=epic_issue,
        epic_id=epic_id,
        root_branch=root_branch,
        parent_branch=parent_branch,
        repo_root=repo_root,
        git_path=git_path,
        agent_spec=agent_spec,
        agent_options=agent_options,
        agent_home=agent_home,
        agent_env=agent_env,
        with_codex_exec=with_codex_exec,
        strip_flag_with_value=strip_flag_with_value,
        ensure_exec_subcommand_flag=ensure_exec_subcommand_flag,
    )


def _cleanup_epic_branches_and_worktrees(
    *,
    project_data_dir: Path | None,
    repo_root: Path,
    epic_id: str,
    keep_branches: set[str] | None = None,
    git_path: str | None = None,
    log: Callable[[str], None] | None = None,
) -> None:
    worker_integration_service.cleanup_epic_branches_and_worktrees(
        project_data_dir=project_data_dir,
        repo_root=repo_root,
        epic_id=epic_id,
        keep_branches=keep_branches,
        git_path=git_path,
        log=log,
    )


def _integrate_epic_root_to_parent(
    *,
    epic_issue: dict[str, object],
    epic_id: str,
    root_branch: str,
    parent_branch: str,
    history: str,
    squash_message_mode: str = "deterministic",
    squash_message_agent_spec: agents.AgentSpec | None = None,
    squash_message_agent_options: list[str] | None = None,
    squash_message_agent_home: Path | None = None,
    squash_message_agent_env: dict[str, str] | None = None,
    integration_cwd: Path | None = None,
    repo_root: Path,
    git_path: str | None = None,
) -> tuple[bool, str | None, str | None]:
    return worker_integration_service.integrate_epic_root_to_parent(
        epic_issue=epic_issue,
        epic_id=epic_id,
        root_branch=root_branch,
        parent_branch=parent_branch,
        history=history,
        squash_message_mode=squash_message_mode,
        squash_message_agent_spec=squash_message_agent_spec,
        squash_message_agent_options=squash_message_agent_options,
        squash_message_agent_home=squash_message_agent_home,
        squash_message_agent_env=squash_message_agent_env,
        integration_cwd=integration_cwd,
        repo_root=repo_root,
        git_path=git_path,
        with_codex_exec=with_codex_exec,
        strip_flag_with_value=strip_flag_with_value,
        ensure_exec_subcommand_flag=ensure_exec_subcommand_flag,
    )


def _finalize_epic_if_complete(
    *,
    epic_id: str,
    agent_id: str,
    agent_bead_id: str,
    branch_pr: bool,
    branch_history: str,
    branch_squash_message: str = "deterministic",
    beads_root: Path,
    repo_root: Path,
    project_data_dir: Path | None = None,
    squash_message_agent_spec: agents.AgentSpec | None = None,
    squash_message_agent_options: list[str] | None = None,
    squash_message_agent_home: Path | None = None,
    squash_message_agent_env: dict[str, str] | None = None,
    git_path: str | None = None,
    log: Callable[[str], None] | None = None,
) -> FinalizeResult:
    return worker_finalize.finalize_epic_if_complete(
        epic_id=epic_id,
        agent_id=agent_id,
        agent_bead_id=agent_bead_id,
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
        log=log,
        epic_ready_to_finalize=lambda target_epic_id: _epic_ready_to_finalize(
            target_epic_id, beads_root=beads_root, repo_root=repo_root
        ),
        normalize_branch_value=normalize_branch_value,
        extract_changeset_root_branch=extract_changeset_root_branch,
        send_planner_notification=send_planner_notification,
        resolve_epic_integration_cwd=_resolve_epic_integration_cwd,
        integrate_epic_root_to_parent=_integrate_epic_root_to_parent,
        cleanup_epic_branches_and_worktrees=_cleanup_epic_branches_and_worktrees,
    )


def _finalize_terminal_changeset(
    *,
    changeset_id: str,
    epic_id: str,
    agent_id: str,
    agent_bead_id: str,
    terminal_state: str,
    integrated_sha: str | None,
    branch_pr: bool,
    branch_history: str,
    branch_squash_message: str,
    beads_root: Path,
    repo_root: Path,
    project_data_dir: Path | None,
    squash_message_agent_spec: agents.AgentSpec | None,
    squash_message_agent_options: list[str] | None,
    squash_message_agent_home: Path | None,
    squash_message_agent_env: dict[str, str] | None,
    git_path: str | None,
) -> FinalizeResult:
    try:
        return worker_finalize.finalize_terminal_changeset(
            changeset_id=changeset_id,
            epic_id=epic_id,
            terminal_state=terminal_state,
            integrated_sha=integrated_sha,
            beads_root=beads_root,
            repo_root=repo_root,
            mark_changeset_merged=lambda target_id: mark_changeset_merged(
                target_id, beads_root=beads_root, repo_root=repo_root
            ),
            mark_changeset_abandoned=lambda target_id: mark_changeset_abandoned(
                target_id, beads_root=beads_root, repo_root=repo_root
            ),
            close_completed_container_changesets=lambda target_epic_id: (
                close_completed_container_changesets(
                    target_epic_id, beads_root=beads_root, repo_root=repo_root
                )
            ),
            finalize_epic_if_complete=lambda: _finalize_epic_if_complete(
                epic_id=epic_id,
                agent_id=agent_id,
                agent_bead_id=agent_bead_id,
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
                log=say,
            ),
        )
    except ValueError as exc:
        die(str(exc))
        return FinalizeResult(continue_running=False, reason="changeset_finalize_error")


epic_ready_to_finalize = _epic_ready_to_finalize
ensure_local_branch = _ensure_local_branch
run_git_status = _run_git_status
resolve_epic_integration_cwd = _resolve_epic_integration_cwd
resolve_changeset_worktree_path = _resolve_changeset_worktree_path
collect_publish_signal_diagnostics = _collect_publish_signal_diagnostics
attempt_push_work_branch = _attempt_push_work_branch
format_publish_diagnostics = _format_publish_diagnostics
ensure_branch_not_checked_out = _ensure_branch_not_checked_out
sync_local_branch_from_remote = _sync_local_branch_from_remote
first_external_ticket_id = _first_external_ticket_id
squash_subject = _squash_subject
normalize_squash_message_mode = _normalize_squash_message_mode
parse_squash_subject_output = _parse_squash_subject_output
agent_generated_squash_subject = _agent_generated_squash_subject
cleanup_epic_branches_and_worktrees = _cleanup_epic_branches_and_worktrees
integrate_epic_root_to_parent = _integrate_epic_root_to_parent
finalize_epic_if_complete = _finalize_epic_if_complete
finalize_terminal_changeset = _finalize_terminal_changeset

__all__ = [
    "agent_generated_squash_subject",
    "attempt_push_work_branch",
    "cleanup_epic_branches_and_worktrees",
    "collect_publish_signal_diagnostics",
    "ensure_branch_not_checked_out",
    "ensure_local_branch",
    "epic_ready_to_finalize",
    "finalize_epic_if_complete",
    "finalize_terminal_changeset",
    "first_external_ticket_id",
    "format_publish_diagnostics",
    "integrate_epic_root_to_parent",
    "normalize_squash_message_mode",
    "parse_squash_subject_output",
    "resolve_changeset_worktree_path",
    "resolve_epic_integration_cwd",
    "run_git_status",
    "squash_subject",
    "sync_local_branch_from_remote",
]

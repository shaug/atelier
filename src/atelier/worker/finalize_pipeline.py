"""Finalize decision pipeline for worker changesets."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .. import beads, git, prs
from .models import FinalizeResult


def run_finalize_pipeline(
    *,
    changeset_id: str,
    epic_id: str,
    agent_id: str,
    agent_bead_id: str,
    started_at: dt.datetime,
    repo_slug: str | None,
    beads_root: Path,
    repo_root: Path,
    branch_pr: bool,
    branch_pr_strategy: object,
    branch_history: str,
    branch_squash_message: str,
    project_data_dir: Path | None,
    squash_message_agent_spec: Any,
    squash_message_agent_options: list[str] | None,
    squash_message_agent_home: Path | None,
    squash_message_agent_env: dict[str, str] | None,
    git_path: str | None,
    issue_labels: Callable[[dict[str, object]], set[str]],
    find_invalid_changeset_labels: Callable[..., list[str]],
    send_invalid_changeset_labels_notification: Callable[..., str],
    has_open_descendant_changesets: Callable[..., bool],
    has_blocking_messages: Callable[..., bool],
    mark_changeset_children_in_progress: Callable[..., None],
    close_completed_container_changesets: Callable[..., list[str]],
    promote_planned_descendant_changesets: Callable[..., None],
    changeset_integration_signal: Callable[..., tuple[bool, str | None]],
    recover_premature_merged_changeset: Callable[..., FinalizeResult | None],
    mark_changeset_blocked: Callable[..., None],
    send_planner_notification: Callable[..., None],
    mark_changeset_closed: Callable[..., None],
    finalize_epic_if_complete: Callable[..., FinalizeResult],
    mark_changeset_in_progress: Callable[..., None],
    changeset_waiting_on_review_or_signals: Callable[..., bool],
    lookup_pr_payload: Callable[..., dict[str, object] | None],
    lookup_pr_payload_diagnostic: Callable[
        ..., tuple[dict[str, object] | None, str | None]
    ],
    log_warning: Callable[[str], None],
    log_debug: Callable[[str], None],
    update_changeset_review_from_pr: Callable[..., None],
    finalize_terminal_changeset: Callable[..., FinalizeResult],
    handle_pushed_without_pr: Callable[..., FinalizeResult],
    attempt_push_work_branch: Callable[..., tuple[bool, str | None]],
    collect_publish_signal_diagnostics: Callable[..., Any],
    format_publish_diagnostics: Callable[..., str],
    set_changeset_review_pending_state: Callable[..., None],
) -> FinalizeResult:
    if not changeset_id:
        return FinalizeResult(continue_running=False, reason="changeset_missing")
    issues = beads.run_bd_json(
        ["show", changeset_id], beads_root=beads_root, cwd=repo_root
    )
    if not issues:
        return FinalizeResult(continue_running=False, reason="changeset_not_found")
    issue = issues[0]
    labels = issue_labels(issue)
    invalid_changesets = find_invalid_changeset_labels(
        epic_id, beads_root=beads_root, repo_root=repo_root
    )
    if invalid_changesets:
        send_invalid_changeset_labels_notification(
            epic_id=epic_id,
            invalid_changesets=invalid_changesets,
            agent_id=agent_id,
            beads_root=beads_root,
            repo_root=repo_root,
            dry_run=False,
        )
        return FinalizeResult(
            continue_running=False, reason="changeset_label_violation"
        )
    if "cs:merged" in labels or "cs:abandoned" in labels:
        if has_open_descendant_changesets(
            changeset_id, beads_root=beads_root, repo_root=repo_root
        ):
            descendants = beads.list_descendant_changesets(
                changeset_id,
                beads_root=beads_root,
                cwd=repo_root,
                include_closed=False,
            )
            planned_ids = {
                issue_id
                for descendant in descendants
                if isinstance((issue_id := descendant.get("id")), str)
                and issue_id
                and "cs:planned" in issue_labels(descendant)
            }
            if planned_ids and has_blocking_messages(
                thread_ids={changeset_id, epic_id, *planned_ids},
                started_at=started_at,
                beads_root=beads_root,
                repo_root=repo_root,
            ):
                mark_changeset_children_in_progress(
                    changeset_id, beads_root=beads_root, repo_root=repo_root
                )
                close_completed_container_changesets(
                    epic_id, beads_root=beads_root, repo_root=repo_root
                )
                return FinalizeResult(
                    continue_running=False, reason="changeset_children_planning_blocked"
                )
            promote_planned_descendant_changesets(
                changeset_id, beads_root=beads_root, repo_root=repo_root
            )
            mark_changeset_children_in_progress(
                changeset_id, beads_root=beads_root, repo_root=repo_root
            )
            close_completed_container_changesets(
                epic_id, beads_root=beads_root, repo_root=repo_root
            )
            return FinalizeResult(
                continue_running=True, reason="changeset_children_pending"
            )
        if "cs:merged" in labels:
            integration_proven, integrated_sha = changeset_integration_signal(
                issue, repo_slug=repo_slug, repo_root=repo_root, git_path=git_path
            )
            if not integration_proven:
                recovered = recover_premature_merged_changeset(
                    issue=issue,
                    changeset_id=changeset_id,
                    epic_id=epic_id,
                    agent_id=agent_id,
                    agent_bead_id=agent_bead_id,
                    branch_pr=branch_pr,
                    branch_history=branch_history,
                    branch_squash_message=branch_squash_message,
                    branch_pr_strategy=branch_pr_strategy,
                    repo_slug=repo_slug,
                    beads_root=beads_root,
                    repo_root=repo_root,
                    project_data_dir=project_data_dir,
                    squash_message_agent_spec=squash_message_agent_spec,
                    squash_message_agent_options=squash_message_agent_options,
                    squash_message_agent_home=squash_message_agent_home,
                    squash_message_agent_env=squash_message_agent_env,
                    git_path=git_path,
                )
                if recovered is not None:
                    return recovered
                mark_changeset_blocked(
                    changeset_id,
                    beads_root=beads_root,
                    repo_root=repo_root,
                    reason="missing integration signal for cs:merged",
                )
                send_planner_notification(
                    subject=(
                        f"NEEDS-DECISION: Missing integration signal ({changeset_id})"
                    ),
                    body="Changeset is labeled cs:merged but no integration signal "
                    "(changeset.integrated_sha or merged PR) was found.",
                    agent_id=agent_id,
                    thread_id=changeset_id,
                    beads_root=beads_root,
                    repo_root=repo_root,
                    dry_run=False,
                )
                return FinalizeResult(
                    continue_running=False,
                    reason="changeset_blocked_missing_integration",
                )
            if integrated_sha and integrated_sha.strip():
                beads.update_changeset_integrated_sha(
                    changeset_id,
                    integrated_sha.strip(),
                    beads_root=beads_root,
                    cwd=repo_root,
                )
        mark_changeset_closed(changeset_id, beads_root=beads_root, repo_root=repo_root)
        close_completed_container_changesets(
            epic_id, beads_root=beads_root, repo_root=repo_root
        )
        return finalize_epic_if_complete(
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
        )
    if has_blocking_messages(
        thread_ids={changeset_id, epic_id},
        started_at=started_at,
        beads_root=beads_root,
        repo_root=repo_root,
    ):
        mark_changeset_blocked(
            changeset_id,
            beads_root=beads_root,
            repo_root=repo_root,
            reason="message requires planner decision",
        )
        return FinalizeResult(
            continue_running=False, reason="changeset_blocked_message"
        )
    if "cs:in_progress" in labels:
        if changeset_waiting_on_review_or_signals(
            issue,
            repo_slug=repo_slug,
            repo_root=repo_root,
            branch_pr=branch_pr,
            branch_pr_strategy=branch_pr_strategy,
            git_path=git_path,
        ):
            return FinalizeResult(
                continue_running=True, reason="changeset_review_pending"
            )

    description = issue.get("description")
    fields = beads.parse_description_fields(
        description if isinstance(description, str) else ""
    )
    work_branch = fields.get("changeset.work_branch")
    if not work_branch or work_branch.strip().lower() == "null":
        mark_changeset_blocked(
            changeset_id,
            beads_root=beads_root,
            repo_root=repo_root,
            reason="missing changeset.work_branch metadata",
        )
        send_planner_notification(
            subject=f"NEEDS-DECISION: Missing changeset metadata ({changeset_id})",
            body="Missing changeset.work_branch metadata needed to validate publish.",
            agent_id=agent_id,
            thread_id=changeset_id,
            beads_root=beads_root,
            repo_root=repo_root,
            dry_run=False,
        )
        return FinalizeResult(
            continue_running=False, reason="changeset_blocked_missing_metadata"
        )
    work_branch = work_branch.strip()
    pushed = git.git_ref_exists(
        repo_root, f"refs/remotes/origin/{work_branch}", git_path=git_path
    )
    pr_payload = None
    pr_lookup_error: str | None = None
    if repo_slug:
        pr_payload = lookup_pr_payload(repo_slug, work_branch)
        if pr_payload is None:
            _payload_check, pr_lookup_error = lookup_pr_payload_diagnostic(
                repo_slug, work_branch
            )
    if branch_pr and pr_lookup_error:
        log_warning(
            "changeset="
            f"{changeset_id} finalize PR status lookup failed branch={work_branch}: "
            f"{pr_lookup_error}"
        )
        mark_changeset_in_progress(
            changeset_id, beads_root=beads_root, repo_root=repo_root
        )
        send_planner_notification(
            subject=f"NEEDS-DECISION: PR status query failed ({changeset_id})",
            body=(
                "Unable to evaluate PR lifecycle during finalize because GitHub "
                f"status lookup failed for branch `{work_branch}`.\n"
                f"Error: {pr_lookup_error}\n"
                "Action: resolve GitHub access/query issues and rerun worker finalize."
            ),
            agent_id=agent_id,
            thread_id=changeset_id,
            beads_root=beads_root,
            repo_root=repo_root,
            dry_run=False,
        )
        return FinalizeResult(
            continue_running=False, reason="changeset_pr_status_query_failed"
        )
    lifecycle: str | None = None
    if branch_pr:
        review_requested = prs.has_review_requests(pr_payload)
        lifecycle = prs.lifecycle_state(
            pr_payload, pushed=pushed, review_requested=review_requested
        )
    if lifecycle == "merged":
        log_debug(f"changeset={changeset_id} finalize lifecycle=merged")
        update_changeset_review_from_pr(
            changeset_id,
            pr_payload=pr_payload,
            pushed=pushed,
            beads_root=beads_root,
            repo_root=repo_root,
        )
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
    if lifecycle == "closed":
        log_debug(f"changeset={changeset_id} finalize lifecycle=closed")
        update_changeset_review_from_pr(
            changeset_id,
            pr_payload=pr_payload,
            pushed=pushed,
            beads_root=beads_root,
            repo_root=repo_root,
        )
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
    if branch_pr and pushed and not pr_payload:
        integration_ok, integrated_sha = changeset_integration_signal(
            issue, repo_slug=repo_slug, repo_root=repo_root, git_path=git_path
        )
        if integration_ok:
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
    if branch_pr and pushed and not pr_payload:
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
    if not pushed and not pr_payload:
        push_detail: str | None = None
        if branch_pr:
            pushed, push_detail = attempt_push_work_branch(
                work_branch, repo_root=repo_root, git_path=git_path
            )
            if pushed:
                if repo_slug:
                    pr_payload = lookup_pr_payload(repo_slug, work_branch)
                    if pr_payload is None:
                        _payload_check, pr_lookup_error = lookup_pr_payload_diagnostic(
                            repo_slug, work_branch
                        )
                    if pr_lookup_error:
                        log_warning(
                            "changeset="
                            f"{changeset_id} push succeeded but PR status lookup "
                            f"failed branch={work_branch}: {pr_lookup_error}"
                        )
                        mark_changeset_in_progress(
                            changeset_id, beads_root=beads_root, repo_root=repo_root
                        )
                        send_planner_notification(
                            subject=(
                                "NEEDS-DECISION: PR status query failed "
                                f"({changeset_id})"
                            ),
                            body=(
                                "Branch push succeeded but GitHub PR status lookup "
                                f"failed for `{work_branch}`.\n"
                                f"Error: {pr_lookup_error}\n"
                                "Action: resolve GitHub access/query issues and "
                                "rerun worker finalize."
                            ),
                            agent_id=agent_id,
                            thread_id=changeset_id,
                            beads_root=beads_root,
                            repo_root=repo_root,
                            dry_run=False,
                        )
                        return FinalizeResult(
                            continue_running=False,
                            reason="changeset_pr_status_query_failed",
                        )
                if branch_pr and not pr_payload:
                    return handle_pushed_without_pr(
                        issue=issue,
                        changeset_id=changeset_id,
                        agent_id=agent_id,
                        repo_slug=repo_slug,
                        repo_root=repo_root,
                        beads_root=beads_root,
                        branch_pr_strategy=branch_pr_strategy,
                        git_path=git_path,
                        create_detail_prefix=push_detail,
                    )
                set_changeset_review_pending_state(
                    changeset_id=changeset_id,
                    pr_payload=pr_payload,
                    pushed=True,
                    fallback_pr_state=None,
                    beads_root=beads_root,
                    repo_root=repo_root,
                )
                return FinalizeResult(
                    continue_running=True, reason="changeset_review_pending"
                )

        diagnostics = collect_publish_signal_diagnostics(
            work_branch=work_branch,
            epic_id=epic_id,
            changeset_id=changeset_id,
            project_data_dir=project_data_dir,
            repo_root=repo_root,
            git_path=git_path,
        )
        diagnostics_text = format_publish_diagnostics(
            diagnostics, push_detail=push_detail
        )
        if diagnostics.has_recoverable_local_state:
            mark_changeset_in_progress(
                changeset_id, beads_root=beads_root, repo_root=repo_root
            )
            beads.run_bd_command(
                [
                    "update",
                    changeset_id,
                    "--append-notes",
                    "publish_pending: no push/PR signal after worker completion; "
                    "kept changeset in-progress for retry.",
                ],
                beads_root=beads_root,
                cwd=repo_root,
                allow_failure=True,
            )
            send_planner_notification(
                subject=f"NEEDS-DECISION: Publish incomplete ({changeset_id})",
                body=(
                    "No push or PR detected after worker completion. "
                    "Recovered to in_progress for retry.\n"
                    f"{diagnostics_text}"
                ),
                agent_id=agent_id,
                thread_id=changeset_id,
                beads_root=beads_root,
                repo_root=repo_root,
                dry_run=False,
            )
            return FinalizeResult(
                continue_running=False, reason="changeset_publish_pending"
            )

        mark_changeset_blocked(
            changeset_id,
            beads_root=beads_root,
            repo_root=repo_root,
            reason="publish/checks signals missing",
        )
        send_planner_notification(
            subject=f"NEEDS-DECISION: Publish/checks missing ({changeset_id})",
            body=(
                "No push or PR detected after worker completion and no local "
                "recoverable state found.\n"
                f"{diagnostics_text}"
            ),
            agent_id=agent_id,
            thread_id=changeset_id,
            beads_root=beads_root,
            repo_root=repo_root,
            dry_run=False,
        )
        return FinalizeResult(
            continue_running=False, reason="changeset_blocked_publish_missing"
        )
    if branch_pr and pr_payload:
        set_changeset_review_pending_state(
            changeset_id=changeset_id,
            pr_payload=pr_payload,
            pushed=pushed,
            fallback_pr_state=None,
            beads_root=beads_root,
            repo_root=repo_root,
        )
        return FinalizeResult(continue_running=True, reason="changeset_review_pending")
    return FinalizeResult(continue_running=True, reason="changeset_published")

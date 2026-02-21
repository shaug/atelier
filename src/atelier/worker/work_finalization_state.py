"""Finalize/publish state helpers for worker runtime."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from pathlib import Path

from .. import agents, beads, changeset_fields, changesets, git, lifecycle, pr_strategy, prs
from ..io import say
from ..worker import finalization_service as worker_finalization_service
from ..worker import integration_service as worker_integration_service
from ..worker import publish as worker_publish
from ..worker import queueing as worker_queueing
from ..worker import reconcile_service as worker_reconcile_service
from ..worker.finalization import pr_gate as worker_pr_gate
from ..worker.finalization import recovery as worker_recovery
from ..worker.models import FinalizeResult
from .work_runtime_common import (
    dry_run_log,
    extract_workspace_parent_branch,
    issue_labels,
    issue_parent_id,
    parse_issue_time,
)

_VALID_CHANGESET_STATE_LABELS = {
    "cs:planned",
    "cs:ready",
    "cs:in_progress",
    "cs:blocked",
    "cs:merged",
    "cs:abandoned",
}


def send_planner_notification(
    *,
    subject: str,
    body: str,
    agent_id: str,
    thread_id: str | None,
    beads_root: Path,
    repo_root: Path,
    dry_run: bool,
) -> None:
    """Send planner notification.

    Args:
        subject: Value for `subject`.
        body: Value for `body`.
        agent_id: Value for `agent_id`.
        thread_id: Value for `thread_id`.
        beads_root: Value for `beads_root`.
        repo_root: Value for `repo_root`.
        dry_run: Value for `dry_run`.

    Returns:
        Function result.
    """
    worker_queueing.send_planner_notification(
        subject=subject,
        body=body,
        agent_id=agent_id,
        thread_id=thread_id,
        beads_root=beads_root,
        repo_root=repo_root,
        dry_run=dry_run,
        dry_run_log=dry_run_log,
    )


def send_invalid_changeset_labels_notification(
    *,
    epic_id: str,
    invalid_changesets: list[str],
    agent_id: str,
    beads_root: Path,
    repo_root: Path,
    dry_run: bool,
) -> str:
    """Send invalid changeset labels notification.

    Args:
        epic_id: Value for `epic_id`.
        invalid_changesets: Value for `invalid_changesets`.
        agent_id: Value for `agent_id`.
        beads_root: Value for `beads_root`.
        repo_root: Value for `repo_root`.
        dry_run: Value for `dry_run`.

    Returns:
        Function result.
    """
    return worker_queueing.send_invalid_changeset_labels_notification(
        epic_id=epic_id,
        invalid_changesets=invalid_changesets,
        agent_id=agent_id,
        beads_root=beads_root,
        repo_root=repo_root,
        dry_run=dry_run,
        dry_run_log=dry_run_log,
    )


def send_no_ready_changesets(
    *,
    epic_id: str,
    agent_id: str,
    beads_root: Path,
    repo_root: Path,
    dry_run: bool,
) -> None:
    """Send no ready changesets.

    Args:
        epic_id: Value for `epic_id`.
        agent_id: Value for `agent_id`.
        beads_root: Value for `beads_root`.
        repo_root: Value for `repo_root`.
        dry_run: Value for `dry_run`.

    Returns:
        Function result.
    """
    worker_queueing.send_no_ready_changesets(
        epic_id=epic_id,
        agent_id=agent_id,
        beads_root=beads_root,
        repo_root=repo_root,
        dry_run=dry_run,
        dry_run_log=dry_run_log,
    )


def release_epic_assignment(epic_id: str, *, beads_root: Path, repo_root: Path) -> None:
    """Release epic assignment.

    Args:
        epic_id: Value for `epic_id`.
        beads_root: Value for `beads_root`.
        repo_root: Value for `repo_root`.

    Returns:
        Function result.
    """
    issues = beads.run_bd_json(["show", epic_id], beads_root=beads_root, cwd=repo_root)
    if not issues:
        return
    issue = issues[0]
    labels = issue_labels(issue)
    status = str(issue.get("status") or "")
    args = ["update", epic_id, "--assignee", ""]
    if "at:hooked" in labels:
        args.extend(["--remove-label", "at:hooked"])
    if status and status not in {"closed", "done"}:
        args.extend(["--status", "open"])
    beads.run_bd_command(args, beads_root=beads_root, cwd=repo_root, allow_failure=True)


def has_open_descendant_changesets(changeset_id: str, *, beads_root: Path, repo_root: Path) -> bool:
    """Has open descendant changesets.

    Args:
        changeset_id: Value for `changeset_id`.
        beads_root: Value for `beads_root`.
        repo_root: Value for `repo_root`.

    Returns:
        Function result.
    """
    descendants = beads.list_descendant_changesets(
        changeset_id,
        beads_root=beads_root,
        cwd=repo_root,
        include_closed=False,
    )
    return bool(descendants)


def is_changeset_in_progress(issue: dict[str, object]) -> bool:
    """Is changeset in progress.

    Args:
        issue: Value for `issue`.

    Returns:
        Function result.
    """
    return lifecycle.is_changeset_in_progress(issue.get("status"), issue_labels(issue))


def is_changeset_ready(issue: dict[str, object]) -> bool:
    """Is changeset ready.

    Args:
        issue: Value for `issue`.

    Returns:
        Function result.
    """
    return lifecycle.is_changeset_ready(issue.get("status"), issue_labels(issue))


def changeset_review_state(issue: dict[str, object]) -> str | None:
    """Changeset review state.

    Args:
        issue: Value for `issue`.

    Returns:
        Function result.
    """
    return changeset_fields.review_state(issue)


def changeset_waiting_on_review(issue: dict[str, object]) -> bool:
    """Changeset waiting on review.

    Args:
        issue: Value for `issue`.

    Returns:
        Function result.
    """
    state = changeset_review_state(issue)
    if state is None:
        return False
    return state in {"pushed", "draft-pr", "pr-open", "in-review", "approved"}


def changeset_work_branch(issue: dict[str, object]) -> str | None:
    """Changeset work branch.

    Args:
        issue: Value for `issue`.

    Returns:
        Function result.
    """
    return changeset_fields.work_branch(issue)


def changeset_pr_url(issue: dict[str, object]) -> str | None:
    """Changeset pr url.

    Args:
        issue: Value for `issue`.

    Returns:
        Function result.
    """
    return changeset_fields.pr_url(issue)


def lookup_pr_payload(repo_slug: str | None, branch: str) -> dict[str, object] | None:
    """Lookup PR payload for a branch.

    Args:
        repo_slug: GitHub owner/repo slug.
        branch: Branch name used for PR lookup.

    Returns:
        PR payload when found, otherwise ``None``.
    """
    if not repo_slug:
        return None
    return prs.read_github_pr_status(repo_slug, branch)


def lookup_pr_payload_diagnostic(
    repo_slug: str | None, branch: str
) -> tuple[dict[str, object] | None, str | None]:
    """Lookup PR payload with explicit query-failure diagnostics.

    Args:
        repo_slug: GitHub owner/repo slug.
        branch: Branch name used for PR lookup.

    Returns:
        Tuple containing payload and optional diagnostic message.
    """
    if not repo_slug:
        return None, None
    lookup = prs.lookup_github_pr_status(repo_slug, branch)
    if lookup.found:
        return lookup.payload, None
    if lookup.failed:
        error = lookup.error or "unknown gh error"
        if error.startswith("missing required command: gh"):
            return None, None
        return None, error
    return None, None


def changeset_root_branch(issue: dict[str, object]) -> str | None:
    """Changeset root branch.

    Args:
        issue: Value for `issue`.

    Returns:
        Function result.
    """
    return changeset_fields.root_branch(issue)


def changeset_base_branch(
    issue: dict[str, object],
    *,
    beads_root: Path | None = None,
    repo_root: Path,
    git_path: str | None,
) -> str | None:
    """Changeset base branch.

    Args:
        issue: Value for `issue`.
        beads_root: Value for `beads_root`.
        repo_root: Value for `repo_root`.
        git_path: Value for `git_path`.

    Returns:
        Function result.
    """
    description = issue.get("description")
    fields = beads.parse_description_fields(description if isinstance(description, str) else "")
    root_branch = changeset_root_branch(issue)
    parent_branch = changeset_parent_branch(issue, root_branch=root_branch or "")
    workspace_parent_branch = fields.get("workspace.parent_branch")
    normalized_parent = parent_branch.strip() if isinstance(parent_branch, str) else ""
    normalized_root = root_branch.strip() if isinstance(root_branch, str) else ""
    normalized_workspace_parent = (
        workspace_parent_branch.strip() if isinstance(workspace_parent_branch, str) else ""
    )
    if (
        not normalized_workspace_parent
        and beads_root is not None
        and normalized_root
        and normalized_parent
        and normalized_parent == normalized_root
    ):
        epic_id = resolve_epic_id_for_changeset(issue, beads_root=beads_root, repo_root=repo_root)
        if epic_id:
            epic_issues = beads.run_bd_json(["show", epic_id], beads_root=beads_root, cwd=repo_root)
            if epic_issues:
                resolved_parent = extract_workspace_parent_branch(epic_issues[0])
                if resolved_parent:
                    normalized_workspace_parent = resolved_parent
    # Top-level changesets often persisted parent=root; use workspace parent
    # for PR base when available so PR creation targets mainline.
    if (
        normalized_workspace_parent
        and normalized_workspace_parent.lower() != "null"
        and normalized_root
        and normalized_parent
        and normalized_parent == normalized_root
    ):
        return normalized_workspace_parent
    if normalized_parent and normalized_parent.lower() != "null":
        return normalized_parent
    if root_branch:
        return root_branch
    return git.git_default_branch(repo_root, git_path=git_path)


def render_changeset_pr_body(issue: dict[str, object]) -> str:
    """Render changeset pr body.

    Args:
        issue: Value for `issue`.

    Returns:
        Function result.
    """
    description = issue.get("description")
    fields = beads.parse_description_fields(description if isinstance(description, str) else "")
    return worker_publish.render_changeset_pr_body(issue, fields=fields)


def attempt_create_draft_pr(
    *,
    repo_slug: str,
    issue: dict[str, object],
    work_branch: str,
    beads_root: Path,
    repo_root: Path,
    git_path: str | None,
    changeset_base_branch_fn: Callable[..., str] | None = None,
    render_changeset_pr_body_fn: Callable[[dict[str, object]], str] | None = None,
) -> tuple[bool, str]:
    """Attempt create draft pr.

    Args:
        repo_slug: Value for `repo_slug`.
        issue: Value for `issue`.
        work_branch: Value for `work_branch`.
        beads_root: Value for `beads_root`.
        repo_root: Value for `repo_root`.
        git_path: Value for `git_path`.
        changeset_base_branch_fn: Value for `changeset_base_branch_fn`.
        render_changeset_pr_body_fn: Value for `render_changeset_pr_body_fn`.

    Returns:
        Function result.
    """
    return worker_pr_gate.attempt_create_draft_pr(
        repo_slug=repo_slug,
        issue=issue,
        work_branch=work_branch,
        beads_root=beads_root,
        repo_root=repo_root,
        git_path=git_path,
        changeset_base_branch=changeset_base_branch_fn or changeset_base_branch,
        render_changeset_pr_body=render_changeset_pr_body_fn or render_changeset_pr_body,
    )


def set_changeset_review_pending_state(
    *,
    changeset_id: str,
    pr_payload: dict[str, object] | None,
    pushed: bool,
    fallback_pr_state: str | None,
    beads_root: Path,
    repo_root: Path,
) -> None:
    """Set changeset review pending state.

    Args:
        changeset_id: Value for `changeset_id`.
        pr_payload: Value for `pr_payload`.
        pushed: Value for `pushed`.
        fallback_pr_state: Value for `fallback_pr_state`.
        beads_root: Value for `beads_root`.
        repo_root: Value for `repo_root`.

    Returns:
        Function result.
    """
    worker_pr_gate.set_changeset_review_pending_state(
        changeset_id=changeset_id,
        pr_payload=pr_payload,
        pushed=pushed,
        fallback_pr_state=fallback_pr_state,
        beads_root=beads_root,
        repo_root=repo_root,
        mark_changeset_in_progress=mark_changeset_in_progress,
        update_changeset_review_from_pr=update_changeset_review_from_pr,
    )


def update_changeset_review_from_pr(
    changeset_id: str,
    *,
    pr_payload: dict[str, object] | None,
    pushed: bool,
    beads_root: Path,
    repo_root: Path,
) -> None:
    """Update changeset review from pr.

    Args:
        changeset_id: Value for `changeset_id`.
        pr_payload: Value for `pr_payload`.
        pushed: Value for `pushed`.
        beads_root: Value for `beads_root`.
        repo_root: Value for `repo_root`.

    Returns:
        Function result.
    """
    if not pr_payload:
        return
    review_requested = prs.has_review_requests(pr_payload)
    lifecycle = prs.lifecycle_state(pr_payload, pushed=pushed, review_requested=review_requested)
    metadata = changesets.ReviewMetadata(
        pr_url=str(pr_payload.get("url") or "") or None,
        pr_number=str(pr_payload.get("number") or "") or None,
        pr_state=lifecycle,
    )
    beads.update_changeset_review(
        changeset_id,
        metadata,
        beads_root=beads_root,
        cwd=repo_root,
    )


def handle_pushed_without_pr(
    *,
    issue: dict[str, object],
    changeset_id: str,
    agent_id: str,
    repo_slug: str | None,
    repo_root: Path,
    beads_root: Path,
    branch_pr_strategy: object,
    git_path: str | None,
    create_detail_prefix: str | None = None,
) -> FinalizeResult:
    """Handle pushed without pr.

    Args:
        issue: Value for `issue`.
        changeset_id: Value for `changeset_id`.
        agent_id: Value for `agent_id`.
        repo_slug: Value for `repo_slug`.
        repo_root: Value for `repo_root`.
        beads_root: Value for `beads_root`.
        branch_pr_strategy: Value for `branch_pr_strategy`.
        git_path: Value for `git_path`.
        create_detail_prefix: Value for `create_detail_prefix`.

    Returns:
        Function result.
    """
    gate_result = worker_pr_gate.handle_pushed_without_pr(
        issue=issue,
        changeset_id=changeset_id,
        agent_id=agent_id,
        repo_slug=repo_slug,
        repo_root=repo_root,
        beads_root=beads_root,
        branch_pr_strategy=branch_pr_strategy,
        git_path=git_path,
        create_detail_prefix=create_detail_prefix,
        changeset_base_branch=changeset_base_branch,
        changeset_work_branch=changeset_work_branch,
        render_changeset_pr_body=render_changeset_pr_body,
        lookup_pr_payload=lookup_pr_payload,
        lookup_pr_payload_diagnostic=lookup_pr_payload_diagnostic,
        mark_changeset_in_progress=mark_changeset_in_progress,
        send_planner_notification=send_planner_notification,
        update_changeset_review_from_pr=update_changeset_review_from_pr,
        emit=say,
        attempt_create_draft_pr_fn=attempt_create_draft_pr,
    )
    return gate_result.finalize_result


def changeset_parent_lifecycle_state(
    issue: dict[str, object],
    *,
    repo_slug: str | None,
    repo_root: Path,
    git_path: str | None,
) -> str | None:
    """Changeset parent lifecycle state.

    Args:
        issue: Value for `issue`.
        repo_slug: Value for `repo_slug`.
        repo_root: Value for `repo_root`.
        git_path: Value for `git_path`.

    Returns:
        Function result.
    """
    return worker_pr_gate.changeset_parent_lifecycle_state(
        issue,
        repo_slug=repo_slug,
        repo_root=repo_root,
        git_path=git_path,
        lookup_pr_payload=lookup_pr_payload,
    )


def changeset_pr_creation_decision(
    issue: dict[str, object],
    *,
    repo_slug: str | None,
    repo_root: Path,
    git_path: str | None,
    branch_pr_strategy: object,
) -> pr_strategy.PrStrategyDecision:
    """Changeset pr creation decision.

    Args:
        issue: Value for `issue`.
        repo_slug: Value for `repo_slug`.
        repo_root: Value for `repo_root`.
        git_path: Value for `git_path`.
        branch_pr_strategy: Value for `branch_pr_strategy`.

    Returns:
        Function result.
    """
    return worker_pr_gate.changeset_pr_creation_decision(
        issue,
        repo_slug=repo_slug,
        repo_root=repo_root,
        git_path=git_path,
        branch_pr_strategy=branch_pr_strategy,
        lookup_pr_payload=lookup_pr_payload,
    )


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
    branch_pr_strategy: pr_strategy.PrStrategy,
    repo_slug: str | None,
    beads_root: Path,
    repo_root: Path,
    project_data_dir: Path,
    squash_message_agent_spec: agents.AgentSpec | None,
    squash_message_agent_options: list[str],
    squash_message_agent_home: Path | None,
    squash_message_agent_env: dict[str, str] | None,
    git_path: str | None,
) -> FinalizeResult | None:
    """Recover premature merged changeset.

    Args:
        issue: Value for `issue`.
        changeset_id: Value for `changeset_id`.
        epic_id: Value for `epic_id`.
        agent_id: Value for `agent_id`.
        agent_bead_id: Value for `agent_bead_id`.
        branch_pr: Value for `branch_pr`.
        branch_history: Value for `branch_history`.
        branch_squash_message: Value for `branch_squash_message`.
        branch_pr_strategy: Value for `branch_pr_strategy`.
        repo_slug: Value for `repo_slug`.
        beads_root: Value for `beads_root`.
        repo_root: Value for `repo_root`.
        project_data_dir: Value for `project_data_dir`.
        squash_message_agent_spec: Value for `squash_message_agent_spec`.
        squash_message_agent_options: Value for `squash_message_agent_options`.
        squash_message_agent_home: Value for `squash_message_agent_home`.
        squash_message_agent_env: Value for `squash_message_agent_env`.
        git_path: Value for `git_path`.

    Returns:
        Function result.
    """
    from .work_finalization_integration import finalize_terminal_changeset

    return worker_recovery.recover_premature_merged_changeset(
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
        changeset_work_branch=changeset_work_branch,
        lookup_pr_payload=lookup_pr_payload,
        lookup_pr_payload_diagnostic=lookup_pr_payload_diagnostic,
        changeset_integration_signal=changeset_integration_signal,
        finalize_terminal_changeset=finalize_terminal_changeset,
        mark_changeset_in_progress=mark_changeset_in_progress,
        update_changeset_review_from_pr=update_changeset_review_from_pr,
        handle_pushed_without_pr=handle_pushed_without_pr,
    )


def changeset_waiting_on_review_or_signals(
    issue: dict[str, object],
    *,
    repo_slug: str | None,
    repo_root: Path,
    branch_pr: bool,
    branch_pr_strategy: object,
    git_path: str | None,
) -> bool:
    """Changeset waiting on review or signals.

    Args:
        issue: Value for `issue`.
        repo_slug: Value for `repo_slug`.
        repo_root: Value for `repo_root`.
        branch_pr: Value for `branch_pr`.
        branch_pr_strategy: Value for `branch_pr_strategy`.
        git_path: Value for `git_path`.

    Returns:
        Function result.
    """
    if not branch_pr:
        return False
    work_branch = changeset_work_branch(issue)
    if work_branch:
        pushed = git.git_ref_exists(
            repo_root, f"refs/remotes/origin/{work_branch}", git_path=git_path
        )
        pr_payload = lookup_pr_payload(repo_slug, work_branch)
        review_requested = prs.has_review_requests(pr_payload)
        state = prs.lifecycle_state(pr_payload, pushed=pushed, review_requested=review_requested)
        if state in {"merged", "closed"}:
            return False
        if state in {"draft-pr", "pr-open", "in-review", "approved"}:
            return True
        if state == "pushed":
            decision = changeset_pr_creation_decision(
                issue,
                repo_slug=repo_slug,
                repo_root=repo_root,
                git_path=git_path,
                branch_pr_strategy=branch_pr_strategy,
            )
            return not decision.allow_pr
    review_state = changeset_review_state(issue)
    if review_state:
        if review_state in {"draft-pr", "pr-open", "in-review", "approved"}:
            return True
        if review_state == "pushed":
            decision = changeset_pr_creation_decision(
                issue,
                repo_slug=repo_slug,
                repo_root=repo_root,
                git_path=git_path,
                branch_pr_strategy=branch_pr_strategy,
            )
            return not decision.allow_pr
    return False


def is_changeset_recovery_candidate(
    issue: dict[str, object],
    *,
    repo_slug: str | None,
    repo_root: Path,
    branch_pr: bool,
    git_path: str | None,
) -> bool:
    """Return whether a blocked changeset has enough signals to recover.

    Args:
        issue: Changeset issue payload.
        repo_slug: Optional GitHub owner/repo slug.
        repo_root: Repository checkout path.
        branch_pr: Whether PR mode is enabled.
        git_path: Optional git binary path override.

    Returns:
        ``True`` when recovery should re-run finalize logic.
    """
    labels = issue_labels(issue)
    status = str(issue.get("status") or "").strip().lower()
    if "cs:blocked" not in labels and status != "blocked":
        return False
    if "cs:merged" in labels or "cs:abandoned" in labels:
        return False
    if status in {"closed", "done"}:
        return False
    work_branch = changeset_work_branch(issue)
    if not work_branch:
        return False
    pushed = git.git_ref_exists(repo_root, f"refs/remotes/origin/{work_branch}", git_path=git_path)
    if branch_pr:
        pr_payload = lookup_pr_payload(repo_slug, work_branch)
        review_requested = prs.has_review_requests(pr_payload)
        lifecycle = prs.lifecycle_state(
            pr_payload, pushed=pushed, review_requested=review_requested
        )
        if lifecycle in {"pushed", "draft-pr", "pr-open", "in-review", "approved"}:
            return True
        review_state = changeset_review_state(issue)
        return review_state in {
            "pushed",
            "draft-pr",
            "pr-open",
            "in-review",
            "approved",
        }
    return pushed


def list_child_issues(
    parent_id: str, *, beads_root: Path, repo_root: Path, include_closed: bool = False
) -> list[dict[str, object]]:
    """List child issues.

    Args:
        parent_id: Value for `parent_id`.
        beads_root: Value for `beads_root`.
        repo_root: Value for `repo_root`.
        include_closed: Value for `include_closed`.

    Returns:
        Function result.
    """
    return worker_finalization_service.list_child_issues(
        parent_id,
        beads_root=beads_root,
        repo_root=repo_root,
        include_closed=include_closed,
    )


def find_invalid_changeset_labels(root_id: str, *, beads_root: Path, repo_root: Path) -> list[str]:
    """Find invalid changeset labels.

    Args:
        root_id: Value for `root_id`.
        beads_root: Value for `beads_root`.
        repo_root: Value for `repo_root`.

    Returns:
        Function result.
    """
    return worker_finalization_service.find_invalid_changeset_labels(
        root_id,
        beads_root=beads_root,
        repo_root=repo_root,
        valid_changeset_state_labels=_VALID_CHANGESET_STATE_LABELS,
    )


def changeset_parent_branch(issue: dict[str, object], *, root_branch: str) -> str:
    """Changeset parent branch.

    Args:
        issue: Value for `issue`.
        root_branch: Value for `root_branch`.

    Returns:
        Function result.
    """
    description = issue.get("description")
    fields = beads.parse_description_fields(description if isinstance(description, str) else "")
    parent_branch = fields.get("changeset.parent_branch")
    if not parent_branch:
        return root_branch
    normalized = parent_branch.strip()
    if not normalized or normalized.lower() == "null":
        return root_branch
    return normalized


def mark_changeset_in_progress(changeset_id: str, *, beads_root: Path, repo_root: Path) -> None:
    """Mark changeset in progress.

    Args:
        changeset_id: Value for `changeset_id`.
        beads_root: Value for `beads_root`.
        repo_root: Value for `repo_root`.

    Returns:
        Function result.
    """
    worker_finalization_service.mark_changeset_in_progress(
        changeset_id,
        beads_root=beads_root,
        repo_root=repo_root,
    )


def mark_changeset_closed(changeset_id: str, *, beads_root: Path, repo_root: Path) -> None:
    """Mark changeset closed.

    Args:
        changeset_id: Value for `changeset_id`.
        beads_root: Value for `beads_root`.
        repo_root: Value for `repo_root`.

    Returns:
        Function result.
    """
    worker_finalization_service.mark_changeset_closed(
        changeset_id,
        beads_root=beads_root,
        repo_root=repo_root,
    )


def mark_changeset_merged(changeset_id: str, *, beads_root: Path, repo_root: Path) -> None:
    """Mark changeset merged.

    Args:
        changeset_id: Value for `changeset_id`.
        beads_root: Value for `beads_root`.
        repo_root: Value for `repo_root`.

    Returns:
        Function result.
    """
    worker_finalization_service.mark_changeset_merged(
        changeset_id,
        beads_root=beads_root,
        repo_root=repo_root,
    )


def mark_changeset_abandoned(changeset_id: str, *, beads_root: Path, repo_root: Path) -> None:
    """Mark changeset abandoned.

    Args:
        changeset_id: Value for `changeset_id`.
        beads_root: Value for `beads_root`.
        repo_root: Value for `repo_root`.

    Returns:
        Function result.
    """
    worker_finalization_service.mark_changeset_abandoned(
        changeset_id,
        beads_root=beads_root,
        repo_root=repo_root,
    )


def mark_changeset_blocked(
    changeset_id: str, *, beads_root: Path, repo_root: Path, reason: str
) -> None:
    """Mark changeset blocked.

    Args:
        changeset_id: Value for `changeset_id`.
        beads_root: Value for `beads_root`.
        repo_root: Value for `repo_root`.
        reason: Value for `reason`.

    Returns:
        Function result.
    """
    worker_finalization_service.mark_changeset_blocked(
        changeset_id,
        beads_root=beads_root,
        repo_root=repo_root,
        reason=reason,
    )


def mark_changeset_children_in_progress(
    changeset_id: str, *, beads_root: Path, repo_root: Path
) -> None:
    """Mark changeset children in progress.

    Args:
        changeset_id: Value for `changeset_id`.
        beads_root: Value for `beads_root`.
        repo_root: Value for `repo_root`.

    Returns:
        Function result.
    """
    worker_finalization_service.mark_changeset_children_in_progress(
        changeset_id,
        beads_root=beads_root,
        repo_root=repo_root,
    )


def close_completed_container_changesets(
    epic_id: str, *, beads_root: Path, repo_root: Path
) -> list[str]:
    """Close completed container changesets.

    Args:
        epic_id: Value for `epic_id`.
        beads_root: Value for `beads_root`.
        repo_root: Value for `repo_root`.

    Returns:
        Function result.
    """
    return worker_finalization_service.close_completed_container_changesets(
        epic_id,
        beads_root=beads_root,
        repo_root=repo_root,
        has_open_descendant_changesets=lambda issue_id: has_open_descendant_changesets(
            issue_id, beads_root=beads_root, repo_root=repo_root
        ),
    )


def promote_planned_descendant_changesets(
    changeset_id: str, *, beads_root: Path, repo_root: Path
) -> list[str]:
    """Promote planned descendant changesets.

    Args:
        changeset_id: Value for `changeset_id`.
        beads_root: Value for `beads_root`.
        repo_root: Value for `repo_root`.

    Returns:
        Function result.
    """
    return worker_finalization_service.promote_planned_descendant_changesets(
        changeset_id, beads_root=beads_root, repo_root=repo_root
    )


def has_blocking_messages(
    *,
    thread_ids: set[str],
    started_at: dt.datetime,
    beads_root: Path,
    repo_root: Path,
) -> bool:
    """Has blocking messages.

    Args:
        thread_ids: Value for `thread_ids`.
        started_at: Value for `started_at`.
        beads_root: Value for `beads_root`.
        repo_root: Value for `repo_root`.

    Returns:
        Function result.
    """
    return worker_finalization_service.has_blocking_messages(
        thread_ids=thread_ids,
        started_at=started_at,
        beads_root=beads_root,
        repo_root=repo_root,
        parse_issue_time=parse_issue_time,
    )


def branch_ref_for_lookup(
    repo_root: Path, branch: str, *, git_path: str | None = None
) -> str | None:
    """Branch ref for lookup.

    Args:
        repo_root: Value for `repo_root`.
        branch: Value for `branch`.
        git_path: Value for `git_path`.

    Returns:
        Function result.
    """
    return worker_integration_service.branch_ref_for_lookup(repo_root, branch, git_path=git_path)


def epic_root_integrated_into_parent(
    epic_issue: dict[str, object],
    *,
    repo_root: Path,
    git_path: str | None = None,
) -> bool:
    """Epic root integrated into parent.

    Args:
        epic_issue: Value for `epic_issue`.
        repo_root: Value for `repo_root`.
        git_path: Value for `git_path`.

    Returns:
        Function result.
    """
    return worker_integration_service.epic_root_integrated_into_parent(
        epic_issue,
        repo_root=repo_root,
        git_path=git_path,
    )


def changeset_integration_signal(
    issue: dict[str, object],
    *,
    repo_slug: str | None,
    repo_root: Path,
    git_path: str | None = None,
) -> tuple[bool, str | None]:
    """Changeset integration signal.

    Args:
        issue: Value for `issue`.
        repo_slug: Value for `repo_slug`.
        repo_root: Value for `repo_root`.
        git_path: Value for `git_path`.

    Returns:
        Function result.
    """
    return worker_integration_service.changeset_integration_signal(
        issue,
        repo_slug=repo_slug,
        repo_root=repo_root,
        lookup_pr_payload=lookup_pr_payload,
        git_path=git_path,
    )


def resolve_epic_id_for_changeset(
    issue: dict[str, object], *, beads_root: Path, repo_root: Path
) -> str | None:
    """Resolve epic id for changeset.

    Args:
        issue: Value for `issue`.
        beads_root: Value for `beads_root`.
        repo_root: Value for `repo_root`.

    Returns:
        Function result.
    """
    return worker_reconcile_service.resolve_epic_id_for_changeset(
        issue,
        beads_root=beads_root,
        repo_root=repo_root,
        issue_labels=issue_labels,
        issue_parent_id=issue_parent_id,
    )


__all__ = [
    "attempt_create_draft_pr",
    "branch_ref_for_lookup",
    "changeset_base_branch",
    "changeset_integration_signal",
    "changeset_parent_branch",
    "changeset_parent_lifecycle_state",
    "changeset_pr_creation_decision",
    "changeset_pr_url",
    "changeset_review_state",
    "changeset_root_branch",
    "changeset_waiting_on_review",
    "changeset_waiting_on_review_or_signals",
    "changeset_work_branch",
    "close_completed_container_changesets",
    "epic_root_integrated_into_parent",
    "find_invalid_changeset_labels",
    "handle_pushed_without_pr",
    "has_blocking_messages",
    "has_open_descendant_changesets",
    "is_changeset_in_progress",
    "is_changeset_ready",
    "is_changeset_recovery_candidate",
    "list_child_issues",
    "lookup_pr_payload",
    "lookup_pr_payload_diagnostic",
    "mark_changeset_abandoned",
    "mark_changeset_blocked",
    "mark_changeset_children_in_progress",
    "mark_changeset_closed",
    "mark_changeset_in_progress",
    "mark_changeset_merged",
    "promote_planned_descendant_changesets",
    "recover_premature_merged_changeset",
    "release_epic_assignment",
    "render_changeset_pr_body",
    "resolve_epic_id_for_changeset",
    "send_invalid_changeset_labels_notification",
    "send_no_ready_changesets",
    "send_planner_notification",
    "set_changeset_review_pending_state",
    "update_changeset_review_from_pr",
]

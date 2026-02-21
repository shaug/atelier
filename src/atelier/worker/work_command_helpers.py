"""Helper logic for the `atelier work` command.

This module contains worker business logic used by the thin command controller.
"""

from __future__ import annotations

import datetime as dt
import os
import re
from collections.abc import Callable
from pathlib import Path

from .. import (
    agent_home,
    agents,
    beads,
    changeset_fields,
    changesets,
    codex,
    config,
    exec,
    git,
    lifecycle,
    messages,
    pr_strategy,
    prs,
    work_feedback,
    worktrees,
)
from .. import (
    log as atelier_log,
)
from .. import (
    root_branch as root_branch_module,
)
from ..io import die, prompt, say, select
from ..worker import changeset_state as worker_changeset_state
from ..worker import finalize as worker_finalize
from ..worker import finalize_pipeline as worker_finalize_pipeline
from ..worker import integration as worker_integration
from ..worker import prompts as worker_prompts
from ..worker import publish as worker_publish
from ..worker import queueing as worker_queueing
from ..worker import reconcile as worker_reconcile
from ..worker import review as worker_review
from ..worker import selection as worker_selection
from ..worker import telemetry as worker_telemetry
from ..worker.finalization import pr_gate as worker_pr_gate
from ..worker.finalization import recovery as worker_recovery
from ..worker.models import (
    FinalizeResult,
    PublishSignalDiagnostics,
    ReconcileResult,
    StartupContractResult,
    WorkerRunSummary,
)
from ..worker.session import startup as worker_startup

root_branch = root_branch_module

_MODE_VALUES = {"prompt", "auto"}
_RUN_MODE_VALUES = {"once", "default", "watch"}
_WATCH_INTERVAL_SECONDS = 60
_WORKER_QUEUE_NAME = "worker"
_SQUASH_MESSAGE_MODES = {"deterministic", "agent"}
_VALID_CHANGESET_STATE_LABELS = {
    "cs:planned",
    "cs:ready",
    "cs:in_progress",
    "cs:blocked",
    "cs:merged",
    "cs:abandoned",
}
_DEPENDENCY_ID_PATTERN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)\b")


ReviewFeedbackSnapshot = work_feedback.ReviewFeedbackSnapshot
ReviewFeedbackSelection = worker_review.ReviewFeedbackSelection
_ReviewFeedbackSelection = ReviewFeedbackSelection
# Compatibility alias while tests/modules migrate to extracted worker models.
_PublishSignalDiagnostics = PublishSignalDiagnostics


def _normalize_branch_value(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned or cleaned.lower() == "null":
        return None
    return cleaned


def _extract_changeset_root_branch(issue: dict[str, object]) -> str | None:
    description = issue.get("description")
    fields = beads.parse_description_fields(
        description if isinstance(description, str) else ""
    )
    return _normalize_branch_value(fields.get("changeset.root_branch"))


def _extract_workspace_parent_branch(issue: dict[str, object]) -> str | None:
    description = issue.get("description")
    fields = beads.parse_description_fields(
        description if isinstance(description, str) else ""
    )
    return _normalize_branch_value(fields.get("workspace.parent_branch"))


def _issue_parent_id(issue: dict[str, object]) -> str | None:
    parent = issue.get("parent")
    if isinstance(parent, str):
        cleaned = parent.strip()
        return cleaned or None
    if isinstance(parent, dict):
        parent_id = parent.get("id")
        if isinstance(parent_id, str):
            cleaned = parent_id.strip()
            return cleaned or None
    return None


def _parse_dependency_issue_id(value: object) -> str | None:
    if isinstance(value, dict):
        relation = value.get("relation")
        if isinstance(relation, str) and relation.strip().lower() == "parent-child":
            return None
        issue_id = value.get("id")
        if isinstance(issue_id, str):
            cleaned = issue_id.strip()
            return cleaned or None
        nested_issue = value.get("issue")
        if isinstance(nested_issue, dict):
            nested_id = nested_issue.get("id")
            if isinstance(nested_id, str):
                cleaned = nested_id.strip()
                return cleaned or None
        return None

    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if "parent-child" in text.lower():
        return None
    match = _DEPENDENCY_ID_PATTERN.match(text)
    if not match:
        return None
    return match.group(1).strip() or None


def _issue_dependency_ids(issue: dict[str, object]) -> tuple[str, ...]:
    dependencies = issue.get("dependencies")
    if not isinstance(dependencies, list):
        return ()
    ids: list[str] = []
    seen: set[str] = set()
    for dependency in dependencies:
        dependency_id = _parse_dependency_issue_id(dependency)
        if not dependency_id or dependency_id in seen:
            continue
        seen.add(dependency_id)
        ids.append(dependency_id)
    return tuple(ids)


def _dry_run_log(message: str) -> None:
    say(f"DRY-RUN: {message}")


def _log_debug(message: str) -> None:
    atelier_log.debug(f"[work] {message}")


def _trace_enabled() -> bool:
    return worker_telemetry.trace_enabled("ATELIER_WORK_TRACE")


def _step(label: str, *, timings: list[tuple[str, float]], trace: bool) -> callable:
    return worker_telemetry.step(
        label, timings=timings, trace=trace, say=say, log_debug=_log_debug
    )


def _report_timings(timings: list[tuple[str, float]], *, trace: bool) -> None:
    worker_telemetry.report_timings(timings, trace=trace, say=say)


def _report_worker_summary(summary: WorkerRunSummary, *, dry_run: bool) -> None:
    worker_telemetry.report_worker_summary(
        summary, dry_run=dry_run, say=say, log_debug=_log_debug
    )


def _with_codex_exec(cmd: list[str], opening_prompt: str) -> list[str]:
    """Return a codex command rewritten to run non-interactively via `exec`."""
    if not cmd:
        return cmd
    rewritten = list(cmd)
    if opening_prompt and rewritten[-1] == opening_prompt:
        return [*rewritten[:-1], "exec", opening_prompt]
    rewritten.append("exec")
    if opening_prompt:
        rewritten.append(opening_prompt)
    return rewritten


def _strip_flag_with_value(args: list[str], flag: str) -> list[str]:
    """Return args without instances of `flag` and its value."""
    cleaned: list[str] = []
    skip_next = False
    for token in args:
        if skip_next:
            skip_next = False
            continue
        if token == flag:
            skip_next = True
            continue
        if token.startswith(f"{flag}="):
            continue
        cleaned.append(token)
    return cleaned


def _ensure_exec_subcommand_flag(args: list[str], flag: str) -> list[str]:
    """Ensure a flag is present on the codex `exec` subcommand."""
    rewritten = list(args)
    try:
        exec_index = rewritten.index("exec")
    except ValueError:
        return rewritten
    prompt_start = len(rewritten)
    if exec_index + 1 < len(rewritten):
        prompt_start = exec_index + 1
        for index in range(exec_index + 1, len(rewritten)):
            token = rewritten[index]
            if token.startswith("-"):
                continue
            prompt_start = index
            break
    existing = rewritten[exec_index + 1 : prompt_start]
    if flag in existing:
        return rewritten
    rewritten.insert(exec_index + 1, flag)
    return rewritten


def _normalize_mode(value: str | None) -> str:
    if value is None:
        value = os.environ.get("ATELIER_MODE", "prompt")
    normalized = value.strip().lower()
    if normalized not in _MODE_VALUES:
        die("mode must be one of: prompt, auto")
    return normalized


def _normalize_run_mode(value: str | None) -> str:
    if value is None:
        value = os.environ.get("ATELIER_RUN_MODE", "default")
    normalized = value.strip().lower()
    if normalized not in _RUN_MODE_VALUES:
        die("run mode must be one of: once, default, watch")
    return normalized


def _watch_interval_seconds() -> int:
    raw = os.environ.get("ATELIER_WATCH_INTERVAL", "").strip()
    if not raw:
        return _WATCH_INTERVAL_SECONDS
    try:
        value = int(raw)
    except ValueError:
        die("ATELIER_WATCH_INTERVAL must be an integer number of seconds")
    if value <= 0:
        die("ATELIER_WATCH_INTERVAL must be a positive number of seconds")
    return value


def _issue_labels(issue: dict[str, object]) -> set[str]:
    labels = issue.get("labels")
    if not isinstance(labels, list):
        return set()
    return {str(label) for label in labels if label is not None}


def _filter_epics(
    issues: list[dict[str, object]],
    *,
    assignee: str | None = None,
    require_unassigned: bool = False,
) -> list[dict[str, object]]:
    return worker_selection.filter_epics(
        issues,
        assignee=assignee,
        require_unassigned=require_unassigned,
        allow_hooked=assignee is not None,
        skip_draft=True,
    )


def _parse_issue_time(value: object) -> dt.datetime | None:
    return worker_selection.parse_issue_time(value)


def _is_closed_status(status: object) -> bool:
    return lifecycle.is_closed_status(status)


def _is_feedback_eligible_epic_status(status: object) -> bool:
    return not _is_closed_status(status)


def _is_agent_session_active(agent_id: str) -> bool:
    return agent_home.is_session_agent_active(agent_id)


def _select_epic_from_ready_changesets(
    *,
    issues: list[dict[str, object]],
    is_actionable: Callable[[str], bool],
    beads_root: Path,
    repo_root: Path,
) -> str | None:
    ready_changesets = beads.run_bd_json(
        ["ready", "--label", "at:changeset"], beads_root=beads_root, cwd=repo_root
    )
    return worker_selection.select_epic_from_ready_changesets(
        issues=issues,
        ready_changesets=ready_changesets,
        is_actionable=is_actionable,
    )


def _send_planner_notification(
    *,
    subject: str,
    body: str,
    agent_id: str,
    thread_id: str | None,
    beads_root: Path,
    repo_root: Path,
    dry_run: bool,
) -> None:
    worker_queueing.send_planner_notification(
        subject=subject,
        body=body,
        agent_id=agent_id,
        thread_id=thread_id,
        beads_root=beads_root,
        repo_root=repo_root,
        dry_run=dry_run,
        dry_run_log=_dry_run_log,
    )


def _send_invalid_changeset_labels_notification(
    *,
    epic_id: str,
    invalid_changesets: list[str],
    agent_id: str,
    beads_root: Path,
    repo_root: Path,
    dry_run: bool,
) -> str:
    return worker_queueing.send_invalid_changeset_labels_notification(
        epic_id=epic_id,
        invalid_changesets=invalid_changesets,
        agent_id=agent_id,
        beads_root=beads_root,
        repo_root=repo_root,
        dry_run=dry_run,
        dry_run_log=_dry_run_log,
    )


def _send_no_ready_changesets(
    *,
    epic_id: str,
    agent_id: str,
    beads_root: Path,
    repo_root: Path,
    dry_run: bool,
) -> None:
    worker_queueing.send_no_ready_changesets(
        epic_id=epic_id,
        agent_id=agent_id,
        beads_root=beads_root,
        repo_root=repo_root,
        dry_run=dry_run,
        dry_run_log=_dry_run_log,
    )


def _release_epic_assignment(
    epic_id: str, *, beads_root: Path, repo_root: Path
) -> None:
    issues = beads.run_bd_json(["show", epic_id], beads_root=beads_root, cwd=repo_root)
    if not issues:
        return
    issue = issues[0]
    labels = _issue_labels(issue)
    status = str(issue.get("status") or "")
    args = ["update", epic_id, "--assignee", ""]
    if "at:hooked" in labels:
        args.extend(["--remove-label", "at:hooked"])
    if status and status not in {"closed", "done"}:
        args.extend(["--status", "open"])
    beads.run_bd_command(args, beads_root=beads_root, cwd=repo_root, allow_failure=True)


def _next_changeset(
    *,
    epic_id: str,
    beads_root: Path,
    repo_root: Path,
    repo_slug: str | None = None,
    branch_pr: bool = True,
    branch_pr_strategy: object = pr_strategy.PR_STRATEGY_DEFAULT,
    git_path: str | None = None,
) -> dict[str, object] | None:
    return worker_startup.next_changeset(
        epic_id=epic_id,
        beads_root=beads_root,
        repo_root=repo_root,
        repo_slug=repo_slug,
        branch_pr=branch_pr,
        branch_pr_strategy=branch_pr_strategy,
        git_path=git_path,
        issue_labels=_issue_labels,
        is_changeset_ready=_is_changeset_ready,
        changeset_waiting_on_review_or_signals=_changeset_waiting_on_review_or_signals,
        is_changeset_recovery_candidate=_is_changeset_recovery_candidate,
        has_open_descendant_changesets=_has_open_descendant_changesets,
        run_bd_json=beads.run_bd_json,
        list_descendant_changesets=beads.list_descendant_changesets,
        is_changeset_in_progress=_is_changeset_in_progress,
    )


def _has_open_descendant_changesets(
    changeset_id: str, *, beads_root: Path, repo_root: Path
) -> bool:
    descendants = beads.list_descendant_changesets(
        changeset_id,
        beads_root=beads_root,
        cwd=repo_root,
        include_closed=False,
    )
    return bool(descendants)


def _is_changeset_in_progress(issue: dict[str, object]) -> bool:
    return lifecycle.is_changeset_in_progress(issue.get("status"), _issue_labels(issue))


def _is_changeset_ready(issue: dict[str, object]) -> bool:
    return lifecycle.is_changeset_ready(issue.get("status"), _issue_labels(issue))


def _changeset_review_state(issue: dict[str, object]) -> str | None:
    return changeset_fields.review_state(issue)


def _changeset_waiting_on_review(issue: dict[str, object]) -> bool:
    state = _changeset_review_state(issue)
    if state is None:
        return False
    return state in {"pushed", "draft-pr", "pr-open", "in-review", "approved"}


def _changeset_work_branch(issue: dict[str, object]) -> str | None:
    return changeset_fields.work_branch(issue)


def _changeset_pr_url(issue: dict[str, object]) -> str | None:
    return changeset_fields.pr_url(issue)


def _lookup_pr_payload(repo_slug: str | None, branch: str) -> dict[str, object] | None:
    """Lookup PR payload for a branch."""
    if not repo_slug:
        return None
    return prs.read_github_pr_status(repo_slug, branch)


def _lookup_pr_payload_diagnostic(
    repo_slug: str | None, branch: str
) -> tuple[dict[str, object] | None, str | None]:
    """Lookup PR payload with explicit query-failure diagnostics."""
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


def _changeset_root_branch(issue: dict[str, object]) -> str | None:
    return changeset_fields.root_branch(issue)


def _changeset_base_branch(
    issue: dict[str, object],
    *,
    beads_root: Path | None = None,
    repo_root: Path,
    git_path: str | None,
) -> str | None:
    description = issue.get("description")
    fields = beads.parse_description_fields(
        description if isinstance(description, str) else ""
    )
    root_branch = _changeset_root_branch(issue)
    parent_branch = _changeset_parent_branch(issue, root_branch=root_branch or "")
    workspace_parent_branch = fields.get("workspace.parent_branch")
    normalized_parent = parent_branch.strip() if isinstance(parent_branch, str) else ""
    normalized_root = root_branch.strip() if isinstance(root_branch, str) else ""
    normalized_workspace_parent = (
        workspace_parent_branch.strip()
        if isinstance(workspace_parent_branch, str)
        else ""
    )
    if (
        not normalized_workspace_parent
        and beads_root is not None
        and normalized_root
        and normalized_parent
        and normalized_parent == normalized_root
    ):
        epic_id = _resolve_epic_id_for_changeset(
            issue, beads_root=beads_root, repo_root=repo_root
        )
        if epic_id:
            epic_issues = beads.run_bd_json(
                ["show", epic_id], beads_root=beads_root, cwd=repo_root
            )
            if epic_issues:
                resolved_parent = _extract_workspace_parent_branch(epic_issues[0])
                if resolved_parent:
                    normalized_workspace_parent = resolved_parent
    # Top-level changesets often persisted parent=root; use workspace parent for
    # PR base when available so PR creation targets mainline, not the root branch.
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


def _render_changeset_pr_body(issue: dict[str, object]) -> str:
    description = issue.get("description")
    fields = beads.parse_description_fields(
        description if isinstance(description, str) else ""
    )
    return worker_publish.render_changeset_pr_body(issue, fields=fields)


def _attempt_create_draft_pr(
    *,
    repo_slug: str,
    issue: dict[str, object],
    work_branch: str,
    beads_root: Path,
    repo_root: Path,
    git_path: str | None,
    changeset_base_branch: Callable[..., str] | None = None,
    render_changeset_pr_body: Callable[[dict[str, object]], str] | None = None,
) -> tuple[bool, str]:
    return worker_pr_gate.attempt_create_draft_pr(
        repo_slug=repo_slug,
        issue=issue,
        work_branch=work_branch,
        beads_root=beads_root,
        repo_root=repo_root,
        git_path=git_path,
        changeset_base_branch=changeset_base_branch or _changeset_base_branch,
        render_changeset_pr_body=render_changeset_pr_body or _render_changeset_pr_body,
    )


def _set_changeset_review_pending_state(
    *,
    changeset_id: str,
    pr_payload: dict[str, object] | None,
    pushed: bool,
    fallback_pr_state: str | None,
    beads_root: Path,
    repo_root: Path,
) -> None:
    worker_pr_gate.set_changeset_review_pending_state(
        changeset_id=changeset_id,
        pr_payload=pr_payload,
        pushed=pushed,
        fallback_pr_state=fallback_pr_state,
        beads_root=beads_root,
        repo_root=repo_root,
        mark_changeset_in_progress=_mark_changeset_in_progress,
        update_changeset_review_from_pr=_update_changeset_review_from_pr,
    )


def _update_changeset_review_from_pr(
    changeset_id: str,
    *,
    pr_payload: dict[str, object] | None,
    pushed: bool,
    beads_root: Path,
    repo_root: Path,
) -> None:
    if not pr_payload:
        return
    review_requested = prs.has_review_requests(pr_payload)
    lifecycle = prs.lifecycle_state(
        pr_payload, pushed=pushed, review_requested=review_requested
    )
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


def _handle_pushed_without_pr(
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
        changeset_base_branch=_changeset_base_branch,
        changeset_work_branch=_changeset_work_branch,
        render_changeset_pr_body=_render_changeset_pr_body,
        lookup_pr_payload=_lookup_pr_payload,
        lookup_pr_payload_diagnostic=_lookup_pr_payload_diagnostic,
        mark_changeset_in_progress=_mark_changeset_in_progress,
        send_planner_notification=_send_planner_notification,
        update_changeset_review_from_pr=_update_changeset_review_from_pr,
        emit=say,
        attempt_create_draft_pr_fn=_attempt_create_draft_pr,
    )
    return gate_result.finalize_result


def _changeset_parent_lifecycle_state(
    issue: dict[str, object],
    *,
    repo_slug: str | None,
    repo_root: Path,
    git_path: str | None,
) -> str | None:
    return worker_pr_gate.changeset_parent_lifecycle_state(
        issue,
        repo_slug=repo_slug,
        repo_root=repo_root,
        git_path=git_path,
        lookup_pr_payload=_lookup_pr_payload,
    )


def _changeset_pr_creation_decision(
    issue: dict[str, object],
    *,
    repo_slug: str | None,
    repo_root: Path,
    git_path: str | None,
    branch_pr_strategy: object,
) -> pr_strategy.PrStrategyDecision:
    return worker_pr_gate.changeset_pr_creation_decision(
        issue,
        repo_slug=repo_slug,
        repo_root=repo_root,
        git_path=git_path,
        branch_pr_strategy=branch_pr_strategy,
        lookup_pr_payload=_lookup_pr_payload,
    )


def _recover_premature_merged_changeset(
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
) -> FinalizeResult | None:
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
        changeset_work_branch=_changeset_work_branch,
        lookup_pr_payload=_lookup_pr_payload,
        lookup_pr_payload_diagnostic=_lookup_pr_payload_diagnostic,
        changeset_integration_signal=_changeset_integration_signal,
        finalize_terminal_changeset=_finalize_terminal_changeset,
        mark_changeset_in_progress=_mark_changeset_in_progress,
        update_changeset_review_from_pr=_update_changeset_review_from_pr,
        handle_pushed_without_pr=_handle_pushed_without_pr,
    )


def _changeset_waiting_on_review_or_signals(
    issue: dict[str, object],
    *,
    repo_slug: str | None,
    repo_root: Path,
    branch_pr: bool,
    branch_pr_strategy: object,
    git_path: str | None,
) -> bool:
    if not branch_pr:
        return False
    work_branch = _changeset_work_branch(issue)
    if work_branch:
        pushed = git.git_ref_exists(
            repo_root, f"refs/remotes/origin/{work_branch}", git_path=git_path
        )
        pr_payload = _lookup_pr_payload(repo_slug, work_branch)
        review_requested = prs.has_review_requests(pr_payload)
        state = prs.lifecycle_state(
            pr_payload, pushed=pushed, review_requested=review_requested
        )
        if state in {"merged", "closed"}:
            return False
        if state in {"draft-pr", "pr-open", "in-review", "approved"}:
            return True
        if state == "pushed":
            decision = _changeset_pr_creation_decision(
                issue,
                repo_slug=repo_slug,
                repo_root=repo_root,
                git_path=git_path,
                branch_pr_strategy=branch_pr_strategy,
            )
            return not decision.allow_pr
    review_state = _changeset_review_state(issue)
    if review_state:
        if review_state in {"draft-pr", "pr-open", "in-review", "approved"}:
            return True
        if review_state == "pushed":
            decision = _changeset_pr_creation_decision(
                issue,
                repo_slug=repo_slug,
                repo_root=repo_root,
                git_path=git_path,
                branch_pr_strategy=branch_pr_strategy,
            )
            return not decision.allow_pr
    return False


def _is_changeset_recovery_candidate(
    issue: dict[str, object],
    *,
    repo_slug: str | None,
    repo_root: Path,
    branch_pr: bool,
    git_path: str | None,
) -> bool:
    """Return True when a blocked changeset has enough publish/review signals to retry."""
    labels = _issue_labels(issue)
    status = str(issue.get("status") or "").strip().lower()
    if "cs:blocked" not in labels and status != "blocked":
        return False
    if "cs:merged" in labels or "cs:abandoned" in labels:
        return False
    if status in {"closed", "done"}:
        return False
    work_branch = _changeset_work_branch(issue)
    if not work_branch:
        return False
    pushed = git.git_ref_exists(
        repo_root, f"refs/remotes/origin/{work_branch}", git_path=git_path
    )
    if branch_pr:
        pr_payload = _lookup_pr_payload(repo_slug, work_branch)
        review_requested = prs.has_review_requests(pr_payload)
        lifecycle = prs.lifecycle_state(
            pr_payload, pushed=pushed, review_requested=review_requested
        )
        if lifecycle in {"pushed", "draft-pr", "pr-open", "in-review", "approved"}:
            return True
        review_state = _changeset_review_state(issue)
        return review_state in {
            "pushed",
            "draft-pr",
            "pr-open",
            "in-review",
            "approved",
        }
    return pushed


def _persist_review_feedback_cursor(
    *,
    changeset_id: str,
    issue: dict[str, object],
    repo_slug: str | None,
    beads_root: Path,
    repo_root: Path,
) -> None:
    work_feedback.persist_review_feedback_cursor(
        changeset_id=changeset_id,
        issue=issue,
        repo_slug=repo_slug,
        beads_root=beads_root,
        repo_root=repo_root,
    )


def _capture_review_feedback_snapshot(
    *,
    issue: dict[str, object],
    repo_slug: str | None,
    repo_root: Path,
    git_path: str | None,
) -> ReviewFeedbackSnapshot:
    return work_feedback.capture_review_feedback_snapshot(
        issue=issue,
        repo_slug=repo_slug,
        repo_root=repo_root,
        git_path=git_path,
    )


def _review_feedback_progressed(
    before: ReviewFeedbackSnapshot, after: ReviewFeedbackSnapshot
) -> bool:
    return work_feedback.review_feedback_progressed(before, after)


def _select_review_feedback_changeset(
    *,
    epic_id: str,
    repo_slug: str | None,
    beads_root: Path,
    repo_root: Path,
) -> ReviewFeedbackSelection | None:
    return worker_review.select_review_feedback_changeset(
        epic_id=epic_id,
        repo_slug=repo_slug,
        beads_root=beads_root,
        repo_root=repo_root,
    )


def _select_global_review_feedback_changeset(
    *,
    repo_slug: str | None,
    beads_root: Path,
    repo_root: Path,
) -> ReviewFeedbackSelection | None:
    return worker_review.select_global_review_feedback_changeset(
        repo_slug=repo_slug,
        beads_root=beads_root,
        repo_root=repo_root,
        resolve_epic_id_for_changeset=(
            lambda issue: (
                _resolve_epic_id_for_changeset(
                    issue, beads_root=beads_root, repo_root=repo_root
                )
                or str(issue.get("id") or "")
                or None
            )
        ),
    )


def _list_child_issues(
    parent_id: str, *, beads_root: Path, repo_root: Path, include_closed: bool = False
) -> list[dict[str, object]]:
    return worker_changeset_state.list_child_issues(
        parent_id,
        beads_root=beads_root,
        repo_root=repo_root,
        include_closed=include_closed,
    )


def _find_invalid_changeset_labels(
    root_id: str, *, beads_root: Path, repo_root: Path
) -> list[str]:
    return worker_changeset_state.find_invalid_changeset_labels(
        root_id,
        beads_root=beads_root,
        repo_root=repo_root,
        valid_changeset_state_labels=_VALID_CHANGESET_STATE_LABELS,
    )


def _changeset_parent_branch(issue: dict[str, object], *, root_branch: str) -> str:
    description = issue.get("description")
    fields = beads.parse_description_fields(
        description if isinstance(description, str) else ""
    )
    parent_branch = fields.get("changeset.parent_branch")
    if not parent_branch:
        return root_branch
    normalized = parent_branch.strip()
    if not normalized or normalized.lower() == "null":
        return root_branch
    return normalized


def _resolve_hooked_epic(
    agent_bead_id: str,
    agent_id: str,
    *,
    beads_root: Path,
    repo_root: Path,
) -> str | None:
    hook_id = beads.get_agent_hook(agent_bead_id, beads_root=beads_root, cwd=repo_root)
    if not hook_id:
        return None
    issues = beads.run_bd_json(["show", hook_id], beads_root=beads_root, cwd=repo_root)
    if not issues:
        return None
    epic = issues[0]
    status = str(epic.get("status") or "").lower()
    if status in {"closed", "done"}:
        return None
    assignee = epic.get("assignee")
    if assignee and assignee != agent_id:
        return None
    if assignee != agent_id:
        return None
    return hook_id


def _mark_changeset_in_progress(
    changeset_id: str, *, beads_root: Path, repo_root: Path
) -> None:
    worker_changeset_state.mark_changeset_in_progress(
        changeset_id,
        beads_root=beads_root,
        repo_root=repo_root,
    )


def _mark_changeset_closed(
    changeset_id: str, *, beads_root: Path, repo_root: Path
) -> None:
    worker_changeset_state.mark_changeset_closed(
        changeset_id,
        beads_root=beads_root,
        repo_root=repo_root,
    )


def _mark_changeset_merged(
    changeset_id: str, *, beads_root: Path, repo_root: Path
) -> None:
    worker_changeset_state.mark_changeset_merged(
        changeset_id,
        beads_root=beads_root,
        repo_root=repo_root,
    )


def _mark_changeset_abandoned(
    changeset_id: str, *, beads_root: Path, repo_root: Path
) -> None:
    worker_changeset_state.mark_changeset_abandoned(
        changeset_id,
        beads_root=beads_root,
        repo_root=repo_root,
    )


def _mark_changeset_blocked(
    changeset_id: str, *, beads_root: Path, repo_root: Path, reason: str
) -> None:
    worker_changeset_state.mark_changeset_blocked(
        changeset_id,
        beads_root=beads_root,
        repo_root=repo_root,
        reason=reason,
    )


def _mark_changeset_children_in_progress(
    changeset_id: str, *, beads_root: Path, repo_root: Path
) -> None:
    worker_changeset_state.mark_changeset_children_in_progress(
        changeset_id,
        beads_root=beads_root,
        repo_root=repo_root,
    )


def _close_completed_container_changesets(
    epic_id: str, *, beads_root: Path, repo_root: Path
) -> list[str]:
    return worker_changeset_state.close_completed_container_changesets(
        epic_id,
        beads_root=beads_root,
        repo_root=repo_root,
        has_open_descendant_changesets=lambda issue_id: _has_open_descendant_changesets(
            issue_id, beads_root=beads_root, repo_root=repo_root
        ),
    )


def _promote_planned_descendant_changesets(
    changeset_id: str, *, beads_root: Path, repo_root: Path
) -> list[str]:
    return worker_changeset_state.promote_planned_descendant_changesets(
        changeset_id, beads_root=beads_root, repo_root=repo_root
    )


def _has_blocking_messages(
    *,
    thread_ids: set[str],
    started_at: dt.datetime,
    beads_root: Path,
    repo_root: Path,
) -> bool:
    issues = beads.run_bd_json(
        ["list", "--label", "at:message", "--label", "at:unread"],
        beads_root=beads_root,
        cwd=repo_root,
    )
    for issue in issues:
        created_at = _parse_issue_time(issue.get("created_at"))
        if created_at is not None and created_at < started_at:
            continue
        description = issue.get("description")
        payload = messages.parse_message(
            description if isinstance(description, str) else ""
        )
        thread = payload.metadata.get("thread")
        if isinstance(thread, str) and thread in thread_ids:
            return True
    return False


def _branch_ref_for_lookup(
    repo_root: Path, branch: str, *, git_path: str | None = None
) -> str | None:
    return worker_integration.branch_ref_for_lookup(
        repo_root, branch, git_path=git_path
    )


def _epic_root_integrated_into_parent(
    epic_issue: dict[str, object],
    *,
    repo_root: Path,
    git_path: str | None = None,
) -> bool:
    return worker_integration.epic_root_integrated_into_parent(
        epic_issue,
        repo_root=repo_root,
        extract_changeset_root_branch=_extract_changeset_root_branch,
        extract_workspace_parent_branch=_extract_workspace_parent_branch,
        git_path=git_path,
    )


def _changeset_integration_signal(
    issue: dict[str, object],
    *,
    repo_slug: str | None,
    repo_root: Path,
    git_path: str | None = None,
) -> tuple[bool, str | None]:
    return worker_integration.changeset_integration_signal(
        issue,
        repo_slug=repo_slug,
        repo_root=repo_root,
        lookup_pr_payload=_lookup_pr_payload,
        git_path=git_path,
    )


def _resolve_epic_id_for_changeset(
    issue: dict[str, object], *, beads_root: Path, repo_root: Path
) -> str | None:
    current = issue
    current_id = issue.get("id")
    if not isinstance(current_id, str) or not current_id.strip():
        return None
    visited: set[str] = set()
    while True:
        issue_id = current_id.strip()
        if not issue_id or issue_id in visited:
            return None
        visited.add(issue_id)
        labels = _issue_labels(current)
        if "at:epic" in labels:
            return issue_id
        parent_id = _issue_parent_id(current)
        if not parent_id:
            # `bd list` payloads can omit parent details; refresh full issue once.
            if current is issue:
                loaded = beads.run_bd_json(
                    ["show", issue_id], beads_root=beads_root, cwd=repo_root
                )
                if loaded:
                    refreshed = loaded[0]
                    refreshed_parent = _issue_parent_id(refreshed)
                    if refreshed_parent:
                        current = refreshed
                        parent_id = refreshed_parent
                        current_id = issue_id
            # Standalone top-level changeset can act as its own epic root.
            if not parent_id:
                return issue_id
        parent_issues = beads.run_bd_json(
            ["show", parent_id], beads_root=beads_root, cwd=repo_root
        )
        if not parent_issues:
            return parent_id
        current = parent_issues[0]
        current_id = parent_id


def list_reconcile_epic_candidates(
    *,
    project_config: config.ProjectConfig,
    beads_root: Path,
    repo_root: Path,
    git_path: str | None = None,
) -> dict[str, list[str]]:
    return worker_reconcile.list_reconcile_epic_candidates(
        project_config=project_config,
        beads_root=beads_root,
        repo_root=repo_root,
        git_path=git_path,
        changeset_integration_signal=_changeset_integration_signal,
        resolve_epic_id_for_changeset=_resolve_epic_id_for_changeset,
        is_closed_status=_is_closed_status,
        epic_root_integrated_into_parent=_epic_root_integrated_into_parent,
    )


def reconcile_blocked_merged_changesets(
    *,
    agent_id: str,
    agent_bead_id: str | None,
    project_config: config.ProjectConfig,
    project_data_dir: Path | None,
    beads_root: Path,
    repo_root: Path,
    git_path: str | None = None,
    epic_filter: str | None = None,
    changeset_filter: set[str] | None = None,
    dry_run: bool = False,
    log: Callable[[str], None] | None = None,
) -> ReconcileResult:
    return worker_reconcile.reconcile_blocked_merged_changesets(
        agent_id=agent_id,
        agent_bead_id=agent_bead_id,
        project_config=project_config,
        project_data_dir=project_data_dir,
        beads_root=beads_root,
        repo_root=repo_root,
        git_path=git_path,
        epic_filter=epic_filter,
        changeset_filter=changeset_filter,
        dry_run=dry_run,
        log=log,
        resolve_epic_id_for_changeset=_resolve_epic_id_for_changeset,
        changeset_integration_signal=_changeset_integration_signal,
        issue_dependency_ids=_issue_dependency_ids,
        issue_labels=_issue_labels,
        finalize_changeset=_finalize_changeset,
        finalize_epic_if_complete=_finalize_epic_if_complete,
    )


def _epic_ready_to_finalize(epic_id: str, *, beads_root: Path, repo_root: Path) -> bool:
    issues = beads.run_bd_json(["show", epic_id], beads_root=beads_root, cwd=repo_root)
    if not issues:
        return False
    issue = issues[0]
    labels = _issue_labels(issue)
    if "at:changeset" in labels and ("cs:merged" in labels or "cs:abandoned" in labels):
        return True
    summary = beads.epic_changeset_summary(
        epic_id, beads_root=beads_root, cwd=repo_root
    )
    return summary.ready_to_close


def _ensure_local_branch(
    branch: str, *, repo_root: Path, git_path: str | None = None
) -> bool:
    branch_name = branch.strip()
    if not branch_name:
        return False
    if git.git_ref_exists(repo_root, f"refs/heads/{branch_name}", git_path=git_path):
        return True
    if not git.git_ref_exists(
        repo_root, f"refs/remotes/origin/{branch_name}", git_path=git_path
    ):
        return False
    result = exec.try_run_command(
        git.git_command(
            [
                "-C",
                str(repo_root),
                "branch",
                branch_name,
                f"origin/{branch_name}",
            ],
            git_path=git_path,
        )
    )
    return bool(result and result.returncode == 0)


def _run_git_status(
    args: list[str],
    *,
    repo_root: Path,
    git_path: str | None = None,
    cwd: Path | None = None,
) -> tuple[bool, str]:
    target_cwd = cwd or repo_root
    result = exec.try_run_command(
        git.git_command(["-C", str(target_cwd), *args], git_path=git_path)
    )
    if result is None:
        return False, "missing required command: git"
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        return False, detail or f"command failed: git {' '.join(args)}"
    return True, (result.stdout or "").strip()


def _resolve_epic_integration_cwd(
    *,
    project_data_dir: Path | None,
    repo_root: Path,
    epic_id: str,
    root_branch: str,
    git_path: str | None = None,
) -> Path:
    """Prefer the epic worktree when it has the root branch checked out."""
    if project_data_dir is None or not epic_id:
        return repo_root
    mapping = worktrees.load_mapping(worktrees.mapping_path(project_data_dir, epic_id))
    if mapping is None or not mapping.worktree_path:
        return repo_root
    worktree_path = Path(mapping.worktree_path)
    if not worktree_path.is_absolute():
        worktree_path = project_data_dir / worktree_path
    if not worktree_path.exists() or not (worktree_path / ".git").exists():
        return repo_root
    current_branch = git.git_current_branch(worktree_path, git_path=git_path)
    if current_branch == root_branch:
        return worktree_path
    return repo_root


def _resolve_changeset_worktree_path(
    *,
    project_data_dir: Path | None,
    epic_id: str,
    changeset_id: str,
) -> Path | None:
    if project_data_dir is None or not epic_id or not changeset_id:
        return None
    mapping = worktrees.load_mapping(worktrees.mapping_path(project_data_dir, epic_id))
    if mapping is None:
        return None
    relpath = mapping.changeset_worktrees.get(changeset_id)
    if not relpath:
        return None
    worktree_path = Path(relpath)
    if not worktree_path.is_absolute():
        worktree_path = project_data_dir / worktree_path
    if not worktree_path.exists() or not (worktree_path / ".git").exists():
        return None
    return worktree_path


def _collect_publish_signal_diagnostics(
    *,
    work_branch: str,
    epic_id: str,
    changeset_id: str,
    project_data_dir: Path | None,
    repo_root: Path,
    git_path: str | None,
) -> PublishSignalDiagnostics:
    local_branch_exists = git.git_ref_exists(
        repo_root, f"refs/heads/{work_branch}", git_path=git_path
    )
    remote_branch_exists = git.git_ref_exists(
        repo_root, f"refs/remotes/origin/{work_branch}", git_path=git_path
    )
    worktree_path = _resolve_changeset_worktree_path(
        project_data_dir=project_data_dir,
        epic_id=epic_id,
        changeset_id=changeset_id,
    )
    status_root = worktree_path or repo_root
    dirty_entries = tuple(git.git_status_porcelain(status_root, git_path=git_path))
    return PublishSignalDiagnostics(
        local_branch_exists=local_branch_exists,
        remote_branch_exists=remote_branch_exists,
        worktree_path=worktree_path,
        dirty_entries=dirty_entries,
    )


def _attempt_push_work_branch(
    work_branch: str, *, repo_root: Path, git_path: str | None = None
) -> tuple[bool, str]:
    if not git.git_ref_exists(
        repo_root, f"refs/heads/{work_branch}", git_path=git_path
    ):
        return False, f"local branch missing: {work_branch}"
    ok, detail = _run_git_status(
        ["push", "-u", "origin", work_branch], repo_root=repo_root, git_path=git_path
    )
    if ok:
        return True, detail or f"pushed {work_branch} to origin"
    return False, detail


def _format_publish_diagnostics(
    diagnostics: PublishSignalDiagnostics, *, push_detail: str | None = None
) -> str:
    lines = [
        f"- local branch exists: {'yes' if diagnostics.local_branch_exists else 'no'}",
        f"- remote branch exists: {'yes' if diagnostics.remote_branch_exists else 'no'}",
    ]
    if diagnostics.worktree_path is not None:
        lines.append(f"- changeset worktree: {diagnostics.worktree_path}")
    if diagnostics.dirty_entries:
        lines.append("- dirty files:")
        for entry in diagnostics.dirty_entries[:8]:
            lines.append(f"  - {entry}")
        if len(diagnostics.dirty_entries) > 8:
            lines.append(f"  - ... (+{len(diagnostics.dirty_entries) - 8} more)")
    if push_detail:
        lines.append(f"- push attempt: {push_detail}")
    return "\n".join(lines)


def _ensure_branch_not_checked_out(
    branch: str, *, repo_root: Path, git_path: str | None = None
) -> None:
    current = git.git_current_branch(repo_root, git_path=git_path)
    if current != branch:
        return
    _run_git_status(["checkout", "--detach"], repo_root=repo_root, git_path=git_path)


def _sync_local_branch_from_remote(
    branch: str, *, repo_root: Path, git_path: str | None = None
) -> bool:
    branch_name = branch.strip()
    if not branch_name:
        return False
    if not git.git_ref_exists(
        repo_root, f"refs/remotes/origin/{branch_name}", git_path=git_path
    ):
        return False
    _ensure_branch_not_checked_out(branch_name, repo_root=repo_root, git_path=git_path)
    ok, _ = _run_git_status(
        ["branch", "-f", branch_name, f"origin/{branch_name}"],
        repo_root=repo_root,
        git_path=git_path,
    )
    return ok


def _first_external_ticket_id(issue: dict[str, object]) -> str | None:
    description = issue.get("description")
    tickets = beads.parse_external_tickets(
        description if isinstance(description, str) else None
    )
    if not tickets:
        return None
    primary = [ticket for ticket in tickets if ticket.relation == "primary"]
    source = primary or tickets
    for ticket in source:
        ticket_id = (ticket.ticket_id or "").strip()
        if ticket_id:
            return ticket_id
    return None


def _squash_subject(issue: dict[str, object], *, epic_id: str) -> str:
    ticket_id = _first_external_ticket_id(issue)
    title = str(issue.get("title") or "").strip()
    if ticket_id and title:
        return f"{ticket_id}: {title}"
    if ticket_id:
        return ticket_id
    if title:
        return title
    return epic_id


def _normalize_squash_message_mode(value: object) -> str:
    if not isinstance(value, str):
        return "deterministic"
    normalized = value.strip().lower()
    if normalized in _SQUASH_MESSAGE_MODES:
        return normalized
    return "deterministic"


def _parse_squash_subject_output(output: str) -> str | None:
    cleaned = codex.strip_ansi(output).replace("\r", "\n")
    for raw_line in cleaned.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        lowered = line.lower()
        if lowered in {"thinking", "user", "assistant", "codex", "--------"}:
            continue
        if lowered.startswith(
            (
                "warning:",
                "deprecated:",
                "mcp:",
                "tokens used",
                "openai codex",
                "session id:",
            )
        ):
            continue
        line = line.strip("`\"'").strip()
        if line.startswith(("-", "*")):
            line = line[1:].strip()
        line = " ".join(line.split())
        if line:
            return line[:120]
    return None


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
    if agent_spec is None or agent_home is None:
        return None
    if agent_spec.name != "codex":
        return None

    commit_messages = git.git_commit_messages(
        repo_root,
        parent_branch,
        root_branch,
        git_path=git_path,
    )
    files_changed = git.git_diff_name_status(
        repo_root,
        parent_branch,
        root_branch,
        git_path=git_path,
    )
    ticket_id = _first_external_ticket_id(epic_issue) or "none"
    title = str(epic_issue.get("title") or epic_id).strip() or epic_id
    commits_preview = (
        "\n".join(f"- {message}" for message in commit_messages[:12] if message)
        or "- (none)"
    )
    files_preview = "\n".join(
        f"- {entry}" for entry in files_changed[:30] if entry
    ) or ("- (none)")
    prompt_text = "\n".join(
        [
            "Draft a single git squash commit subject for integrating an epic branch.",
            "",
            "Constraints:",
            "- Output exactly one line (no markdown, no bullets, no quotes).",
            "- Imperative mood, no trailing period.",
            "- Maximum 72 characters.",
            "",
            f"Epic id: {epic_id}",
            f"Primary ticket: {ticket_id}",
            f"Epic title: {title}",
            f"Parent branch: {parent_branch}",
            f"Root branch: {root_branch}",
            "",
            "Commit messages being squashed:",
            commits_preview,
            "",
            "Changed files:",
            files_preview,
            "",
            "Return only the commit subject.",
        ]
    )

    start_cmd, start_cwd = agent_spec.build_start_command(
        agent_home,
        list(agent_options or []),
        prompt_text,
    )
    start_cmd = _with_codex_exec(start_cmd, prompt_text)
    start_cmd = _strip_flag_with_value(start_cmd, "--cd")
    start_cmd = _ensure_exec_subcommand_flag(start_cmd, "--skip-git-repo-check")
    start_cwd = agent_home
    result = exec.try_run_command(start_cmd, cwd=start_cwd, env=agent_env)
    if result is None or result.returncode != 0:
        return None
    parsed = _parse_squash_subject_output(result.stdout or "")
    if parsed:
        return parsed
    return _parse_squash_subject_output(result.stderr or "")


def _cleanup_epic_branches_and_worktrees(
    *,
    project_data_dir: Path | None,
    repo_root: Path,
    epic_id: str,
    keep_branches: set[str] | None = None,
    git_path: str | None = None,
    log: Callable[[str], None] | None = None,
) -> None:
    worker_integration.cleanup_epic_branches_and_worktrees(
        project_data_dir=project_data_dir,
        repo_root=repo_root,
        epic_id=epic_id,
        keep_branches=keep_branches,
        git_path=git_path,
        log=log,
        run_git_status=_run_git_status,
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
    return worker_integration.integrate_epic_root_to_parent(
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
        ensure_local_branch=_ensure_local_branch,
        run_git_status=_run_git_status,
        sync_local_branch_from_remote=_sync_local_branch_from_remote,
        normalize_squash_message_mode=_normalize_squash_message_mode,
        agent_generated_squash_subject=_agent_generated_squash_subject,
        squash_subject=lambda issue, eid: _squash_subject(issue, epic_id=eid),
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
        normalize_branch_value=_normalize_branch_value,
        extract_changeset_root_branch=_extract_changeset_root_branch,
        send_planner_notification=_send_planner_notification,
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
            mark_changeset_merged=lambda target_id: _mark_changeset_merged(
                target_id, beads_root=beads_root, repo_root=repo_root
            ),
            mark_changeset_abandoned=lambda target_id: _mark_changeset_abandoned(
                target_id, beads_root=beads_root, repo_root=repo_root
            ),
            close_completed_container_changesets=lambda target_epic_id: (
                _close_completed_container_changesets(
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


def _finalize_changeset(
    *,
    changeset_id: str,
    epic_id: str,
    agent_id: str,
    agent_bead_id: str,
    started_at: dt.datetime,
    repo_slug: str | None,
    beads_root: Path,
    repo_root: Path,
    branch_pr: bool = True,
    branch_pr_strategy: object = pr_strategy.PR_STRATEGY_DEFAULT,
    branch_history: str = "manual",
    branch_squash_message: str = "deterministic",
    project_data_dir: Path | None = None,
    squash_message_agent_spec: agents.AgentSpec | None = None,
    squash_message_agent_options: list[str] | None = None,
    squash_message_agent_home: Path | None = None,
    squash_message_agent_env: dict[str, str] | None = None,
    git_path: str | None = None,
) -> FinalizeResult:
    return worker_finalize_pipeline.run_finalize_pipeline(
        changeset_id=changeset_id,
        epic_id=epic_id,
        agent_id=agent_id,
        agent_bead_id=agent_bead_id,
        started_at=started_at,
        repo_slug=repo_slug,
        beads_root=beads_root,
        repo_root=repo_root,
        branch_pr=branch_pr,
        branch_pr_strategy=branch_pr_strategy,
        branch_history=branch_history,
        branch_squash_message=branch_squash_message,
        project_data_dir=project_data_dir,
        squash_message_agent_spec=squash_message_agent_spec,
        squash_message_agent_options=squash_message_agent_options,
        squash_message_agent_home=squash_message_agent_home,
        squash_message_agent_env=squash_message_agent_env,
        git_path=git_path,
        issue_labels=_issue_labels,
        find_invalid_changeset_labels=_find_invalid_changeset_labels,
        send_invalid_changeset_labels_notification=_send_invalid_changeset_labels_notification,
        has_open_descendant_changesets=_has_open_descendant_changesets,
        has_blocking_messages=_has_blocking_messages,
        mark_changeset_children_in_progress=_mark_changeset_children_in_progress,
        close_completed_container_changesets=_close_completed_container_changesets,
        promote_planned_descendant_changesets=_promote_planned_descendant_changesets,
        changeset_integration_signal=_changeset_integration_signal,
        recover_premature_merged_changeset=_recover_premature_merged_changeset,
        mark_changeset_blocked=_mark_changeset_blocked,
        send_planner_notification=_send_planner_notification,
        mark_changeset_closed=_mark_changeset_closed,
        finalize_epic_if_complete=_finalize_epic_if_complete,
        mark_changeset_in_progress=_mark_changeset_in_progress,
        changeset_waiting_on_review_or_signals=_changeset_waiting_on_review_or_signals,
        lookup_pr_payload=_lookup_pr_payload,
        lookup_pr_payload_diagnostic=_lookup_pr_payload_diagnostic,
        update_changeset_review_from_pr=_update_changeset_review_from_pr,
        finalize_terminal_changeset=_finalize_terminal_changeset,
        handle_pushed_without_pr=_handle_pushed_without_pr,
        attempt_push_work_branch=_attempt_push_work_branch,
        collect_publish_signal_diagnostics=_collect_publish_signal_diagnostics,
        format_publish_diagnostics=_format_publish_diagnostics,
        set_changeset_review_pending_state=_set_changeset_review_pending_state,
    )


def _worker_opening_prompt(
    *,
    project_enlistment: str,
    workspace_branch: str,
    epic_id: str,
    changeset_id: str,
    changeset_title: str,
    review_feedback: bool = False,
    review_pr_url: str | None = None,
) -> str:
    return worker_prompts.worker_opening_prompt(
        project_enlistment=project_enlistment,
        workspace_branch=workspace_branch,
        epic_id=epic_id,
        changeset_id=changeset_id,
        changeset_title=changeset_title,
        review_feedback=review_feedback,
        review_pr_url=review_pr_url,
    )


def _check_inbox_before_claim(
    agent_id: str, *, beads_root: Path, repo_root: Path
) -> bool:
    return worker_queueing.check_inbox_before_claim(
        agent_id,
        beads_root=beads_root,
        repo_root=repo_root,
        emit=say,
    )


def _handle_queue_before_claim(
    agent_id: str,
    *,
    beads_root: Path,
    repo_root: Path,
    queue_name: str | None = _WORKER_QUEUE_NAME,
    force_prompt: bool = False,
    dry_run: bool = False,
    assume_yes: bool = False,
) -> bool:
    return worker_queueing.handle_queue_before_claim(
        agent_id,
        beads_root=beads_root,
        repo_root=repo_root,
        queue_name=queue_name,
        force_prompt=force_prompt,
        dry_run=dry_run,
        assume_yes=assume_yes,
        emit=say,
        prompt_fn=prompt,
        die_fn=die,
        dry_run_log=_dry_run_log,
    )


def _run_startup_contract(
    *,
    agent_id: str,
    agent_bead_id: str | None,
    beads_root: Path,
    repo_root: Path,
    mode: str,
    explicit_epic_id: str | None,
    queue_only: bool,
    dry_run: bool,
    assume_yes: bool,
    repo_slug: str | None = None,
    branch_pr: bool = True,
    branch_pr_strategy: object = pr_strategy.PR_STRATEGY_DEFAULT,
    git_path: str | None = None,
) -> StartupContractResult:
    context = worker_startup.StartupContractContext(
        agent_id=agent_id,
        agent_bead_id=agent_bead_id,
        beads_root=beads_root,
        repo_root=repo_root,
        mode=mode,
        explicit_epic_id=explicit_epic_id,
        queue_only=queue_only,
        dry_run=dry_run,
        assume_yes=assume_yes,
        repo_slug=repo_slug,
        branch_pr=branch_pr,
        branch_pr_strategy=branch_pr_strategy,
        git_path=git_path,
        worker_queue_name=_WORKER_QUEUE_NAME,
    )
    ports = worker_startup.StartupContractPorts(
        handle_queue_before_claim=_handle_queue_before_claim,
        list_epics=lambda *, beads_root, repo_root: beads.run_bd_json(
            ["list", "--label", "at:epic"], beads_root=beads_root, cwd=repo_root
        ),
        next_changeset_fn=_next_changeset,
        resolve_hooked_epic=_resolve_hooked_epic,
        filter_epics=_filter_epics,
        sort_by_created_at=worker_selection.sort_by_created_at,
        stale_family_assigned_epics=lambda issues, agent_id: (
            worker_selection.stale_family_assigned_epics(
                issues,
                agent_id=agent_id,
                is_session_active=agent_home.is_session_agent_active,
            )
        ),
        select_review_feedback_changeset=_select_review_feedback_changeset,
        parse_issue_time=worker_selection.parse_issue_time,
        select_global_review_feedback_changeset=_select_global_review_feedback_changeset,
        is_feedback_eligible_epic_status=_is_feedback_eligible_epic_status,
        issue_labels=_issue_labels,
        check_inbox_before_claim=_check_inbox_before_claim,
        select_epic_auto=worker_selection.select_epic_auto,
        select_epic_prompt=lambda issues, agent_id, is_actionable, assume_yes: (
            worker_selection.select_epic_prompt(
                issues,
                agent_id=agent_id,
                is_actionable=is_actionable,
                extract_root_branch=beads.extract_workspace_root_branch,
                select_fn=lambda title, options: select(title, options),
                assume_yes=assume_yes,
            )
        ),
        select_epic_from_ready_changesets=lambda *, issues, is_actionable, beads_root, repo_root: (
            worker_selection.select_epic_from_ready_changesets(
                issues=issues,
                ready_changesets=beads.run_bd_json(
                    ["ready", "--label", "at:changeset"],
                    beads_root=beads_root,
                    cwd=repo_root,
                ),
                is_actionable=is_actionable,
            )
        ),
        send_needs_decision=lambda *, agent_id, mode, issues, beads_root, repo_root, dry_run: (
            worker_queueing.send_needs_decision(
                agent_id=agent_id,
                mode=mode,
                issues=issues,
                beads_root=beads_root,
                repo_root=repo_root,
                dry_run=dry_run,
                filter_epics=_filter_epics,
                dry_run_log=_dry_run_log,
            )
        ),
        dry_run_log=_dry_run_log,
        emit=say,
        run_bd_json=beads.run_bd_json,
        agent_family_id=worker_selection.agent_family_id,
        is_agent_session_active=_is_agent_session_active,
        die_fn=die,
    )
    return worker_startup.run_startup_contract_service(context=context, ports=ports)

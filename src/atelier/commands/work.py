"""Worker session command implementation.

Starts worker sessions by selecting an epic and its next ready changeset.
``atelier work`` can loop or watch based on run mode.
"""

from __future__ import annotations

import datetime as dt
import os
import re
import time
from collections.abc import Callable
from pathlib import Path

from .. import (
    agent_home,
    agents,
    beads,
    branching,
    changeset_fields,
    changesets,
    codex,
    config,
    exec,
    git,
    hooks,
    lifecycle,
    messages,
    paths,
    policy,
    pr_strategy,
    prompting,
    prs,
    root_branch,
    skills,
    templates,
    work_feedback,
    workspace,
    worktrees,
)
from .. import (
    log as atelier_log,
)
from ..io import confirm, die, prompt, say, select
from ..worker import changeset_state as worker_changeset_state
from ..worker import finalize as worker_finalize
from ..worker import finalize_pipeline as worker_finalize_pipeline
from ..worker import integration as worker_integration
from ..worker import prompts as worker_prompts
from ..worker import publish as worker_publish
from ..worker import queueing as worker_queueing
from ..worker import reconcile as worker_reconcile
from ..worker import review as worker_review
from ..worker import runtime as worker_runtime
from ..worker import selection as worker_selection
from ..worker import telemetry as worker_telemetry
from ..worker.models import (
    FinalizeResult,
    PublishSignalDiagnostics,
    ReconcileResult,
    StartupContractResult,
    WorkerRunSummary,
)
from ..worker.session import agent as worker_session_agent
from ..worker.session import runner as worker_session_runner
from ..worker.session import startup as worker_startup
from ..worker.session import worktree as worker_session_worktree
from .resolve import resolve_current_project_with_repo_root

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

# Keep these module references available for command-level patch points while
# business logic migrates into worker/session modules.
_LEGACY_PATCH_EXPORTS = (
    hooks,
    paths,
    policy,
    prompting,
    skills,
    templates,
    workspace,
)


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


def _log_warning(message: str) -> None:
    atelier_log.warning(f"[work] {message}")


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


def _is_eligible_status(status: str, *, allow_hooked: bool) -> bool:
    return worker_selection.is_eligible_status(status, allow_hooked=allow_hooked)


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


def _attempt_create_draft_pr(
    *,
    repo_slug: str,
    issue: dict[str, object],
    work_branch: str,
    beads_root: Path,
    repo_root: Path,
    git_path: str | None,
) -> tuple[bool, str]:
    base_branch = _changeset_base_branch(
        issue, beads_root=beads_root, repo_root=repo_root, git_path=git_path
    )
    if not base_branch:
        return False, "missing PR base branch metadata"
    title = str(issue.get("title") or "").strip() or work_branch
    body = _render_changeset_pr_body(issue)
    result = exec.try_run_command(
        [
            "gh",
            "pr",
            "create",
            "--repo",
            repo_slug,
            "--base",
            base_branch,
            "--head",
            work_branch,
            "--title",
            title,
            "--body",
            body,
            "--draft",
        ]
    )
    if result is None:
        return False, "missing required command: gh"
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        return False, detail or "gh pr create failed"
    detail = (result.stdout or "").strip()
    return True, detail or "created draft PR"


def _normalized_markdown_bullets(value: str) -> list[str]:
    return worker_publish.normalized_markdown_bullets(value)


def _render_changeset_pr_body(issue: dict[str, object]) -> str:
    description = issue.get("description")
    fields = beads.parse_description_fields(
        description if isinstance(description, str) else ""
    )
    return worker_publish.render_changeset_pr_body(issue, fields=fields)


def _set_changeset_review_pending_state(
    *,
    changeset_id: str,
    pr_payload: dict[str, object] | None,
    pushed: bool,
    fallback_pr_state: str | None,
    beads_root: Path,
    repo_root: Path,
) -> None:
    _mark_changeset_in_progress(
        changeset_id, beads_root=beads_root, repo_root=repo_root
    )
    if pr_payload:
        _update_changeset_review_from_pr(
            changeset_id,
            pr_payload=pr_payload,
            pushed=pushed,
            beads_root=beads_root,
            repo_root=repo_root,
        )
        return
    if fallback_pr_state:
        beads.update_changeset_review(
            changeset_id,
            changesets.ReviewMetadata(pr_state=fallback_pr_state),
            beads_root=beads_root,
            cwd=repo_root,
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
    decision = _changeset_pr_creation_decision(
        issue,
        repo_slug=repo_slug,
        repo_root=repo_root,
        git_path=git_path,
        branch_pr_strategy=branch_pr_strategy,
    )
    if not decision.allow_pr:
        _set_changeset_review_pending_state(
            changeset_id=changeset_id,
            pr_payload=None,
            pushed=True,
            fallback_pr_state="pushed",
            beads_root=beads_root,
            repo_root=repo_root,
        )
        return FinalizeResult(continue_running=True, reason="changeset_review_pending")

    failure_reason = "changeset_pr_create_failed"
    failure_subject = "NEEDS-DECISION: PR creation failed"
    create_detail = create_detail_prefix or ""
    if not repo_slug:
        failure_reason = "changeset_pr_missing_repo_slug"
        failure_subject = "NEEDS-DECISION: PR provider config missing"
        create_detail = "missing GitHub repo slug for PR creation"
    else:
        work_branch = _changeset_work_branch(issue)
        if not work_branch:
            create_detail = "missing changeset.work_branch metadata for PR creation"
        else:
            created, detail = _attempt_create_draft_pr(
                repo_slug=repo_slug,
                issue=issue,
                work_branch=work_branch,
                beads_root=beads_root,
                repo_root=repo_root,
                git_path=git_path,
            )
            create_detail = detail
            if created:
                pr_payload = _lookup_pr_payload(repo_slug, work_branch)
                lookup_error = None
                if pr_payload is None:
                    _payload_check, lookup_error = _lookup_pr_payload_diagnostic(
                        repo_slug, work_branch
                    )
                if pr_payload:
                    _set_changeset_review_pending_state(
                        changeset_id=changeset_id,
                        pr_payload=pr_payload,
                        pushed=True,
                        fallback_pr_state=None,
                        beads_root=beads_root,
                        repo_root=repo_root,
                    )
                else:
                    _set_changeset_review_pending_state(
                        changeset_id=changeset_id,
                        pr_payload=None,
                        pushed=True,
                        fallback_pr_state="draft-pr",
                        beads_root=beads_root,
                        repo_root=repo_root,
                    )
                if lookup_error:
                    create_detail = (
                        f"{create_detail}; unable to verify created PR: {lookup_error}"
                    )
                return FinalizeResult(
                    continue_running=True, reason="changeset_review_pending"
                )
            # Recover from duplicate/race failures by checking live PR state.
            pr_payload = _lookup_pr_payload(repo_slug, work_branch)
            lookup_error = None
            if pr_payload is None:
                _payload_check, lookup_error = _lookup_pr_payload_diagnostic(
                    repo_slug, work_branch
                )
            if pr_payload:
                _set_changeset_review_pending_state(
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
            if lookup_error:
                failure_reason = "changeset_pr_status_query_failed"
                failure_subject = "NEEDS-DECISION: PR status query failed"
                create_detail = (
                    f"{create_detail}; unable to verify existing PR: {lookup_error}"
                )
                _log_warning(
                    f"changeset={changeset_id} PR status lookup failed after create attempt: {lookup_error}"
                )

    _mark_changeset_in_progress(
        changeset_id, beads_root=beads_root, repo_root=repo_root
    )
    note = (
        "publish_pending: branch pushed but PR missing where "
        f"strategy allows PR ({decision.reason})"
    )
    if create_detail:
        note = f"{note}; PR creation attempt failed: {create_detail}"
    beads.run_bd_command(
        [
            "update",
            changeset_id,
            "--append-notes",
            note,
        ],
        beads_root=beads_root,
        cwd=repo_root,
        allow_failure=True,
    )
    body = (
        "Changeset branch is pushed but no PR exists where policy allows PR "
        f"creation (strategy={decision.strategy}, reason={decision.reason})."
    )
    if create_detail:
        body = f"{body}\nPR creation attempt failed: {create_detail}"
        say(f"PR creation failed for {changeset_id}: {create_detail}")
    if failure_reason == "changeset_pr_missing_repo_slug":
        body = (
            f"{body}\nAction: configure GitHub provider metadata so finalize can "
            "create PRs automatically."
        )
    else:
        body = (
            f"{body}\nAction: resolve `gh pr create` failure and rerun worker finalize."
        )
    _send_planner_notification(
        subject=f"{failure_subject} ({changeset_id})",
        body=body,
        agent_id=agent_id,
        thread_id=changeset_id,
        beads_root=beads_root,
        repo_root=repo_root,
        dry_run=False,
    )
    _log_warning(
        f"changeset={changeset_id} finalize stopped reason={failure_reason} strategy={decision.strategy} detail={create_detail or 'n/a'}"
    )
    return FinalizeResult(continue_running=False, reason=failure_reason)


def _changeset_parent_lifecycle_state(
    issue: dict[str, object],
    *,
    repo_slug: str | None,
    repo_root: Path,
    git_path: str | None,
) -> str | None:
    if not repo_slug:
        return None
    description = issue.get("description")
    fields = beads.parse_description_fields(
        description if isinstance(description, str) else ""
    )
    parent_branch = fields.get("changeset.parent_branch")
    root_branch = fields.get("changeset.root_branch")
    if not isinstance(parent_branch, str):
        return None
    normalized = parent_branch.strip()
    if not normalized or normalized.lower() == "null":
        return None
    if isinstance(root_branch, str):
        normalized_root = root_branch.strip()
        if normalized_root and normalized_root.lower() != "null":
            # Top-level changesets commonly use root==parent; treat as no-parent
            # for PR strategy gating to avoid self-deadlocking PR creation.
            if normalized_root == normalized:
                return None
    pushed = git.git_ref_exists(
        repo_root, f"refs/remotes/origin/{normalized}", git_path=git_path
    )
    payload = _lookup_pr_payload(repo_slug, normalized)
    review_requested = prs.has_review_requests(payload)
    return prs.lifecycle_state(
        payload, pushed=pushed, review_requested=review_requested
    )


def _changeset_pr_creation_decision(
    issue: dict[str, object],
    *,
    repo_slug: str | None,
    repo_root: Path,
    git_path: str | None,
    branch_pr_strategy: object,
) -> pr_strategy.PrStrategyDecision:
    parent_state = _changeset_parent_lifecycle_state(
        issue, repo_slug=repo_slug, repo_root=repo_root, git_path=git_path
    )
    return pr_strategy.pr_strategy_decision(
        branch_pr_strategy, parent_state=parent_state
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
    """Recover when an agent marks cs:merged before PR/integration signals exist."""
    if not branch_pr:
        return None
    work_branch = _changeset_work_branch(issue)
    if not work_branch:
        return None
    pushed = git.git_ref_exists(
        repo_root, f"refs/remotes/origin/{work_branch}", git_path=git_path
    )
    pr_payload = _lookup_pr_payload(repo_slug, work_branch)
    lookup_error = None
    if pr_payload is None:
        _payload_check, lookup_error = _lookup_pr_payload_diagnostic(
            repo_slug, work_branch
        )
    if lookup_error:
        _log_warning(
            f"changeset={changeset_id} premature-merged recovery failed PR lookup for branch={work_branch}: {lookup_error}"
        )
        return FinalizeResult(
            continue_running=False, reason="changeset_pr_status_query_failed"
        )
    review_requested = prs.has_review_requests(pr_payload)
    lifecycle = prs.lifecycle_state(
        pr_payload, pushed=pushed, review_requested=review_requested
    )

    if lifecycle in {"draft-pr", "pr-open", "in-review", "approved"}:
        _mark_changeset_in_progress(
            changeset_id, beads_root=beads_root, repo_root=repo_root
        )
        _update_changeset_review_from_pr(
            changeset_id,
            pr_payload=pr_payload,
            pushed=pushed,
            beads_root=beads_root,
            repo_root=repo_root,
        )
        return FinalizeResult(continue_running=True, reason="changeset_review_pending")
    if lifecycle == "merged":
        _integration_ok, integrated_sha = _changeset_integration_signal(
            issue, repo_slug=None, repo_root=repo_root, git_path=git_path
        )
        return _finalize_terminal_changeset(
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
        integration_ok, integrated_sha = _changeset_integration_signal(
            issue, repo_slug=repo_slug, repo_root=repo_root, git_path=git_path
        )
        return _finalize_terminal_changeset(
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
    if pushed and not pr_payload:
        _mark_changeset_in_progress(
            changeset_id, beads_root=beads_root, repo_root=repo_root
        )
        return _handle_pushed_without_pr(
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
        log_warning=_log_warning,
        log_debug=_log_debug,
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
    return worker_startup.run_startup_contract(
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
        log_debug=_log_debug,
        log_warning=_log_warning,
        dry_run_log=_dry_run_log,
        emit=say,
        run_bd_json=beads.run_bd_json,
        agent_family_id=worker_selection.agent_family_id,
        is_agent_session_active=_is_agent_session_active,
        die_fn=die,
    )


def _run_worker_once(
    args: object, *, mode: str, dry_run: bool, session_key: str
) -> WorkerRunSummary:
    """Start a single worker session by selecting an epic and changeset."""
    timings: list[tuple[str, float]] = []
    trace = _trace_enabled()
    prs.clear_runtime_cache()

    def finish(summary: WorkerRunSummary) -> WorkerRunSummary:
        _report_timings(timings, trace=trace)
        return summary

    project_root, project_config, _enlistment, repo_root = (
        resolve_current_project_with_repo_root()
    )
    project_data_dir = config.resolve_project_data_dir(project_root, project_config)
    beads_root = config.resolve_beads_root(project_data_dir, repo_root)
    git_path = config.resolve_git_path(project_config)
    if dry_run:
        agent = agent_home.preview_agent_home(
            project_data_dir, project_config, role="worker", session_key=session_key
        )
    else:
        agent = agent_home.resolve_agent_home(
            project_data_dir, project_config, role="worker", session_key=session_key
        )

    with agents.scoped_agent_env(agent.agent_id):
        say("Worker session")
        agent_bead_id: str | None = None
        finish_step = _step("Prime beads", timings=timings, trace=trace)
        if dry_run:
            _dry_run_log("Would run: bd prime")
        else:
            beads.run_bd_command(["prime"], beads_root=beads_root, cwd=repo_root)
        finish_step()
        finish_step = _step("Ensure worker agent bead", timings=timings, trace=trace)
        if dry_run:
            agent_bead = beads.find_agent_bead(
                agent.agent_id, beads_root=beads_root, cwd=repo_root
            )
            if agent_bead:
                agent_bead_id = (
                    str(agent_bead.get("id")) if agent_bead.get("id") else None
                )
            if not agent_bead_id:
                _dry_run_log(
                    f"Would create agent bead for {agent.agent_id!r} (worker)."
                )
            _dry_run_log("Would sync agent home policy.")
        else:
            agent_bead = beads.ensure_agent_bead(
                agent.agent_id, beads_root=beads_root, cwd=repo_root, role="worker"
            )
            agent_bead_id = agent_bead.get("id")
        finish_step()

        epic_id = getattr(args, "epic_id", None)
        queue_only = bool(getattr(args, "queue", False))
        assume_yes = bool(getattr(args, "yes", False))
        should_reconcile = bool(getattr(args, "reconcile", False))

        if not dry_run:
            if not isinstance(agent_bead_id, str) or not agent_bead_id:
                die("failed to resolve agent bead id")

        if should_reconcile:
            finish_step = _step(
                "Reconcile blocked changesets", timings=timings, trace=trace
            )
            reconcile_result = reconcile_blocked_merged_changesets(
                agent_id=agent.agent_id,
                agent_bead_id=agent_bead_id,
                project_config=project_config,
                project_data_dir=project_data_dir,
                beads_root=beads_root,
                repo_root=repo_root,
                git_path=git_path,
                dry_run=dry_run,
                log=say,
            )
            finish_step(
                extra=(
                    f"scanned={reconcile_result.scanned}, "
                    f"actionable={reconcile_result.actionable}, "
                    f"reconciled={reconcile_result.reconciled}, "
                    f"failed={reconcile_result.failed}"
                )
            )

        repo_slug = prs.github_repo_slug(
            project_config.project.origin or project_config.project.repo_url
        )
        finish_step = _step("Select epic", timings=timings, trace=trace)
        startup_result = _run_startup_contract(
            agent_id=agent.agent_id,
            agent_bead_id=agent_bead_id,
            beads_root=beads_root,
            repo_root=repo_root,
            mode=mode,
            explicit_epic_id=epic_id,
            queue_only=queue_only,
            dry_run=dry_run,
            assume_yes=assume_yes,
            repo_slug=repo_slug,
            branch_pr=project_config.branch.pr,
            branch_pr_strategy=project_config.branch.pr_strategy,
            git_path=git_path,
        )
        summary_note = startup_result.reason
        if startup_result.epic_id:
            summary_note = f"{summary_note} ({startup_result.epic_id})"
        finish_step(extra=summary_note)
        if startup_result.should_exit:
            if dry_run:
                _dry_run_log("Startup contract would exit without starting a worker.")
            return finish(
                WorkerRunSummary(
                    started=False,
                    reason=startup_result.reason,
                    epic_id=startup_result.epic_id,
                )
            )
        if not startup_result.epic_id:
            if dry_run:
                _dry_run_log("Startup contract did not select an epic.")
                return finish(
                    WorkerRunSummary(
                        started=False, reason="no_epic_selected", epic_id=None
                    )
                )
            die("startup contract did not select an epic")
        selected_epic = startup_result.epic_id

        finish_step = _step("Claim epic", timings=timings, trace=trace)
        if dry_run:
            _dry_run_log(f"Selected epic: {selected_epic}")
            issues = beads.run_bd_json(
                ["show", selected_epic], beads_root=beads_root, cwd=repo_root
            )
            if not issues:
                _dry_run_log(f"Epic {selected_epic!r} not found.")
                finish_step(extra="epic not found")
                return finish(
                    WorkerRunSummary(
                        started=False, reason="epic_not_found", epic_id=selected_epic
                    )
                )
            epic_issue = issues[0]
            _dry_run_log(
                f"Would claim epic {selected_epic!r} for agent {agent.agent_id!r}."
            )
            if startup_result.reassign_from:
                _dry_run_log(
                    "Would reclaim stale epic assignment from "
                    f"{startup_result.reassign_from!r}."
                )
        else:
            say(f"Selected epic: {selected_epic}")
            epic_issue = beads.claim_epic(
                selected_epic,
                agent.agent_id,
                beads_root=beads_root,
                cwd=repo_root,
                allow_takeover_from=startup_result.reassign_from,
            )
            if startup_result.reassign_from:
                previous_agent = beads.find_agent_bead(
                    startup_result.reassign_from,
                    beads_root=beads_root,
                    cwd=repo_root,
                )
                previous_agent_id = (
                    str(previous_agent.get("id"))
                    if previous_agent and previous_agent.get("id")
                    else ""
                )
                if previous_agent_id:
                    beads.clear_agent_hook(
                        previous_agent_id, beads_root=beads_root, cwd=repo_root
                    )
        finish_step()
        finish_step = _step("Resolve root branch", timings=timings, trace=trace)
        root_branch_value = beads.extract_workspace_root_branch(epic_issue)
        if not root_branch_value:
            root_branch_value = _extract_changeset_root_branch(epic_issue)
        suggested_root_branch = None
        if not root_branch_value:
            suggested_root_branch = branching.suggest_root_branch(
                str(epic_issue.get("title") or selected_epic),
                project_config.branch.prefix,
            )
            if dry_run:
                _dry_run_log(
                    "Root branch missing; would prompt for root branch selection."
                )
                if suggested_root_branch:
                    _dry_run_log(f"Suggested root branch: {suggested_root_branch!r}.")
                root_branch_value = suggested_root_branch
            else:
                root_branch_value = root_branch.prompt_root_branch(
                    title=str(epic_issue.get("title") or selected_epic),
                    branch_prefix=project_config.branch.prefix,
                    beads_root=beads_root,
                    repo_root=repo_root,
                    assume_yes=assume_yes,
                )
                beads.update_workspace_root_branch(
                    selected_epic,
                    root_branch_value,
                    beads_root=beads_root,
                    cwd=repo_root,
                )
        finish_step(extra=root_branch_value or "unset")
        finish_step = _step("Set parent branch + hook", timings=timings, trace=trace)
        parent_branch_value = _extract_workspace_parent_branch(epic_issue)
        default_branch = git.git_default_branch(repo_root, git_path=git_path)
        if not parent_branch_value:
            parent_branch_value = default_branch or root_branch_value
        allow_parent_override = False
        if (
            parent_branch_value
            and root_branch_value
            and parent_branch_value == root_branch_value
            and not project_config.branch.pr
            and default_branch
            and default_branch != root_branch_value
        ):
            parent_branch_value = default_branch
            allow_parent_override = True
        if dry_run:
            _dry_run_log(
                f"Would set workspace parent branch to {parent_branch_value!r}."
            )
            _dry_run_log("Would set agent hook to selected epic.")
        else:
            beads.update_workspace_parent_branch(
                selected_epic,
                parent_branch_value,
                beads_root=beads_root,
                cwd=repo_root,
                allow_override=allow_parent_override,
            )
            beads.set_agent_hook(
                agent_bead_id, selected_epic, beads_root=beads_root, cwd=repo_root
            )
        finish_step()
        finish_step = _step("Validate changeset labels", timings=timings, trace=trace)
        invalid_changesets = _find_invalid_changeset_labels(
            selected_epic, beads_root=beads_root, repo_root=repo_root
        )
        if invalid_changesets:
            detail = _send_invalid_changeset_labels_notification(
                epic_id=selected_epic,
                invalid_changesets=invalid_changesets,
                agent_id=agent.agent_id,
                beads_root=beads_root,
                repo_root=repo_root,
                dry_run=dry_run,
            )
            finish_step(extra=f"invalid labels: {detail}")
            if dry_run:
                _dry_run_log("Would release epic assignment and clear agent hook.")
            else:
                _release_epic_assignment(
                    selected_epic, beads_root=beads_root, repo_root=repo_root
                )
                beads.clear_agent_hook(
                    agent_bead_id, beads_root=beads_root, cwd=repo_root
                )
            return finish(
                WorkerRunSummary(
                    started=False,
                    reason="changeset_label_violation",
                    epic_id=selected_epic,
                )
            )
        finish_step()
        finish_step = _step("Select changeset", timings=timings, trace=trace)
        selected = worker_session_runner.select_changeset(
            selected_epic=selected_epic,
            startup_changeset_id=startup_result.changeset_id,
            beads_root=beads_root,
            repo_root=repo_root,
            repo_slug=repo_slug,
            branch_pr=project_config.branch.pr,
            branch_pr_strategy=project_config.branch.pr_strategy,
            git_path=git_path,
            run_bd_json=beads.run_bd_json,
            resolve_epic_id_for_changeset=_resolve_epic_id_for_changeset,
            next_changeset=_next_changeset,
        )
        changeset = selected.issue
        selected_changeset_override = selected.selected_override
        if changeset is None:
            _send_no_ready_changesets(
                epic_id=selected_epic,
                agent_id=agent.agent_id,
                beads_root=beads_root,
                repo_root=repo_root,
                dry_run=dry_run,
            )
            finish_step(extra="no ready changesets")
            if dry_run:
                _dry_run_log("Would release epic assignment and clear agent hook.")
                return finish(
                    WorkerRunSummary(
                        started=False,
                        reason="no_ready_changesets",
                        epic_id=selected_epic,
                    )
                )
            _release_epic_assignment(
                selected_epic, beads_root=beads_root, repo_root=repo_root
            )
            beads.clear_agent_hook(agent_bead_id, beads_root=beads_root, cwd=repo_root)
            return finish(
                WorkerRunSummary(
                    started=False, reason="no_ready_changesets", epic_id=selected_epic
                )
            )
        changeset_extra = str(changeset.get("id") or "unknown")
        if (
            selected_changeset_override
            and changeset_extra == selected_changeset_override
        ):
            changeset_extra = f"{changeset_extra} (review_feedback)"
        finish_step(extra=changeset_extra)
        changeset_id = changeset.get("id") or ""
        changeset_title = changeset.get("title") or ""
        changeset_parent_branch = root_branch_value
        if changeset_parent_branch and changeset_id:
            if dry_run:
                changeset_parent_branch = _changeset_parent_branch(
                    changeset, root_branch=changeset_parent_branch
                )
            else:
                selected_changeset = beads.run_bd_json(
                    ["show", str(changeset_id)], beads_root=beads_root, cwd=repo_root
                )
                if selected_changeset:
                    changeset_parent_branch = _changeset_parent_branch(
                        selected_changeset[0], root_branch=changeset_parent_branch
                    )
        if dry_run:
            _dry_run_log(f"Next changeset: {changeset_id} {changeset_title}")
        else:
            say(f"Next changeset: {changeset_id} {changeset_title}")
        finish_step = _step("Prepare worktrees", timings=timings, trace=trace)
        worktree_prep = worker_session_worktree.prepare_worktrees(
            dry_run=dry_run,
            project_data_dir=project_data_dir,
            repo_root=repo_root,
            beads_root=beads_root,
            selected_epic=selected_epic,
            changeset_id=str(changeset_id),
            root_branch_value=root_branch_value or "",
            changeset_parent_branch=changeset_parent_branch or "",
            git_path=git_path,
            emit=say,
            dry_run_log=_dry_run_log,
        )
        changeset_worktree_path = worktree_prep.changeset_worktree_path
        finish_step()
        finish_step = _step("Mark changeset in progress", timings=timings, trace=trace)
        if changeset_id:
            if dry_run:
                _dry_run_log(f"Would mark changeset {changeset_id} in progress.")
            else:
                _mark_changeset_in_progress(
                    changeset_id, beads_root=beads_root, repo_root=repo_root
                )
        finish_step()

        finish_step = _step("Prepare agent session", timings=timings, trace=trace)
        try:
            agent_prep = worker_session_agent.prepare_agent_session(
                project_config=project_config,
                project_data_dir=project_data_dir,
                repo_root=repo_root,
                beads_root=beads_root,
                agent=agent,
                changeset_worktree_path=changeset_worktree_path,
                selected_epic=selected_epic,
                changeset_id=str(changeset_id),
                root_branch_value=root_branch_value or "",
                enlistment_path=_enlistment,
                yes=bool(getattr(args, "yes", False)),
                dry_run=dry_run,
                strip_flag_with_value=_strip_flag_with_value,
                confirm_update=lambda message: confirm(message, default=False),
                dry_run_log=_dry_run_log,
                emit=say,
            )
        except RuntimeError as exc:
            die(str(exc))
        agent_spec = agent_prep.agent_spec
        agent_options = agent_prep.agent_options
        project_enlistment = agent_prep.project_enlistment
        workspace_branch = agent_prep.workspace_branch
        env = agent_prep.env
        finish_step()
        opening_prompt = ""
        review_feedback = startup_result.reason == "review_feedback"
        feedback_before: ReviewFeedbackSnapshot | None = None
        if agent_spec.name == "codex":
            review_pr_url = _changeset_pr_url(changeset) if review_feedback else None
            if review_feedback and not review_pr_url and repo_slug:
                feedback_branch = _changeset_work_branch(changeset)
                if feedback_branch:
                    pr_payload = _lookup_pr_payload(repo_slug, feedback_branch)
                    if pr_payload:
                        payload_url = pr_payload.get("url")
                        if isinstance(payload_url, str) and payload_url.strip():
                            review_pr_url = payload_url.strip()
            opening_prompt = _worker_opening_prompt(
                project_enlistment=project_enlistment,
                workspace_branch=workspace_branch,
                epic_id=selected_epic,
                changeset_id=str(changeset_id),
                changeset_title=str(changeset_title),
                review_feedback=review_feedback,
                review_pr_url=review_pr_url,
            )
        if review_feedback:
            feedback_before = _capture_review_feedback_snapshot(
                issue=changeset,
                repo_slug=repo_slug,
                repo_root=repo_root,
                git_path=git_path,
            )
        finish_step = _step("Install agent hooks", timings=timings, trace=trace)
        worker_session_agent.install_agent_hooks(
            dry_run=dry_run,
            agent=agent,
            agent_spec=agent_spec,
            env=env,
            dry_run_log=_dry_run_log,
        )
        finish_step()
        finish_step = _step("Start agent session", timings=timings, trace=trace)
        if dry_run:
            _dry_run_log(f"Would start {agent_spec.display_name} session.")
        session_result = worker_session_agent.start_agent_session(
            dry_run=dry_run,
            agent=agent,
            agent_spec=agent_spec,
            agent_options=agent_options,
            opening_prompt=opening_prompt,
            env=env,
            with_codex_exec=_with_codex_exec,
            strip_flag_with_value=_strip_flag_with_value,
            ensure_exec_subcommand_flag=_ensure_exec_subcommand_flag,
            mark_changeset_blocked=lambda reason: _mark_changeset_blocked(
                changeset_id,
                beads_root=beads_root,
                repo_root=repo_root,
                reason=reason,
            ),
            die_fn=die,
            dry_run_log=_dry_run_log,
            emit=say,
        )
        if session_result is None:
            finish_step(extra="dry run")
            return finish(
                WorkerRunSummary(
                    started=False,
                    reason="dry_run",
                    epic_id=selected_epic,
                    changeset_id=str(changeset_id) if changeset_id else None,
                )
            )
        started_at = session_result.started_at
        finish_step(extra=f"exit={session_result.returncode}")
        finish_step = _step("Finalize changeset", timings=timings, trace=trace)
        finalize_result = _finalize_changeset(
            changeset_id=changeset_id,
            epic_id=selected_epic,
            agent_id=agent.agent_id,
            agent_bead_id=agent_bead_id,
            started_at=started_at,
            repo_slug=repo_slug,
            beads_root=beads_root,
            repo_root=repo_root,
            branch_pr=project_config.branch.pr,
            branch_pr_strategy=project_config.branch.pr_strategy,
            branch_history=project_config.branch.history,
            branch_squash_message=project_config.branch.squash_message,
            project_data_dir=project_data_dir,
            squash_message_agent_spec=agent_spec,
            squash_message_agent_options=agent_options,
            squash_message_agent_home=agent.path,
            squash_message_agent_env=env,
            git_path=git_path,
        )
        if review_feedback and finalize_result.continue_running:
            feedback_after = _capture_review_feedback_snapshot(
                issue=changeset,
                repo_slug=repo_slug,
                repo_root=repo_root,
                git_path=git_path,
            )
            if feedback_before is not None and not _review_feedback_progressed(
                feedback_before, feedback_after
            ):
                _mark_changeset_in_progress(
                    changeset_id, beads_root=beads_root, repo_root=repo_root
                )
                _send_planner_notification(
                    subject=f"NEEDS-DECISION: Review feedback unchanged ({changeset_id})",
                    body=(
                        "Review-feedback run completed without detectable feedback "
                        "progress.\n"
                        f"Before: feedback_at={feedback_before.feedback_at or 'none'}, "
                        "unresolved_threads="
                        f"{feedback_before.unresolved_threads if feedback_before.unresolved_threads is not None else 'unknown'}, "
                        f"branch_head={feedback_before.branch_head or 'none'}\n"
                        f"After: feedback_at={feedback_after.feedback_at or 'none'}, "
                        "unresolved_threads="
                        f"{feedback_after.unresolved_threads if feedback_after.unresolved_threads is not None else 'unknown'}, "
                        f"branch_head={feedback_after.branch_head or 'none'}\n"
                        "Action: address feedback inline (reply + resolve thread) or "
                        "push changes that respond to review comments, then rerun worker."
                    ),
                    agent_id=agent.agent_id,
                    thread_id=changeset_id,
                    beads_root=beads_root,
                    repo_root=repo_root,
                    dry_run=False,
                )
                finish_step(extra="changeset_feedback_not_addressed")
                return finish(
                    WorkerRunSummary(
                        started=False,
                        reason="changeset_feedback_not_addressed",
                        epic_id=selected_epic,
                        changeset_id=str(changeset_id) if changeset_id else None,
                    )
                )
            _persist_review_feedback_cursor(
                changeset_id=changeset_id,
                issue=changeset,
                repo_slug=repo_slug,
                beads_root=beads_root,
                repo_root=repo_root,
            )
        finish_step(extra=finalize_result.reason)
        if not finalize_result.continue_running:
            return finish(
                WorkerRunSummary(
                    started=False,
                    reason=finalize_result.reason,
                    epic_id=selected_epic,
                    changeset_id=str(changeset_id) if changeset_id else None,
                )
            )
        return finish(
            WorkerRunSummary(
                started=True,
                reason="agent_session_complete",
                epic_id=selected_epic,
                changeset_id=str(changeset_id) if changeset_id else None,
            )
        )


def start_worker(args: object) -> None:
    """Start worker sessions based on the configured run mode."""
    mode = _normalize_mode(getattr(args, "mode", None))
    run_mode = _normalize_run_mode(getattr(args, "run_mode", None))
    dry_run = bool(getattr(args, "dry_run", False))
    session_key = agent_home.generate_session_key()
    cleanup_agent: agent_home.AgentHome | None = None
    cleanup_project_dir: Path | None = None
    if not dry_run:
        (
            cleanup_project_root,
            cleanup_project_config,
            _cleanup_enlistment,
            _cleanup_repo_root,
        ) = resolve_current_project_with_repo_root()
        cleanup_project_dir = config.resolve_project_data_dir(
            cleanup_project_root, cleanup_project_config
        )
        cleanup_agent = agent_home.preview_agent_home(
            cleanup_project_dir,
            cleanup_project_config,
            role="worker",
            session_key=session_key,
        )
    try:
        worker_runtime.run_worker_sessions(
            args=args,
            mode=mode,
            run_mode=run_mode,
            dry_run=dry_run,
            session_key=session_key,
            run_worker_once=_run_worker_once,
            report_worker_summary=lambda summary, is_dry_run: _report_worker_summary(
                summary, dry_run=is_dry_run
            ),
            watch_interval_seconds=_watch_interval_seconds,
            dry_run_log=_dry_run_log,
            emit=say,
            sleep_fn=time.sleep,
        )
    finally:
        if cleanup_agent is not None and cleanup_project_dir is not None:
            agent_home.cleanup_agent_home(
                cleanup_agent, project_dir=cleanup_project_dir
            )

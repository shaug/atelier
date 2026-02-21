"""Helper logic for the `atelier work` command.

This module contains worker business logic used by the thin command controller.
"""

from __future__ import annotations

import datetime as dt
import os
from collections.abc import Callable
from pathlib import Path

from .. import (
    agent_home,
    agents,
    beads,
    changeset_fields,
    changesets,
    config,
    git,
    lifecycle,
    pr_strategy,
    prs,
    work_feedback,
)
from .. import (
    log as atelier_log,
)
from .. import (
    root_branch as root_branch_module,
)
from ..io import die, prompt, say, select
from ..worker import finalization_service as worker_finalization_service
from ..worker import finalize as worker_finalize
from ..worker import finalize_pipeline as worker_finalize_pipeline
from ..worker import integration_service as worker_integration_service
from ..worker import prompts as worker_prompts
from ..worker import publish as worker_publish
from ..worker import queueing as worker_queueing
from ..worker import reconcile_service as worker_reconcile_service
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
from ..worker.models_boundary import parse_issue_boundary
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
    boundary = parse_issue_boundary(issue, source="_issue_parent_id")
    return boundary.parent_id


def _issue_dependency_ids(issue: dict[str, object]) -> tuple[str, ...]:
    boundary = parse_issue_boundary(issue, source="_issue_dependency_ids")
    return boundary.dependency_ids


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
    boundary = parse_issue_boundary(issue, source="_issue_labels")
    return set(boundary.labels)


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


class _NextChangesetService(worker_startup.NextChangesetService):
    """Concrete next-changeset service implementation for worker startup."""

    def __init__(self, *, beads_root: Path, repo_root: Path) -> None:
        self._beads_root = beads_root
        self._repo_root = repo_root

    def show_issue(self, issue_id: str) -> dict[str, object] | None:
        issues = beads.run_bd_json(
            ["show", issue_id], beads_root=self._beads_root, cwd=self._repo_root
        )
        return issues[0] if issues else None

    def ready_changesets(self, *, epic_id: str) -> list[dict[str, object]]:
        return beads.run_bd_json(
            ["ready", "--parent", epic_id, "--label", "at:changeset"],
            beads_root=self._beads_root,
            cwd=self._repo_root,
        )

    def issue_labels(self, issue: dict[str, object]) -> set[str]:
        return _issue_labels(issue)

    def is_changeset_ready(self, issue: dict[str, object]) -> bool:
        return _is_changeset_ready(issue)

    def changeset_waiting_on_review_or_signals(
        self,
        issue: dict[str, object],
        *,
        repo_slug: str | None,
        branch_pr: bool,
        branch_pr_strategy: object,
        git_path: str | None,
    ) -> bool:
        return _changeset_waiting_on_review_or_signals(
            issue,
            repo_slug=repo_slug,
            repo_root=self._repo_root,
            branch_pr=branch_pr,
            branch_pr_strategy=branch_pr_strategy,
            git_path=git_path,
        )

    def is_changeset_recovery_candidate(
        self,
        issue: dict[str, object],
        *,
        repo_slug: str | None,
        branch_pr: bool,
        git_path: str | None,
    ) -> bool:
        return _is_changeset_recovery_candidate(
            issue,
            repo_slug=repo_slug,
            repo_root=self._repo_root,
            branch_pr=branch_pr,
            git_path=git_path,
        )

    def has_open_descendant_changesets(self, changeset_id: str) -> bool:
        return _has_open_descendant_changesets(
            changeset_id, beads_root=self._beads_root, repo_root=self._repo_root
        )

    def list_descendant_changesets(
        self,
        parent_id: str,
        *,
        include_closed: bool,
    ) -> list[dict[str, object]]:
        return beads.list_descendant_changesets(
            parent_id,
            beads_root=self._beads_root,
            cwd=self._repo_root,
            include_closed=include_closed,
        )

    def is_changeset_in_progress(self, issue: dict[str, object]) -> bool:
        return _is_changeset_in_progress(issue)


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
    context = worker_startup.NextChangesetContext(
        epic_id=epic_id,
        repo_slug=repo_slug,
        branch_pr=branch_pr,
        branch_pr_strategy=branch_pr_strategy,
        git_path=git_path,
    )
    service = _NextChangesetService(beads_root=beads_root, repo_root=repo_root)
    return worker_startup.next_changeset_service(context=context, service=service)


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
    return worker_finalization_service.list_child_issues(
        parent_id,
        beads_root=beads_root,
        repo_root=repo_root,
        include_closed=include_closed,
    )


def _find_invalid_changeset_labels(
    root_id: str, *, beads_root: Path, repo_root: Path
) -> list[str]:
    return worker_finalization_service.find_invalid_changeset_labels(
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
    worker_finalization_service.mark_changeset_in_progress(
        changeset_id,
        beads_root=beads_root,
        repo_root=repo_root,
    )


def _mark_changeset_closed(
    changeset_id: str, *, beads_root: Path, repo_root: Path
) -> None:
    worker_finalization_service.mark_changeset_closed(
        changeset_id,
        beads_root=beads_root,
        repo_root=repo_root,
    )


def _mark_changeset_merged(
    changeset_id: str, *, beads_root: Path, repo_root: Path
) -> None:
    worker_finalization_service.mark_changeset_merged(
        changeset_id,
        beads_root=beads_root,
        repo_root=repo_root,
    )


def _mark_changeset_abandoned(
    changeset_id: str, *, beads_root: Path, repo_root: Path
) -> None:
    worker_finalization_service.mark_changeset_abandoned(
        changeset_id,
        beads_root=beads_root,
        repo_root=repo_root,
    )


def _mark_changeset_blocked(
    changeset_id: str, *, beads_root: Path, repo_root: Path, reason: str
) -> None:
    worker_finalization_service.mark_changeset_blocked(
        changeset_id,
        beads_root=beads_root,
        repo_root=repo_root,
        reason=reason,
    )


def _mark_changeset_children_in_progress(
    changeset_id: str, *, beads_root: Path, repo_root: Path
) -> None:
    worker_finalization_service.mark_changeset_children_in_progress(
        changeset_id,
        beads_root=beads_root,
        repo_root=repo_root,
    )


def _close_completed_container_changesets(
    epic_id: str, *, beads_root: Path, repo_root: Path
) -> list[str]:
    return worker_finalization_service.close_completed_container_changesets(
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
    return worker_finalization_service.promote_planned_descendant_changesets(
        changeset_id, beads_root=beads_root, repo_root=repo_root
    )


def _has_blocking_messages(
    *,
    thread_ids: set[str],
    started_at: dt.datetime,
    beads_root: Path,
    repo_root: Path,
) -> bool:
    return worker_finalization_service.has_blocking_messages(
        thread_ids=thread_ids,
        started_at=started_at,
        beads_root=beads_root,
        repo_root=repo_root,
        parse_issue_time=_parse_issue_time,
    )


def _branch_ref_for_lookup(
    repo_root: Path, branch: str, *, git_path: str | None = None
) -> str | None:
    return worker_integration_service.branch_ref_for_lookup(
        repo_root, branch, git_path=git_path
    )


def _epic_root_integrated_into_parent(
    epic_issue: dict[str, object],
    *,
    repo_root: Path,
    git_path: str | None = None,
) -> bool:
    return worker_integration_service.epic_root_integrated_into_parent(
        epic_issue,
        repo_root=repo_root,
        git_path=git_path,
    )


def _changeset_integration_signal(
    issue: dict[str, object],
    *,
    repo_slug: str | None,
    repo_root: Path,
    git_path: str | None = None,
) -> tuple[bool, str | None]:
    return worker_integration_service.changeset_integration_signal(
        issue,
        repo_slug=repo_slug,
        repo_root=repo_root,
        lookup_pr_payload=_lookup_pr_payload,
        git_path=git_path,
    )


def _resolve_epic_id_for_changeset(
    issue: dict[str, object], *, beads_root: Path, repo_root: Path
) -> str | None:
    return worker_reconcile_service.resolve_epic_id_for_changeset(
        issue,
        beads_root=beads_root,
        repo_root=repo_root,
        issue_labels=_issue_labels,
        issue_parent_id=_issue_parent_id,
    )


def list_reconcile_epic_candidates(
    *,
    project_config: config.ProjectConfig,
    beads_root: Path,
    repo_root: Path,
    git_path: str | None = None,
) -> dict[str, list[str]]:
    return worker_reconcile_service.list_reconcile_epic_candidates(
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
    return worker_reconcile_service.reconcile_blocked_merged_changesets(
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
        with_codex_exec=_with_codex_exec,
        strip_flag_with_value=_strip_flag_with_value,
        ensure_exec_subcommand_flag=_ensure_exec_subcommand_flag,
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
        with_codex_exec=_with_codex_exec,
        strip_flag_with_value=_strip_flag_with_value,
        ensure_exec_subcommand_flag=_ensure_exec_subcommand_flag,
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


class _StartupContractService(worker_startup.StartupContractService):
    """Concrete startup-contract service implementation for worker runtime."""

    def __init__(self, *, beads_root: Path, repo_root: Path) -> None:
        self._beads_root = beads_root
        self._repo_root = repo_root

    def handle_queue_before_claim(
        self,
        agent_id: str,
        *,
        queue_name: str,
        force_prompt: bool = False,
        dry_run: bool = False,
        assume_yes: bool = False,
    ) -> bool:
        return _handle_queue_before_claim(
            agent_id,
            beads_root=self._beads_root,
            repo_root=self._repo_root,
            queue_name=queue_name,
            force_prompt=force_prompt,
            dry_run=dry_run,
            assume_yes=assume_yes,
        )

    def list_epics(self) -> list[dict[str, object]]:
        return beads.run_bd_json(
            ["list", "--label", "at:epic"],
            beads_root=self._beads_root,
            cwd=self._repo_root,
        )

    def next_changeset(
        self,
        *,
        epic_id: str,
        repo_slug: str | None,
        branch_pr: bool,
        branch_pr_strategy: object,
        git_path: str | None,
    ) -> dict[str, object] | None:
        return _next_changeset(
            epic_id=epic_id,
            beads_root=self._beads_root,
            repo_root=self._repo_root,
            repo_slug=repo_slug,
            branch_pr=branch_pr,
            branch_pr_strategy=branch_pr_strategy,
            git_path=git_path,
        )

    def resolve_hooked_epic(self, agent_bead_id: str, agent_id: str) -> str | None:
        return _resolve_hooked_epic(
            agent_bead_id,
            agent_id,
            beads_root=self._beads_root,
            repo_root=self._repo_root,
        )

    def stale_family_assigned_epics(
        self, issues: list[dict[str, object]], *, agent_id: str
    ) -> list[dict[str, object]]:
        return worker_selection.stale_family_assigned_epics(
            issues,
            agent_id=agent_id,
            is_session_active=agent_home.is_session_agent_active,
        )

    def select_review_feedback_changeset(
        self, *, epic_id: str, repo_slug: str | None
    ) -> ReviewFeedbackSelection | None:
        return _select_review_feedback_changeset(
            epic_id=epic_id,
            repo_slug=repo_slug,
            beads_root=self._beads_root,
            repo_root=self._repo_root,
        )

    def select_global_review_feedback_changeset(
        self, *, repo_slug: str | None
    ) -> ReviewFeedbackSelection | None:
        return _select_global_review_feedback_changeset(
            repo_slug=repo_slug,
            beads_root=self._beads_root,
            repo_root=self._repo_root,
        )

    def check_inbox_before_claim(self, agent_id: str) -> bool:
        return _check_inbox_before_claim(
            agent_id, beads_root=self._beads_root, repo_root=self._repo_root
        )

    def ready_changesets_global(self) -> list[dict[str, object]]:
        return beads.run_bd_json(
            ["ready", "--label", "at:changeset"],
            beads_root=self._beads_root,
            cwd=self._repo_root,
        )

    def select_epic_prompt(
        self,
        issues: list[dict[str, object]],
        *,
        agent_id: str,
        is_actionable: Callable[[str], bool],
        assume_yes: bool,
    ) -> str | None:
        return worker_selection.select_epic_prompt(
            issues,
            agent_id=agent_id,
            is_actionable=is_actionable,
            extract_root_branch=beads.extract_workspace_root_branch,
            select_fn=lambda title, options: select(title, options),
            assume_yes=assume_yes,
        )

    def send_needs_decision(
        self,
        *,
        agent_id: str,
        mode: str,
        issues: list[dict[str, object]],
        dry_run: bool,
    ) -> None:
        worker_queueing.send_needs_decision(
            agent_id=agent_id,
            mode=mode,
            issues=issues,
            beads_root=self._beads_root,
            repo_root=self._repo_root,
            dry_run=dry_run,
            filter_epics=_filter_epics,
            dry_run_log=_dry_run_log,
        )

    def dry_run_log(self, message: str) -> None:
        _dry_run_log(message)

    def emit(self, message: str) -> None:
        say(message)

    def die(self, message: str) -> None:
        die(message)


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
    service = _StartupContractService(beads_root=beads_root, repo_root=repo_root)
    return worker_startup.run_startup_contract_service(context=context, service=service)

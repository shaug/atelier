"""Worker session runner helpers shared by command orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ... import changeset_fields
from ...pr_strategy import PrStrategy
from ..context import ChangesetSelectionContext, WorkerRunContext
from ..models import StartupContractResult, WorkerRunSummary
from ..models_boundary import parse_issue_boundary
from ..ports import (
    BeadsService,
    WorkerControlService,
    WorkerLifecycleService,
    WorkerRuntimeDependencies,
)
from .startup import StartupContractContext
from .worktree import WorktreePreparationContext

_WORKER_QUEUE_NAME = "worker"


def _claim_conflict_assignee(
    *,
    beads: BeadsService,
    epic_id: str,
    agent_id: str,
    allow_takeover_from: str | None,
    beads_root: Path,
    repo_root: Path,
) -> str | None:
    """Return conflicting assignee when an epic claim failed due assignment."""
    issues = beads.run_bd_json(["show", epic_id], beads_root=beads_root, cwd=repo_root)
    if not issues:
        return None
    assignee = issues[0].get("assignee")
    if not isinstance(assignee, str) or not assignee:
        return None
    if assignee == agent_id:
        return None
    if allow_takeover_from and assignee == allow_takeover_from:
        return None
    return assignee


def _abort_startup_read_failure(
    *,
    beads: BeadsService,
    lifecycle: WorkerLifecycleService,
    control: WorkerControlService,
    selected_epic: str,
    agent_id: str,
    agent_bead_id: str,
    beads_root: Path,
    repo_root: Path,
    dry_run: bool,
    stage: str,
    verification_issue_id: str | None,
    reason: str,
) -> WorkerRunSummary:
    """Clean up startup assignment/hook state after Beads read failures."""
    if dry_run:
        control.dry_run_log(
            "Would release epic assignment and clear agent hook after startup Beads read failure."
        )
        return WorkerRunSummary(started=False, reason=reason, epic_id=selected_epic)
    verification_target = verification_issue_id or selected_epic
    try:
        lifecycle.send_planner_notification(
            subject=f"NEEDS-DECISION: Beads read failure during startup ({selected_epic})",
            body=(
                "Worker startup could not continue because Beads issue reads failed.\n"
                f"Epic: {selected_epic}\n"
                f"Stage: {stage}\n"
                "Diagnostics: this usually indicates an embedded `bd` panic or an uninitialized "
                "Beads store.\n"
                "Action: run `bd doctor --fix --yes`, verify `bd show --json "
                f"{verification_target}` succeeds, then retry `atelier work`."
            ),
            agent_id=agent_id,
            thread_id=selected_epic,
            beads_root=beads_root,
            repo_root=repo_root,
            dry_run=False,
        )
    except SystemExit:
        pass
    try:
        lifecycle.release_epic_assignment(selected_epic, beads_root=beads_root, repo_root=repo_root)
    except SystemExit:
        pass
    try:
        beads.clear_agent_hook(agent_bead_id, beads_root=beads_root, cwd=repo_root)
    except SystemExit:
        pass
    return WorkerRunSummary(started=False, reason=reason, epic_id=selected_epic)


@dataclass(frozen=True)
class ChangesetSelection:
    issue: dict[str, object] | None
    selected_override: str


class ChangesetSelectionService(Protocol):
    """Typed selection operations for resolving a changeset to execute."""

    def show_issue(self, issue_id: str) -> dict[str, object] | None: ...

    def resolve_epic_id_for_changeset(self, issue: dict[str, object]) -> str | None: ...

    def next_changeset(self, epic_id: str, *, resume_review: bool) -> dict[str, object] | None: ...


def select_changeset(
    *,
    context: ChangesetSelectionContext,
    service: ChangesetSelectionService,
) -> ChangesetSelection:
    """Resolve startup changeset override, then fallback to next ready one."""
    selected_override = (
        str(context.startup_changeset_id).strip() if context.startup_changeset_id else ""
    )
    changeset: dict[str, object] | None = None
    if selected_override:
        override_issue = service.show_issue(selected_override)
        if override_issue:
            parse_issue_boundary(override_issue, source="select_changeset:override")
            resolved_epic = service.resolve_epic_id_for_changeset(override_issue)
            if resolved_epic == context.selected_epic:
                changeset = override_issue
    if changeset is None:
        changeset = service.next_changeset(
            context.selected_epic,
            resume_review=context.resume_review,
        )
        if changeset is not None:
            parse_issue_boundary(changeset, source="select_changeset:next")
    return ChangesetSelection(issue=changeset, selected_override=selected_override)


@dataclass(frozen=True)
class _BoundChangesetSelectionService:
    lifecycle: WorkerLifecycleService
    beads: BeadsService
    beads_root: Path
    repo_root: Path
    repo_slug: str | None
    branch_pr: bool
    branch_pr_strategy: PrStrategy
    git_path: str | None

    def show_issue(self, issue_id: str) -> dict[str, object] | None:
        issues = self.beads.run_bd_json(
            ["show", issue_id],
            beads_root=self.beads_root,
            cwd=self.repo_root,
        )
        return issues[0] if issues else None

    def resolve_epic_id_for_changeset(self, issue: dict[str, object]) -> str | None:
        return self.lifecycle.resolve_epic_id_for_changeset(
            issue,
            beads_root=self.beads_root,
            repo_root=self.repo_root,
        )

    def next_changeset(self, epic_id: str, *, resume_review: bool) -> dict[str, object] | None:
        return self.lifecycle.next_changeset(
            epic_id=epic_id,
            beads_root=self.beads_root,
            repo_root=self.repo_root,
            repo_slug=self.repo_slug,
            branch_pr=self.branch_pr,
            branch_pr_strategy=self.branch_pr_strategy,
            git_path=self.git_path,
            resume_review=resume_review,
        )


@dataclass(frozen=True)
class _ChangesetBlockHandler:
    lifecycle: WorkerLifecycleService
    changeset_id: str
    beads_root: Path
    repo_root: Path

    def mark_changeset_blocked(self, reason: str) -> None:
        self.lifecycle.mark_changeset_blocked(
            self.changeset_id,
            beads_root=self.beads_root,
            repo_root=self.repo_root,
            reason=reason,
        )


def run_worker_once(
    args: object,
    *,
    run_context: WorkerRunContext,
    deps: WorkerRuntimeDependencies,
) -> WorkerRunSummary:
    infra = deps.infra
    lifecycle = deps.lifecycle
    command_ports = deps.commands
    control = deps.control
    """Start a single worker session by selecting an epic and changeset."""
    mode = run_context.mode
    dry_run = run_context.dry_run
    session_key = run_context.session_key
    timings: list[tuple[str, float]] = []
    trace = control.trace_enabled()
    infra.prs.clear_runtime_cache()

    def finish(summary: WorkerRunSummary) -> WorkerRunSummary:
        control.report_timings(timings, trace=trace)
        return summary

    project_root, project_config, _enlistment, repo_root = (
        infra.resolve_current_project_with_repo_root()
    )
    project_data_dir = infra.config.resolve_project_data_dir(project_root, project_config)
    beads_root = infra.config.resolve_beads_root(project_data_dir, repo_root)
    git_path = infra.config.resolve_git_path(project_config)
    if dry_run:
        agent = infra.agent_home.preview_agent_home(
            project_data_dir, project_config, role="worker", session_key=session_key
        )
    else:
        agent = infra.agent_home.resolve_agent_home(
            project_data_dir, project_config, role="worker", session_key=session_key
        )

    with infra.agents.scoped_agent_env(agent.agent_id):
        control.say("Worker session")
        agent_bead_id: str | None = None
        finishstep = control.step("Prime beads", timings=timings, trace=trace)
        if dry_run:
            control.dry_run_log("Would run: bd prime")
        else:
            infra.beads.run_bd_command(["prime"], beads_root=beads_root, cwd=repo_root)
        finishstep()
        finishstep = control.step("Ensure worker agent bead", timings=timings, trace=trace)
        if dry_run:
            agent_bead = infra.beads.find_agent_bead(
                agent.agent_id, beads_root=beads_root, cwd=repo_root
            )
            if agent_bead:
                agent_bead_id = str(agent_bead.get("id")) if agent_bead.get("id") else None
            if not agent_bead_id:
                control.dry_run_log(f"Would create agent bead for {agent.agent_id!r} (worker).")
            control.dry_run_log("Would sync agent home policy.")
        else:
            agent_bead = infra.beads.ensure_agent_bead(
                agent.agent_id, beads_root=beads_root, cwd=repo_root, role="worker"
            )
            bead_id = agent_bead.get("id")
            agent_bead_id = bead_id if isinstance(bead_id, str) and bead_id else None
        finishstep()

        epic_id = getattr(args, "epic_id", None)
        explicit_resume_requested = isinstance(epic_id, str) and bool(epic_id.strip())
        queue_only = bool(getattr(args, "queue", False))
        assume_yes = bool(getattr(args, "yes", False))
        should_reconcile = bool(getattr(args, "reconcile", False))

        if should_reconcile:
            finishstep = control.step("Reconcile blocked changesets", timings=timings, trace=trace)
            reconcile_result = lifecycle.reconcile_blocked_merged_changesets(
                agent_id=agent.agent_id,
                agent_bead_id=agent_bead_id,
                project_config=project_config,
                project_data_dir=project_data_dir,
                beads_root=beads_root,
                repo_root=repo_root,
                git_path=git_path,
                dry_run=dry_run,
                log=control.say,
            )
            finishstep(
                extra=(
                    f"scanned={reconcile_result.scanned}, "
                    f"actionable={reconcile_result.actionable}, "
                    f"reconciled={reconcile_result.reconciled}, "
                    f"failed={reconcile_result.failed}"
                )
            )

        repo_slug = infra.prs.github_repo_slug(
            project_config.project.origin or project_config.project.repo_url
        )
        agent_bead_id_required = ""
        if not dry_run:
            if not isinstance(agent_bead_id, str) or not agent_bead_id:
                control.die("failed to resolve agent bead id")
                return finish(
                    WorkerRunSummary(started=False, reason="missing_agent_bead", epic_id=None)
                )
            agent_bead_id_required = agent_bead_id
        claim_conflict_excluded_epics: set[str] = set()
        startup_result: StartupContractResult
        selected_epic: str
        epic_issue: dict[str, object]
        while True:
            finishstep = control.step("Select epic", timings=timings, trace=trace)
            startup_result = lifecycle.run_startup_contract(
                context=StartupContractContext(
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
                    worker_queue_name=_WORKER_QUEUE_NAME,
                    resume_review=explicit_resume_requested,
                    excluded_epic_ids=tuple(sorted(claim_conflict_excluded_epics)),
                )
            )
            summary_note = startup_result.reason
            if startup_result.epic_id:
                summary_note = f"{summary_note} ({startup_result.epic_id})"
            finishstep(extra=summary_note)
            if startup_result.should_exit:
                if dry_run:
                    control.dry_run_log("Startup contract would exit without starting a worker.")
                return finish(
                    WorkerRunSummary(
                        started=False,
                        reason=startup_result.reason,
                        epic_id=startup_result.epic_id,
                    )
                )
            if not isinstance(startup_result.epic_id, str) or not startup_result.epic_id:
                if dry_run:
                    control.dry_run_log("Startup contract did not select an epic.")
                    return finish(
                        WorkerRunSummary(started=False, reason="no_epic_selected", epic_id=None)
                    )
                control.die("startup contract did not select an epic")
                return finish(
                    WorkerRunSummary(started=False, reason="no_epic_selected", epic_id=None)
                )
            selected_epic = startup_result.epic_id
            finishstep = control.step("Claim epic", timings=timings, trace=trace)
            if dry_run:
                control.dry_run_log(f"Selected epic: {selected_epic}")
                issues = infra.beads.run_bd_json(
                    ["show", selected_epic], beads_root=beads_root, cwd=repo_root
                )
                if not issues:
                    control.dry_run_log(f"Epic {selected_epic!r} not found.")
                    finishstep(extra="epic not found")
                    return finish(
                        WorkerRunSummary(
                            started=False,
                            reason="epic_not_found",
                            epic_id=selected_epic,
                        )
                    )
                epic_issue = issues[0]
                control.dry_run_log(
                    f"Would claim epic {selected_epic!r} for agent {agent.agent_id!r}."
                )
                if startup_result.reassign_from:
                    control.dry_run_log(
                        f"Would reclaim stale epic assignment from {startup_result.reassign_from!r}."
                    )
                finishstep()
                break

            control.say(f"Selected epic: {selected_epic}")
            try:
                epic_issue = infra.beads.claim_epic(
                    selected_epic,
                    agent.agent_id,
                    beads_root=beads_root,
                    cwd=repo_root,
                    allow_takeover_from=startup_result.reassign_from,
                )
            except SystemExit:
                conflicting_assignee = _claim_conflict_assignee(
                    beads=infra.beads,
                    epic_id=selected_epic,
                    agent_id=agent.agent_id,
                    allow_takeover_from=startup_result.reassign_from,
                    beads_root=beads_root,
                    repo_root=repo_root,
                )
                can_retry = (
                    not dry_run
                    and epic_id is None
                    and bool(conflicting_assignee)
                    and selected_epic not in claim_conflict_excluded_epics
                )
                if can_retry and conflicting_assignee is not None:
                    claim_conflict_excluded_epics.add(selected_epic)
                    control.say(
                        "Skipping conflicted epic and retrying selection: "
                        f"{selected_epic} (assigned to {conflicting_assignee})"
                    )
                    finishstep(extra=f"retry after conflict ({selected_epic})")
                    continue
                raise

            if startup_result.reassign_from:
                previous_agent = infra.beads.find_agent_bead(
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
                    infra.beads.clear_agent_hook(
                        previous_agent_id, beads_root=beads_root, cwd=repo_root
                    )
            finishstep()
            break
        finishstep = control.step("Resolve root branch", timings=timings, trace=trace)
        root_branch_value = infra.beads.extract_workspace_root_branch(epic_issue)
        if not root_branch_value:
            root_branch_value = lifecycle.extract_changeset_root_branch(epic_issue)
        suggested_root_branch = None
        if not root_branch_value:
            suggested_root_branch = infra.branching.suggest_root_branch(
                str(epic_issue.get("title") or selected_epic),
                project_config.branch.prefix,
            )
            if dry_run:
                control.dry_run_log("Root branch missing; would prompt for root branch selection.")
                if suggested_root_branch:
                    control.dry_run_log(f"Suggested root branch: {suggested_root_branch!r}.")
                root_branch_value = suggested_root_branch
            else:
                root_branch_value = infra.root_branch.prompt_root_branch(
                    title=str(epic_issue.get("title") or selected_epic),
                    branch_prefix=project_config.branch.prefix,
                    beads_root=beads_root,
                    repo_root=repo_root,
                    assume_yes=assume_yes,
                )
                if not root_branch_value:
                    control.die("failed to resolve root branch")
                    return finish(
                        WorkerRunSummary(
                            started=False,
                            reason="root_branch_unset",
                            epic_id=selected_epic,
                        )
                    )
                infra.beads.update_workspace_root_branch(
                    selected_epic,
                    root_branch_value,
                    beads_root=beads_root,
                    cwd=repo_root,
                )
        finishstep(extra=root_branch_value or "unset")
        finishstep = control.step("Set parent branch + hook", timings=timings, trace=trace)
        parent_branch_value = lifecycle.extract_workspace_parent_branch(epic_issue)
        default_branch = infra.git.git_default_branch(repo_root, git_path=git_path)
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
            control.dry_run_log(f"Would set workspace parent branch to {parent_branch_value!r}.")
            control.dry_run_log("Would set agent hook to selected epic.")
        else:
            infra.beads.update_workspace_parent_branch(
                selected_epic,
                parent_branch_value,
                beads_root=beads_root,
                cwd=repo_root,
                allow_override=allow_parent_override,
            )
            infra.beads.set_agent_hook(
                agent_bead_id_required, selected_epic, beads_root=beads_root, cwd=repo_root
            )
        finishstep()
        finishstep = control.step("Validate changeset labels", timings=timings, trace=trace)
        try:
            invalid_changesets = lifecycle.find_invalid_changeset_labels(
                selected_epic, beads_root=beads_root, repo_root=repo_root
            )
        except SystemExit as exc:
            detail = f"bd read failed (exit={exc.code})"
            finishstep(extra=detail)
            return finish(
                _abort_startup_read_failure(
                    beads=infra.beads,
                    lifecycle=lifecycle,
                    control=control,
                    selected_epic=selected_epic,
                    agent_id=agent.agent_id,
                    agent_bead_id=agent_bead_id_required,
                    beads_root=beads_root,
                    repo_root=repo_root,
                    dry_run=dry_run,
                    stage="validate changeset labels",
                    verification_issue_id=selected_epic,
                    reason="changeset_label_validation_failed",
                )
            )
        if invalid_changesets:
            detail = lifecycle.send_invalid_changeset_labels_notification(
                epic_id=selected_epic,
                invalid_changesets=invalid_changesets,
                agent_id=agent.agent_id,
                beads_root=beads_root,
                repo_root=repo_root,
                dry_run=dry_run,
            )
            finishstep(extra=f"invalid labels: {detail}")
            if dry_run:
                control.dry_run_log("Would release epic assignment and clear agent hook.")
            else:
                lifecycle.release_epic_assignment(
                    selected_epic, beads_root=beads_root, repo_root=repo_root
                )
                infra.beads.clear_agent_hook(
                    agent_bead_id_required, beads_root=beads_root, cwd=repo_root
                )
            return finish(
                WorkerRunSummary(
                    started=False,
                    reason="changeset_label_violation",
                    epic_id=selected_epic,
                )
            )
        finishstep()
        finishstep = control.step("Select changeset", timings=timings, trace=trace)
        try:
            selected = select_changeset(
                context=ChangesetSelectionContext(
                    selected_epic=selected_epic,
                    startup_changeset_id=startup_result.changeset_id,
                    resume_review=explicit_resume_requested
                    and startup_result.reason == "explicit_epic",
                ),
                service=_BoundChangesetSelectionService(
                    lifecycle=lifecycle,
                    beads=infra.beads,
                    beads_root=beads_root,
                    repo_root=repo_root,
                    repo_slug=repo_slug,
                    branch_pr=project_config.branch.pr,
                    branch_pr_strategy=project_config.branch.pr_strategy,
                    git_path=git_path,
                ),
            )
        except SystemExit as exc:
            detail = f"bd read failed (exit={exc.code})"
            finishstep(extra=detail)
            return finish(
                _abort_startup_read_failure(
                    beads=infra.beads,
                    lifecycle=lifecycle,
                    control=control,
                    selected_epic=selected_epic,
                    agent_id=agent.agent_id,
                    agent_bead_id=agent_bead_id_required,
                    beads_root=beads_root,
                    repo_root=repo_root,
                    dry_run=dry_run,
                    stage="select startup changeset",
                    verification_issue_id=startup_result.changeset_id or selected_epic,
                    reason="changeset_selection_read_failed",
                )
            )
        changeset = selected.issue
        selected_changeset_override = selected.selected_override
        if changeset is None:
            lifecycle.send_no_ready_changesets(
                epic_id=selected_epic,
                agent_id=agent.agent_id,
                beads_root=beads_root,
                repo_root=repo_root,
                dry_run=dry_run,
            )
            finishstep(extra="no ready changesets")
            if dry_run:
                control.dry_run_log("Would release epic assignment and clear agent hook.")
                return finish(
                    WorkerRunSummary(
                        started=False,
                        reason="no_ready_changesets",
                        epic_id=selected_epic,
                    )
                )
            lifecycle.release_epic_assignment(
                selected_epic, beads_root=beads_root, repo_root=repo_root
            )
            infra.beads.clear_agent_hook(
                agent_bead_id_required, beads_root=beads_root, cwd=repo_root
            )
            return finish(
                WorkerRunSummary(started=False, reason="no_ready_changesets", epic_id=selected_epic)
            )
        changeset_extra = str(changeset.get("id") or "unknown")
        if selected_changeset_override and changeset_extra == selected_changeset_override:
            selection_mode = startup_result.reason
            if selection_mode in {"review_feedback", "merge_conflict"}:
                changeset_extra = f"{changeset_extra} ({selection_mode})"
        finishstep(extra=changeset_extra)
        changeset_boundary = parse_issue_boundary(changeset, source="run_worker_once:changeset")
        changeset_id = changeset_boundary.id
        raw_changeset_title = changeset.get("title")
        changeset_title = raw_changeset_title if isinstance(raw_changeset_title, str) else ""
        parent_branch_for_changeset = root_branch_value
        allow_parent_branch_override = False
        if parent_branch_for_changeset and changeset_id:
            if dry_run:
                parent_branch_for_changeset = lifecycle.changeset_parent_branch(
                    changeset,
                    root_branch=parent_branch_for_changeset,
                )
            else:
                try:
                    selected_changeset = infra.beads.run_bd_json(
                        ["show", str(changeset_id)], beads_root=beads_root, cwd=repo_root
                    )
                except SystemExit:
                    return finish(
                        _abort_startup_read_failure(
                            beads=infra.beads,
                            lifecycle=lifecycle,
                            control=control,
                            selected_epic=selected_epic,
                            agent_id=agent.agent_id,
                            agent_bead_id=agent_bead_id_required,
                            beads_root=beads_root,
                            repo_root=repo_root,
                            dry_run=dry_run,
                            stage="read selected changeset metadata",
                            verification_issue_id=str(changeset_id),
                            reason="changeset_metadata_read_failed",
                        )
                    )
                if selected_changeset:
                    current_parent_branch = changeset_fields.parent_branch(selected_changeset[0])
                    parent_branch_for_changeset = lifecycle.changeset_parent_branch(
                        selected_changeset[0],
                        root_branch=parent_branch_for_changeset,
                        beads_root=beads_root,
                        repo_root=repo_root,
                    )
                    if (
                        current_parent_branch
                        and current_parent_branch != parent_branch_for_changeset
                    ):
                        allow_parent_branch_override = True
        if dry_run:
            control.dry_run_log(f"Next changeset: {changeset_id} {changeset_title}")
        else:
            control.say(f"Next changeset: {changeset_id} {changeset_title}")
        finishstep = control.step("Prepare worktrees", timings=timings, trace=trace)
        worktree_prep = infra.worker_session_worktree.prepare_worktrees(
            context=WorktreePreparationContext(
                dry_run=dry_run,
                project_data_dir=project_data_dir,
                repo_root=repo_root,
                beads_root=beads_root,
                selected_epic=selected_epic,
                changeset_id=str(changeset_id),
                root_branch_value=root_branch_value or "",
                changeset_parent_branch=parent_branch_for_changeset or "",
                allow_parent_branch_override=allow_parent_branch_override,
                git_path=git_path,
            ),
            control=control,
        )
        changeset_worktree_path = worktree_prep.changeset_worktree_path
        finishstep()
        finishstep = control.step("Mark changeset in progress", timings=timings, trace=trace)
        if changeset_id:
            if dry_run:
                control.dry_run_log(f"Would mark changeset {changeset_id} in progress.")
            else:
                lifecycle.mark_changeset_in_progress(
                    changeset_id, beads_root=beads_root, repo_root=repo_root
                )
        finishstep()

        finishstep = control.step("Prepare agent session", timings=timings, trace=trace)
        agent_prep = None
        try:
            agent_prep = infra.worker_session_agent.prepare_agent_session(
                project_config=project_config,
                project_data_dir=project_data_dir,
                repo_root=repo_root,
                beads_root=beads_root,
                agent=agent,
                changeset_worktree_path=changeset_worktree_path,
                selected_epic=selected_epic,
                changeset_id=str(changeset_id),
                root_branch_value=root_branch_value or "",
                enlistment_path=Path(_enlistment),
                yes=bool(getattr(args, "yes", False)),
                dry_run=dry_run,
                session_control=control,
                command_ops=command_ports,
            )
        except RuntimeError as exc:
            control.die(str(exc))
            return finish(
                WorkerRunSummary(
                    started=False,
                    reason="agent_prepare_failed",
                    epic_id=selected_epic,
                    changeset_id=changeset_id,
                )
            )
        if agent_prep is None:
            control.die("failed to prepare agent session")
            return finish(
                WorkerRunSummary(
                    started=False,
                    reason="agent_prepare_failed",
                    epic_id=selected_epic,
                    changeset_id=changeset_id,
                )
            )
        agent_spec = agent_prep.agent_spec
        agent_options = agent_prep.agent_options
        project_enlistment = agent_prep.project_enlistment
        workspace_branch = agent_prep.workspace_branch
        env = agent_prep.env
        finishstep()
        opening_prompt = ""
        merge_conflict = startup_result.reason == "merge_conflict"
        review_feedback = startup_result.reason == "review_feedback"
        feedback_before = None
        if agent_spec.name == "codex":
            followup_mode = merge_conflict or review_feedback
            review_pr_url = lifecycle.changeset_pr_url(changeset) if followup_mode else None
            if followup_mode and not review_pr_url and repo_slug:
                feedback_branch = lifecycle.changeset_work_branch(changeset)
                if feedback_branch:
                    pr_payload = lifecycle.lookup_pr_payload(repo_slug, feedback_branch)
                    if pr_payload:
                        payload_url = pr_payload.get("url")
                        if isinstance(payload_url, str) and payload_url.strip():
                            review_pr_url = payload_url.strip()
            opening_prompt = command_ports.worker_opening_prompt(
                project_enlistment=project_enlistment,
                workspace_branch=workspace_branch,
                epic_id=selected_epic,
                changeset_id=str(changeset_id),
                changeset_title=str(changeset_title),
                merge_conflict=merge_conflict,
                review_feedback=review_feedback,
                review_pr_url=review_pr_url,
            )
        if review_feedback:
            feedback_before = lifecycle.capture_review_feedback_snapshot(
                issue=changeset,
                repo_slug=repo_slug,
                repo_root=repo_root,
                git_path=git_path,
            )
        finishstep = control.step("Install agent hooks", timings=timings, trace=trace)
        infra.worker_session_agent.install_agent_hooks(
            dry_run=dry_run,
            agent=agent,
            agent_spec=agent_spec,
            env=env,
            session_control=control,
        )
        finishstep()
        finishstep = control.step("Start agent session", timings=timings, trace=trace)
        if dry_run:
            control.dry_run_log(f"Would start {agent_spec.display_name} session.")
        session_result = infra.worker_session_agent.start_agent_session(
            dry_run=dry_run,
            agent=agent,
            agent_spec=agent_spec,
            agent_options=agent_options,
            opening_prompt=opening_prompt,
            env=env,
            command_ops=command_ports,
            session_control=control,
            blocked_handler=_ChangesetBlockHandler(
                lifecycle=lifecycle,
                changeset_id=str(changeset_id),
                beads_root=beads_root,
                repo_root=repo_root,
            ),
        )
        if session_result is None:
            finishstep(extra="dry run")
            return finish(
                WorkerRunSummary(
                    started=False,
                    reason="dry_run",
                    epic_id=selected_epic,
                    changeset_id=str(changeset_id) if changeset_id else None,
                )
            )
        started_at = session_result.started_at
        finishstep(extra=f"exit={session_result.returncode}")
        finishstep = control.step("Finalize changeset", timings=timings, trace=trace)
        finalize_result = lifecycle.finalize_changeset(
            changeset_id=changeset_id,
            epic_id=selected_epic,
            agent_id=agent.agent_id,
            agent_bead_id=agent_bead_id_required,
            started_at=started_at,
            repo_slug=repo_slug,
            beads_root=beads_root,
            repo_root=repo_root,
            branch_pr=project_config.branch.pr,
            branch_pr_mode=project_config.branch.pr_mode,
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
            feedback_after = lifecycle.capture_review_feedback_snapshot(
                issue=changeset,
                repo_slug=repo_slug,
                repo_root=repo_root,
                git_path=git_path,
            )
            if feedback_before is not None and not lifecycle.review_feedback_progressed(
                feedback_before, feedback_after
            ):
                lifecycle.mark_changeset_in_progress(
                    changeset_id, beads_root=beads_root, repo_root=repo_root
                )
                lifecycle.send_planner_notification(
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
                finishstep(extra="changeset_feedback_not_addressed")
                return finish(
                    WorkerRunSummary(
                        started=False,
                        reason="changeset_feedback_not_addressed",
                        epic_id=selected_epic,
                        changeset_id=str(changeset_id) if changeset_id else None,
                    )
                )
            lifecycle.persist_review_feedback_cursor(
                changeset_id=changeset_id,
                issue=changeset,
                repo_slug=repo_slug,
                beads_root=beads_root,
                repo_root=repo_root,
            )
        terminal_review_handoff = (
            finalize_result.continue_running
            and finalize_result.reason == "changeset_review_pending"
            and not review_feedback
            and not explicit_resume_requested
        )
        if terminal_review_handoff:
            control.say(
                "Review handoff reached; stopping autonomous loop after PR publication. "
                f"Rerun with explicit epic selection to resume `{changeset_id}`."
            )
            finishstep(extra="changeset_review_handoff")
            return finish(
                WorkerRunSummary(
                    started=False,
                    reason="changeset_review_handoff",
                    epic_id=selected_epic,
                    changeset_id=str(changeset_id) if changeset_id else None,
                )
            )
        finishstep(extra=finalize_result.reason)
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

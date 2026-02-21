"""Worker session runner helpers shared by command orchestration."""

from __future__ import annotations

from dataclasses import dataclass

from ..context import ChangesetSelectionContext, WorkerRunContext
from ..models import WorkerRunSummary
from ..ports import ChangesetSelectionPorts, WorkerRuntimeDependencies


@dataclass(frozen=True)
class ChangesetSelection:
    issue: dict[str, object] | None
    selected_override: str


def select_changeset(
    *,
    context: ChangesetSelectionContext,
    ports: ChangesetSelectionPorts,
) -> ChangesetSelection:
    """Resolve explicit startup changeset override, then fallback to next-ready."""
    selected_override = (
        str(context.startup_changeset_id).strip()
        if context.startup_changeset_id
        else ""
    )
    changeset: dict[str, object] | None = None
    if selected_override:
        override_issue = ports.run_bd_json(
            ["show", selected_override],
            beads_root=context.beads_root,
            cwd=context.repo_root,
        )
        if override_issue:
            resolved_epic = ports.resolve_epic_id_for_changeset(
                override_issue[0],
                beads_root=context.beads_root,
                repo_root=context.repo_root,
            )
            if resolved_epic == context.selected_epic:
                changeset = override_issue[0]
    if changeset is None:
        changeset = ports.next_changeset(
            epic_id=context.selected_epic,
            beads_root=context.beads_root,
            repo_root=context.repo_root,
            repo_slug=context.repo_slug,
            branch_pr=context.branch_pr,
            branch_pr_strategy=context.branch_pr_strategy,
            git_path=context.git_path,
        )
    return ChangesetSelection(issue=changeset, selected_override=selected_override)


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
    project_data_dir = infra.config.resolve_project_data_dir(
        project_root, project_config
    )
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
        finishstep = control.step(
            "Ensure worker agent bead", timings=timings, trace=trace
        )
        if dry_run:
            agent_bead = infra.beads.find_agent_bead(
                agent.agent_id, beads_root=beads_root, cwd=repo_root
            )
            if agent_bead:
                agent_bead_id = (
                    str(agent_bead.get("id")) if agent_bead.get("id") else None
                )
            if not agent_bead_id:
                control.dry_run_log(
                    f"Would create agent bead for {agent.agent_id!r} (worker)."
                )
            control.dry_run_log("Would sync agent home policy.")
        else:
            agent_bead = infra.beads.ensure_agent_bead(
                agent.agent_id, beads_root=beads_root, cwd=repo_root, role="worker"
            )
            agent_bead_id = agent_bead.get("id")
        finishstep()

        epic_id = getattr(args, "epic_id", None)
        queue_only = bool(getattr(args, "queue", False))
        assume_yes = bool(getattr(args, "yes", False))
        should_reconcile = bool(getattr(args, "reconcile", False))

        if not dry_run:
            if not isinstance(agent_bead_id, str) or not agent_bead_id:
                control.die("failed to resolve agent bead id")

        if should_reconcile:
            finishstep = control.step(
                "Reconcile blocked changesets", timings=timings, trace=trace
            )
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
        finishstep = control.step("Select epic", timings=timings, trace=trace)
        startup_result = lifecycle.run_startup_contract(
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
        finishstep(extra=summary_note)
        if startup_result.should_exit:
            if dry_run:
                control.dry_run_log(
                    "Startup contract would exit without starting a worker."
                )
            return finish(
                WorkerRunSummary(
                    started=False,
                    reason=startup_result.reason,
                    epic_id=startup_result.epic_id,
                )
            )
        if not startup_result.epic_id:
            if dry_run:
                control.dry_run_log("Startup contract did not select an epic.")
                return finish(
                    WorkerRunSummary(
                        started=False, reason="no_epic_selected", epic_id=None
                    )
                )
            control.die("startup contract did not select an epic")
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
                        started=False, reason="epic_not_found", epic_id=selected_epic
                    )
                )
            epic_issue = issues[0]
            control.dry_run_log(
                f"Would claim epic {selected_epic!r} for agent {agent.agent_id!r}."
            )
            if startup_result.reassign_from:
                control.dry_run_log(
                    "Would reclaim stale epic assignment from "
                    f"{startup_result.reassign_from!r}."
                )
        else:
            control.say(f"Selected epic: {selected_epic}")
            epic_issue = infra.beads.claim_epic(
                selected_epic,
                agent.agent_id,
                beads_root=beads_root,
                cwd=repo_root,
                allow_takeover_from=startup_result.reassign_from,
            )
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
                control.dry_run_log(
                    "Root branch missing; would prompt for root branch selection."
                )
                if suggested_root_branch:
                    control.dry_run_log(
                        f"Suggested root branch: {suggested_root_branch!r}."
                    )
                root_branch_value = suggested_root_branch
            else:
                root_branch_value = infra.root_branch.prompt_root_branch(
                    title=str(epic_issue.get("title") or selected_epic),
                    branch_prefix=project_config.branch.prefix,
                    beads_root=beads_root,
                    repo_root=repo_root,
                    assume_yes=assume_yes,
                )
                infra.beads.update_workspace_root_branch(
                    selected_epic,
                    root_branch_value,
                    beads_root=beads_root,
                    cwd=repo_root,
                )
        finishstep(extra=root_branch_value or "unset")
        finishstep = control.step(
            "Set parent branch + hook", timings=timings, trace=trace
        )
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
            control.dry_run_log(
                f"Would set workspace parent branch to {parent_branch_value!r}."
            )
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
                agent_bead_id, selected_epic, beads_root=beads_root, cwd=repo_root
            )
        finishstep()
        finishstep = control.step(
            "Validate changeset labels", timings=timings, trace=trace
        )
        invalid_changesets = lifecycle.find_invalid_changeset_labels(
            selected_epic, beads_root=beads_root, repo_root=repo_root
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
                control.dry_run_log(
                    "Would release epic assignment and clear agent hook."
                )
            else:
                lifecycle.release_epic_assignment(
                    selected_epic, beads_root=beads_root, repo_root=repo_root
                )
                infra.beads.clear_agent_hook(
                    agent_bead_id, beads_root=beads_root, cwd=repo_root
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
        selected = select_changeset(
            context=ChangesetSelectionContext(
                selected_epic=selected_epic,
                startup_changeset_id=startup_result.changeset_id,
                beads_root=beads_root,
                repo_root=repo_root,
                repo_slug=repo_slug,
                branch_pr=project_config.branch.pr,
                branch_pr_strategy=project_config.branch.pr_strategy,
                git_path=git_path,
            ),
            ports=ChangesetSelectionPorts(
                run_bd_json=infra.beads.run_bd_json,
                resolve_epic_id_for_changeset=lifecycle.resolve_epic_id_for_changeset,
                next_changeset=lifecycle.next_changeset,
            ),
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
                control.dry_run_log(
                    "Would release epic assignment and clear agent hook."
                )
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
                agent_bead_id, beads_root=beads_root, cwd=repo_root
            )
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
        finishstep(extra=changeset_extra)
        changeset_id = changeset.get("id") or ""
        changeset_title = changeset.get("title") or ""
        parent_branch_for_changeset = root_branch_value
        if parent_branch_for_changeset and changeset_id:
            if dry_run:
                parent_branch_for_changeset = lifecycle.changeset_parent_branch(
                    changeset, root_branch=parent_branch_for_changeset
                )
            else:
                selected_changeset = infra.beads.run_bd_json(
                    ["show", str(changeset_id)], beads_root=beads_root, cwd=repo_root
                )
                if selected_changeset:
                    parent_branch_for_changeset = lifecycle.changeset_parent_branch(
                        selected_changeset[0], root_branch=parent_branch_for_changeset
                    )
        if dry_run:
            control.dry_run_log(f"Next changeset: {changeset_id} {changeset_title}")
        else:
            control.say(f"Next changeset: {changeset_id} {changeset_title}")
        finishstep = control.step("Prepare worktrees", timings=timings, trace=trace)
        worktree_prep = infra.worker_session_worktree.prepare_worktrees(
            dry_run=dry_run,
            project_data_dir=project_data_dir,
            repo_root=repo_root,
            beads_root=beads_root,
            selected_epic=selected_epic,
            changeset_id=str(changeset_id),
            root_branch_value=root_branch_value or "",
            changeset_parent_branch=parent_branch_for_changeset or "",
            git_path=git_path,
            emit=control.say,
            dry_run_log=control.dry_run_log,
        )
        changeset_worktree_path = worktree_prep.changeset_worktree_path
        finishstep()
        finishstep = control.step(
            "Mark changeset in progress", timings=timings, trace=trace
        )
        if changeset_id:
            if dry_run:
                control.dry_run_log(f"Would mark changeset {changeset_id} in progress.")
            else:
                lifecycle.mark_changeset_in_progress(
                    changeset_id, beads_root=beads_root, repo_root=repo_root
                )
        finishstep()

        finishstep = control.step("Prepare agent session", timings=timings, trace=trace)
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
                enlistment_path=_enlistment,
                yes=bool(getattr(args, "yes", False)),
                dry_run=dry_run,
                strip_flag_with_value=command_ports.strip_flag_with_value,
                confirm_update=lambda message: control.confirm(message, default=False),
                dry_run_log=control.dry_run_log,
                emit=control.say,
            )
        except RuntimeError as exc:
            control.die(str(exc))
        agent_spec = agent_prep.agent_spec
        agent_options = agent_prep.agent_options
        project_enlistment = agent_prep.project_enlistment
        workspace_branch = agent_prep.workspace_branch
        env = agent_prep.env
        finishstep()
        opening_prompt = ""
        review_feedback = startup_result.reason == "review_feedback"
        feedback_before = None
        if agent_spec.name == "codex":
            review_pr_url = (
                lifecycle.changeset_pr_url(changeset) if review_feedback else None
            )
            if review_feedback and not review_pr_url and repo_slug:
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
            dry_run_log=control.dry_run_log,
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
            with_codex_exec=command_ports.with_codex_exec,
            strip_flag_with_value=command_ports.strip_flag_with_value,
            ensure_exec_subcommand_flag=command_ports.ensure_exec_subcommand_flag,
            mark_changeset_blocked=lambda reason: lifecycle.mark_changeset_blocked(
                changeset_id,
                beads_root=beads_root,
                repo_root=repo_root,
                reason=reason,
            ),
            die_fn=control.die,
            dry_run_log=control.dry_run_log,
            emit=control.say,
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

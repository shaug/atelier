"""Worker session command implementation.

Starts worker sessions by selecting an epic and its next ready changeset.
``atelier work`` can loop or watch based on run mode.
"""

from __future__ import annotations

import datetime as dt
import os
import time
from dataclasses import dataclass
from pathlib import Path

from .. import (
    agent_home,
    agents,
    beads,
    codex,
    config,
    exec,
    git,
    hooks,
    messages,
    paths,
    policy,
    prompting,
    root_branch,
    templates,
    workspace,
    worktrees,
)
from ..io import die, prompt, say
from .resolve import resolve_current_project_with_repo_root

_MODE_VALUES = {"prompt", "auto"}
_RUN_MODE_VALUES = {"once", "default", "watch"}
_WATCH_INTERVAL_SECONDS = 60


@dataclass(frozen=True)
class StartupContractResult:
    epic_id: str | None
    should_exit: bool


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
    if not status:
        return True
    normalized = status.lower()
    if normalized in {"open", "ready", "in_progress"}:
        return True
    if allow_hooked and normalized == "hooked":
        return True
    return False


def _filter_epics(
    issues: list[dict[str, object]],
    *,
    assignee: str | None = None,
    require_unassigned: bool = False,
) -> list[dict[str, object]]:
    filtered: list[dict[str, object]] = []
    for issue in issues:
        status = str(issue.get("status") or "")
        if not _is_eligible_status(status, allow_hooked=assignee is not None):
            continue
        labels = _issue_labels(issue)
        if "at:draft" in labels:
            continue
        issue_assignee = issue.get("assignee")
        if assignee is not None:
            if issue_assignee != assignee:
                continue
        elif require_unassigned and issue_assignee:
            continue
        filtered.append(issue)
    return filtered


def _parse_issue_time(value: object) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


def _sort_by_created_at(
    issues: list[dict[str, object]], *, newest: bool = False
) -> list[dict[str, object]]:
    sentinel = dt.datetime.max.replace(tzinfo=dt.timezone.utc)
    return sorted(
        issues,
        key=lambda issue: _parse_issue_time(issue.get("created_at")) or sentinel,
        reverse=newest,
    )


def _sort_by_recency(issues: list[dict[str, object]]) -> list[dict[str, object]]:
    sentinel = dt.datetime.min.replace(tzinfo=dt.timezone.utc)

    def key(issue: dict[str, object]) -> dt.datetime:
        updated = _parse_issue_time(issue.get("updated_at"))
        if updated:
            return updated
        created = _parse_issue_time(issue.get("created_at"))
        if created:
            return created
        return sentinel

    return sorted(issues, key=key, reverse=True)


def _list_epics(*, beads_root: Path, repo_root: Path) -> list[dict[str, object]]:
    return beads.run_bd_json(
        ["list", "--label", "at:epic"], beads_root=beads_root, cwd=repo_root
    )


def _select_epic_prompt(
    issues: list[dict[str, object]], *, agent_id: str
) -> str | None:
    epics = _filter_epics(issues, require_unassigned=True)
    resume = _filter_epics(issues, assignee=agent_id)
    if not epics and not resume:
        return None
    if epics:
        say("Available epics:")
    for issue in epics:
        issue_id = issue.get("id") or ""
        status = issue.get("status") or "unknown"
        title = issue.get("title") or ""
        root_branch_value = beads.extract_workspace_root_branch(issue) or "unset"
        say(f"- {issue_id} [{status}] {root_branch_value} {title}")
    resume = _sort_by_recency(resume)
    if resume:
        say("Resume epics:")
    for issue in resume:
        issue_id = issue.get("id") or ""
        status = issue.get("status") or "unknown"
        title = issue.get("title") or ""
        root_branch_value = beads.extract_workspace_root_branch(issue) or "unset"
        say(f"- {issue_id} [{status}] {root_branch_value} {title}")
    selection = prompt("Epic id")
    selection = selection.strip()
    if not selection:
        die("epic id is required")
    valid_ids = {str(issue.get("id")) for issue in epics + resume if issue.get("id")}
    if selection not in valid_ids:
        die(f"unknown epic id: {selection}")
    return selection


def _select_epic_auto(issues: list[dict[str, object]], *, agent_id: str) -> str | None:
    ready = _filter_epics(issues, require_unassigned=True)
    if ready:
        ready = _sort_by_created_at(ready)
        return str(ready[0].get("id"))
    unfinished = _filter_epics(issues, assignee=agent_id)
    if unfinished:
        unfinished = _sort_by_created_at(unfinished)
        return str(unfinished[0].get("id"))
    return None


def _send_needs_decision(
    *,
    agent_id: str,
    mode: str,
    issues: list[dict[str, object]],
    beads_root: Path,
    repo_root: Path,
) -> None:
    ready = _filter_epics(issues, require_unassigned=True)
    assigned = _filter_epics(issues, assignee=agent_id)
    subject = "NEEDS-DECISION: No eligible epics"
    timestamp = dt.datetime.now(tz=dt.timezone.utc).isoformat()
    body = "\n".join(
        [
            f"Agent: {agent_id}",
            f"Mode: {mode}",
            f"Total epics: {len(issues)}",
            f"Ready epics: {len(ready)}",
            f"Assigned epics: {len(assigned)}",
            f"Timestamp: {timestamp}",
        ]
    )
    beads.create_message_bead(
        subject=subject,
        body=body,
        metadata={"from": agent_id, "queue": "overseer", "msg_type": "notification"},
        beads_root=beads_root,
        cwd=repo_root,
    )


def _next_changeset(
    *, epic_id: str, beads_root: Path, repo_root: Path
) -> dict[str, object]:
    changesets = beads.run_bd_json(
        [
            "ready",
            "--parent",
            epic_id,
            "--label",
            "at:changeset",
            "--label",
            "cs:ready",
        ],
        beads_root=beads_root,
        cwd=repo_root,
    )
    if not changesets:
        die(f"no ready changesets found for epic {epic_id}")
    return changesets[0]


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
    beads.run_bd_command(
        [
            "update",
            changeset_id,
            "--add-label",
            "cs:in_progress",
            "--remove-label",
            "cs:ready",
            "--status",
            "in_progress",
        ],
        beads_root=beads_root,
        cwd=repo_root,
    )


def _mark_changeset_closed(
    changeset_id: str, *, beads_root: Path, repo_root: Path
) -> None:
    beads.run_bd_command(
        [
            "update",
            changeset_id,
            "--status",
            "closed",
            "--remove-label",
            "cs:ready",
            "--remove-label",
            "cs:planned",
            "--remove-label",
            "cs:in_progress",
        ],
        beads_root=beads_root,
        cwd=repo_root,
    )


def _mark_changeset_blocked(
    changeset_id: str, *, beads_root: Path, repo_root: Path, reason: str
) -> None:
    timestamp = dt.datetime.now(tz=dt.timezone.utc).isoformat()
    note = f"blocked_at: {timestamp} reason: {reason}"
    beads.run_bd_command(
        [
            "update",
            changeset_id,
            "--remove-label",
            "cs:in_progress",
            "--status",
            "open",
            "--append-notes",
            note,
        ],
        beads_root=beads_root,
        cwd=repo_root,
    )


def _has_blocking_messages(
    *,
    thread_ids: set[str],
    started_at: dt.datetime,
    beads_root: Path,
    repo_root: Path,
) -> bool:
    issues = beads.run_bd_json(
        ["list", "--label", "at:message"], beads_root=beads_root, cwd=repo_root
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


def _finalize_changeset(
    *,
    changeset_id: str,
    epic_id: str,
    agent_bead_id: str,
    started_at: dt.datetime,
    beads_root: Path,
    repo_root: Path,
) -> None:
    if not changeset_id:
        return
    issues = beads.run_bd_json(
        ["show", changeset_id], beads_root=beads_root, cwd=repo_root
    )
    if not issues:
        return
    labels = _issue_labels(issues[0])
    if "cs:merged" in labels or "cs:abandoned" in labels:
        _mark_changeset_closed(changeset_id, beads_root=beads_root, repo_root=repo_root)
        beads.close_epic_if_complete(
            epic_id, agent_bead_id, beads_root=beads_root, cwd=repo_root
        )
        return
    if _has_blocking_messages(
        thread_ids={changeset_id, epic_id},
        started_at=started_at,
        beads_root=beads_root,
        repo_root=repo_root,
    ):
        _mark_changeset_blocked(
            changeset_id,
            beads_root=beads_root,
            repo_root=repo_root,
            reason="message requires planner decision",
        )


def _check_inbox_before_claim(
    agent_id: str, *, beads_root: Path, repo_root: Path
) -> bool:
    inbox = beads.list_inbox_messages(
        agent_id, beads_root=beads_root, cwd=repo_root, unread_only=True
    )
    if inbox:
        say(f"Inbox has {len(inbox)} unread message(s); review before claiming work.")
        return True
    return False


def _prompt_queue_claim(
    queued: list[dict[str, object]],
    *,
    agent_id: str,
    beads_root: Path,
    repo_root: Path,
) -> None:
    say("Queued messages:")
    for issue in queued:
        issue_id = issue.get("id") or ""
        queue_name = issue.get("queue") or "queue"
        title = issue.get("title") or ""
        say(f"- {issue_id} [{queue_name}] {title}")
    selection = prompt("Queue message id (blank to skip)")
    selection = selection.strip()
    if not selection:
        return
    valid_ids = {str(issue.get("id")) for issue in queued if issue.get("id")}
    if selection not in valid_ids:
        die(f"unknown queue message id: {selection}")
    beads.claim_queue_message(selection, agent_id, beads_root=beads_root, cwd=repo_root)
    say(f"Claimed queue message: {selection}")


def _handle_queue_before_claim(
    agent_id: str,
    *,
    beads_root: Path,
    repo_root: Path,
    force_prompt: bool = False,
) -> bool:
    queued = beads.list_queue_messages(beads_root=beads_root, cwd=repo_root)
    if not queued:
        if force_prompt:
            say("No queued messages available.")
            return True
        return False
    _prompt_queue_claim(
        queued, agent_id=agent_id, beads_root=beads_root, repo_root=repo_root
    )
    return True


def _run_startup_contract(
    *,
    agent_id: str,
    agent_bead_id: str,
    beads_root: Path,
    repo_root: Path,
    mode: str,
    explicit_epic_id: str | None,
    queue_only: bool,
) -> StartupContractResult:
    """Apply startup_contract skill ordering to select the next epic."""
    if explicit_epic_id is not None:
        selected_epic = str(explicit_epic_id).strip()
        if not selected_epic:
            die("epic id must not be empty")
        return StartupContractResult(epic_id=selected_epic, should_exit=False)

    if queue_only:
        _handle_queue_before_claim(
            agent_id,
            beads_root=beads_root,
            repo_root=repo_root,
            force_prompt=True,
        )
        return StartupContractResult(epic_id=None, should_exit=True)

    hooked_epic = _resolve_hooked_epic(
        agent_bead_id, agent_id, beads_root=beads_root, repo_root=repo_root
    )
    if hooked_epic:
        say(f"Resuming hooked epic: {hooked_epic}")
        return StartupContractResult(epic_id=hooked_epic, should_exit=False)

    issues = _list_epics(beads_root=beads_root, repo_root=repo_root)
    assigned = _filter_epics(issues, assignee=agent_id)
    assigned = _sort_by_created_at(assigned)
    if assigned:
        candidate = assigned[0].get("id")
        if candidate:
            selected_epic = str(candidate)
            say(f"Resuming assigned epic: {selected_epic}")
            return StartupContractResult(epic_id=selected_epic, should_exit=False)

    if _check_inbox_before_claim(agent_id, beads_root=beads_root, repo_root=repo_root):
        return StartupContractResult(epic_id=None, should_exit=True)
    if _handle_queue_before_claim(agent_id, beads_root=beads_root, repo_root=repo_root):
        return StartupContractResult(epic_id=None, should_exit=True)

    if mode == "auto":
        selected_epic = _select_epic_auto(issues, agent_id=agent_id)
    else:
        selected_epic = _select_epic_prompt(issues, agent_id=agent_id)

    if selected_epic is None:
        _send_needs_decision(
            agent_id=agent_id,
            mode=mode,
            issues=issues,
            beads_root=beads_root,
            repo_root=repo_root,
        )
        return StartupContractResult(epic_id=None, should_exit=True)

    return StartupContractResult(epic_id=selected_epic, should_exit=False)


def _run_worker_once(args: object, *, mode: str) -> bool:
    """Start a single worker session by selecting an epic and changeset."""
    project_root, project_config, _enlistment, repo_root = (
        resolve_current_project_with_repo_root()
    )
    project_data_dir = config.resolve_project_data_dir(project_root, project_config)
    beads_root = config.resolve_beads_root(project_data_dir, repo_root)
    agent = agent_home.resolve_agent_home(
        project_data_dir, project_config, role="worker"
    )

    with agents.scoped_agent_env(agent.agent_id):
        beads.run_bd_command(["prime"], beads_root=beads_root, cwd=repo_root)
        agent_bead = beads.ensure_agent_bead(
            agent.agent_id, beads_root=beads_root, cwd=repo_root, role="worker"
        )
        policy.sync_agent_home_policy(
            agent, role=policy.ROLE_WORKER, beads_root=beads_root, cwd=repo_root
        )

        epic_id = getattr(args, "epic_id", None)
        queue_only = bool(getattr(args, "queue", False))

        agent_bead_id = agent_bead.get("id")
        if not isinstance(agent_bead_id, str) or not agent_bead_id:
            die("failed to resolve agent bead id")

        startup_result = _run_startup_contract(
            agent_id=agent.agent_id,
            agent_bead_id=agent_bead_id,
            beads_root=beads_root,
            repo_root=repo_root,
            mode=mode,
            explicit_epic_id=epic_id,
            queue_only=queue_only,
        )
        if startup_result.should_exit:
            return False
        if not startup_result.epic_id:
            die("startup contract did not select an epic")
        selected_epic = startup_result.epic_id

        say(f"Selected epic: {selected_epic}")
        epic_issue = beads.claim_epic(
            selected_epic, agent.agent_id, beads_root=beads_root, cwd=repo_root
        )
        root_branch_value = beads.extract_workspace_root_branch(epic_issue)
        if not root_branch_value:
            root_branch_value = root_branch.prompt_root_branch(
                title=str(epic_issue.get("title") or selected_epic),
                branch_prefix=project_config.branch.prefix,
                beads_root=beads_root,
                repo_root=repo_root,
            )
            beads.update_workspace_root_branch(
                selected_epic, root_branch_value, beads_root=beads_root, cwd=repo_root
            )
        parent_branch_value = root_branch_value
        beads.update_workspace_parent_branch(
            selected_epic, parent_branch_value, beads_root=beads_root, cwd=repo_root
        )
        beads.set_agent_hook(
            agent_bead_id, selected_epic, beads_root=beads_root, cwd=repo_root
        )
        changeset = _next_changeset(
            epic_id=selected_epic, beads_root=beads_root, repo_root=repo_root
        )
        changeset_id = changeset.get("id") or ""
        changeset_title = changeset.get("title") or ""
        say(f"Next changeset: {changeset_id} {changeset_title}")
        if changeset_id:
            _mark_changeset_in_progress(
                changeset_id, beads_root=beads_root, repo_root=repo_root
            )
        git_path = config.resolve_git_path(project_config)
        worktrees.ensure_git_worktree(
            project_data_dir,
            repo_root,
            selected_epic,
            root_branch=root_branch_value,
            git_path=git_path,
        )
        branch, mapping = worktrees.ensure_changeset_branch(
            project_data_dir,
            selected_epic,
            changeset_id,
            root_branch=root_branch_value,
        )
        beads.update_worktree_path(
            selected_epic,
            mapping.worktree_path,
            beads_root=beads_root,
            cwd=repo_root,
        )
        worktree_path = project_data_dir / mapping.worktree_path
        worktrees.ensure_changeset_checkout(
            worktree_path,
            branch,
            root_branch=root_branch_value,
            git_path=git_path,
        )
        if changeset_id:
            root_base = git.git_rev_parse(
                worktree_path, root_branch_value, git_path=git_path
            )
            parent_base = git.git_rev_parse(
                worktree_path, parent_branch_value, git_path=git_path
            )
            beads.update_changeset_branch_metadata(
                changeset_id,
                root_branch=root_branch_value,
                parent_branch=parent_branch_value,
                work_branch=branch,
                root_base=root_base,
                parent_base=parent_base,
                beads_root=beads_root,
                cwd=repo_root,
            )
        say(f"Worktree: {worktree_path}")
        say(f"Changeset branch: {branch}")

        agent_spec = agents.get_agent(project_config.agent.default)
        if agent_spec is None:
            die(f"unsupported agent {project_config.agent.default!r}")
        agent_options = list(project_config.agent.options.get(agent_spec.name, []))
        project_enlistment = project_config.project.enlistment or _enlistment
        worker_agents_path = worktree_path / "AGENTS.md"
        paths.ensure_dir(worker_agents_path.parent)
        worker_template = templates.worker_template(prefer_installed_if_modified=True)
        worker_agents_path.write_text(
            prompting.render_template(
                worker_template,
                {
                    "agent_id": agent.agent_id,
                    "project_root": str(project_enlistment),
                    "project_data_dir": str(project_data_dir),
                    "beads_dir": str(beads_root),
                    "beads_prefix": "at",
                    "worker_worktree": str(worktree_path),
                },
            ),
            encoding="utf-8",
        )
        env = workspace.workspace_environment(
            project_enlistment,
            root_branch_value,
            worktree_path,
            base_env=agents.agent_environment(agent.agent_id),
        )
        env["ATELIER_EPIC_ID"] = selected_epic
        if changeset_id:
            env["ATELIER_CHANGESET_ID"] = str(changeset_id)
        opening_prompt = ""
        if agent_spec.name == "codex":
            opening_prompt = workspace.workspace_session_identifier(
                project_enlistment, root_branch_value, changeset_id or None
            )
        hook_path = hooks.ensure_agent_hooks(agent, agent_spec)
        hooks.ensure_hooks_path(env, hook_path)
        say(f"Starting {agent_spec.display_name} session")
        start_cmd, start_cwd = agent_spec.build_start_command(
            worktree_path, agent_options, opening_prompt
        )
        started_at = dt.datetime.now(tz=dt.timezone.utc)
        if agent_spec.name == "codex":
            result = codex.run_codex_command(start_cmd, cwd=start_cwd, env=env)
            if result is None:
                _mark_changeset_blocked(
                    changeset_id,
                    beads_root=beads_root,
                    repo_root=repo_root,
                    reason=f"missing required command: {start_cmd[0]}",
                )
                die(f"missing required command: {start_cmd[0]}")
            if result.returncode != 0:
                _mark_changeset_blocked(
                    changeset_id,
                    beads_root=beads_root,
                    repo_root=repo_root,
                    reason=f"command failed: {' '.join(start_cmd)}",
                )
                die(f"command failed: {' '.join(start_cmd)}")
        else:
            result = exec.run_command_status(start_cmd, cwd=start_cwd, env=env)
            if result is None:
                _mark_changeset_blocked(
                    changeset_id,
                    beads_root=beads_root,
                    repo_root=repo_root,
                    reason=f"missing required command: {start_cmd[0]}",
                )
                die(f"missing required command: {start_cmd[0]}")
            if result.returncode != 0:
                _mark_changeset_blocked(
                    changeset_id,
                    beads_root=beads_root,
                    repo_root=repo_root,
                    reason=f"command failed: {' '.join(start_cmd)}",
                )
                die(f"command failed: {' '.join(start_cmd)}")
        _finalize_changeset(
            changeset_id=changeset_id,
            epic_id=selected_epic,
            agent_bead_id=agent_bead_id,
            started_at=started_at,
            beads_root=beads_root,
            repo_root=repo_root,
        )
        return True


def start_worker(args: object) -> None:
    """Start worker sessions based on the configured run mode."""
    mode = _normalize_mode(getattr(args, "mode", None))
    run_mode = _normalize_run_mode(getattr(args, "run_mode", None))
    if bool(getattr(args, "queue", False)):
        _run_worker_once(args, mode=mode)
        return

    while True:
        started = _run_worker_once(args, mode=mode)
        if run_mode == "once":
            return
        if started:
            continue
        if run_mode == "watch":
            interval = _watch_interval_seconds()
            say(f"No ready work; watching for updates (sleeping {interval}s).")
            time.sleep(interval)
            continue
        return

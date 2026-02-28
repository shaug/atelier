"""Implementation for the ``atelier plan`` command."""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from .. import (
    agent_home,
    agents,
    beads,
    codex,
    config,
    exec,
    external_registry,
    git,
    hooks,
    paths,
    planner_sync,
    policy,
    prompting,
    sessions,
    skills,
    templates,
    workspace,
    worktrees,
)
from ..io import confirm, die, say
from . import work as work_cmd
from .resolve import resolve_current_project_with_repo_root


def _issue_sort_key(issue: dict[str, object]) -> tuple[str, str]:
    issue_id = str(issue.get("id") or "").strip()
    title = str(issue.get("title") or "").strip()
    return (issue_id, title)


_PLANNER_SESSION_ID_FIELD = "planner_session.id"

_PlannerSessionMode = Literal["resume", "fresh"]


@dataclass(frozen=True)
class _PlannerSessionSelection:
    mode: _PlannerSessionMode
    session_id: str | None
    reason: str
    clear_saved_pointer: bool = False


def _clean_session_id(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned or cleaned.lower() == "null":
        return None
    return cleaned


def _saved_planner_session_id(agent_bead: dict[str, object]) -> str | None:
    description = agent_bead.get("description")
    text = description if isinstance(description, str) else ""
    fields = beads.parse_description_fields(text)
    return _clean_session_id(fields.get(_PLANNER_SESSION_ID_FIELD))


def _select_planner_session(
    *,
    agent_spec: agents.AgentSpec,
    project_enlistment: str,
    planner_branch: str,
    planner_workspace_uid: str | None,
    saved_session_id: str | None,
    new_session: bool,
) -> _PlannerSessionSelection:
    if new_session:
        return _PlannerSessionSelection(
            mode="fresh",
            session_id=None,
            reason="--new-session requested",
        )
    if agent_spec.name != "codex" or agent_spec.resume_subcommand is None:
        return _PlannerSessionSelection(
            mode="fresh",
            session_id=None,
            reason=f"{agent_spec.display_name} resume is unavailable for planner sessions",
        )
    matches = sessions.find_codex_sessions(
        project_enlistment,
        planner_branch,
        planner_workspace_uid,
    )
    if saved_session_id:
        if any(item.session_id == saved_session_id for item in matches):
            return _PlannerSessionSelection(
                mode="resume",
                session_id=saved_session_id,
                reason="saved planner session id",
            )
        return _PlannerSessionSelection(
            mode="fresh",
            session_id=None,
            reason=f"saved planner session {saved_session_id} is stale or missing",
            clear_saved_pointer=True,
        )
    if matches:
        return _PlannerSessionSelection(
            mode="resume",
            session_id=matches[0].session_id,
            reason="most recent matching planner session",
        )
    return _PlannerSessionSelection(
        mode="fresh",
        session_id=None,
        reason="no matching planner session found",
    )


def _planner_session_mode_line(selection: _PlannerSessionSelection) -> str:
    if selection.mode == "resume" and selection.session_id:
        return f"Planner session mode: resume {selection.session_id} ({selection.reason})."
    return f"Planner session mode: start new ({selection.reason})."


def _list_inbox_messages(
    agent_id: str,
    *,
    beads_root: Path,
    repo_root: Path,
) -> None:
    inbox = beads.list_inbox_messages(
        agent_id, beads_root=beads_root, cwd=repo_root, unread_only=True
    )
    if inbox:
        say("Unread messages:")
        for issue in sorted(inbox, key=_issue_sort_key):
            issue_id = issue.get("id") or ""
            title = issue.get("title") or ""
            say(f"- {issue_id} {title}")
        return
    say("No unread messages.")


def _list_queue_messages(*, beads_root: Path, repo_root: Path) -> None:
    queued = beads.list_queue_messages(beads_root=beads_root, cwd=repo_root, unread_only=True)
    if queued:
        say("Queued messages:")
        for issue in sorted(queued, key=_issue_sort_key):
            issue_id = issue.get("id") or ""
            queue_name = issue.get("queue") or "queue"
            title = issue.get("title") or ""
            say(f"- {issue_id} [{queue_name}] {title}")
        return
    say("No queued messages.")


_PLANNER_HOOKS_DIR = "planner-git-hooks"
_PLANNER_PRECOMMIT = """#!/bin/sh
echo "Planner worktree is read-only. Do not commit from this workspace." >&2
exit 1
"""


def _planner_hooks_dir(agent_home_path: Path) -> Path:
    return agent_home_path / _PLANNER_HOOKS_DIR


def _install_planner_commit_blocker(
    worktree_path: Path, hooks_dir: Path, *, git_path: str | None
) -> None:
    paths.ensure_dir(hooks_dir)
    hook_path = hooks_dir / "pre-commit"
    hook_path.write_text(_PLANNER_PRECOMMIT, encoding="utf-8")
    hook_path.chmod(0o755)
    # Enable per-worktree config so hooksPath scopes to this worktree only.
    exec.run_command(
        git.git_command(
            [
                "-C",
                str(worktree_path),
                "config",
                "extensions.worktreeConfig",
                "true",
            ],
            git_path=git_path,
        )
    )
    legacy_hooks = exec.try_run_command(
        git.git_command(
            [
                "-C",
                str(worktree_path),
                "config",
                "--local",
                "--get",
                "core.hooksPath",
            ],
            git_path=git_path,
        )
    )
    if legacy_hooks is None:
        die("missing required command: git")
    if legacy_hooks.returncode == 0 and legacy_hooks.stdout.strip() == str(hooks_dir):
        exec.run_command(
            git.git_command(
                [
                    "-C",
                    str(worktree_path),
                    "config",
                    "--local",
                    "--unset",
                    "core.hooksPath",
                ],
                git_path=git_path,
            )
        )
    exec.run_command(
        git.git_command(
            [
                "-C",
                str(worktree_path),
                "config",
                "--worktree",
                "core.hooksPath",
                str(hooks_dir),
            ],
            git_path=git_path,
        )
    )


def _warn_planner_dirty(worktree_path: Path, *, git_path: str | None) -> None:
    status = git.git_status_porcelain(worktree_path, git_path=git_path)
    if not status:
        return
    say("Planner worktree has uncommitted changes. Keep this workspace read-only.")
    for line in status[:5]:
        say(f"- {line}")


def _ensure_planner_read_only_guardrails(
    worktree_path: Path, hooks_dir: Path, *, git_path: str | None
) -> None:
    if not (worktree_path / ".git").exists():
        return
    _install_planner_commit_blocker(worktree_path, hooks_dir, git_path=git_path)
    _warn_planner_dirty(worktree_path, git_path=git_path)


def _trace_enabled(trace_flag: object) -> bool:
    return bool(trace_flag)


def _planner_branch_name(*, default_branch: str, agent_name: str) -> str:
    token = "".join(ch.lower() if ch.isalnum() else "-" for ch in agent_name.strip() or "planner")
    token = "-".join(part for part in token.split("-") if part)
    if not token:
        token = "planner"
    return f"{default_branch}-planner-{token}"


def _planner_worktree_path(
    project_data_dir: Path, planner_key: str
) -> tuple[worktrees.WorktreeMapping | None, Path]:
    mapping = worktrees.load_mapping(worktrees.mapping_path(project_data_dir, planner_key))
    if mapping is None:
        return None, worktrees.worktree_dir(project_data_dir, planner_key)
    mapped = Path(mapping.worktree_path)
    if not mapped.is_absolute():
        mapped = project_data_dir / mapped
    return mapping, mapped


def _is_worktree_clean(path: Path, *, git_path: str | None) -> bool:
    return not git.git_status_porcelain(path, git_path=git_path)


def _resolve_default_sync_ref(
    path: Path, default_branch: str, *, git_path: str | None
) -> str | None:
    remote_ref = f"refs/remotes/origin/{default_branch}"
    if git.git_ref_exists(path, remote_ref, git_path=git_path):
        return f"origin/{default_branch}"
    local_ref = f"refs/heads/{default_branch}"
    if git.git_ref_exists(path, local_ref, git_path=git_path):
        return default_branch
    return None


def _maybe_migrate_planner_mapping(
    *,
    project_data_dir: Path,
    planner_key: str,
    planner_branch: str,
    default_branch: str,
    git_path: str | None,
) -> None:
    mapping, mapped_path = _planner_worktree_path(project_data_dir, planner_key)
    if mapping is None or mapping.root_branch == planner_branch:
        return
    if mapped_path.exists() and (mapped_path / ".git").exists():
        if not _is_worktree_clean(mapped_path, git_path=git_path):
            say(f"Planner worktree has local changes: {mapped_path}")
            status = git.git_status_porcelain(mapped_path, git_path=git_path)
            if status:
                say("Local changes:")
                for line in status[:20]:
                    say(f"- {line}")
                if len(status) > 20:
                    say(f"- ... ({len(status) - 20} more)")
            proceed = confirm(
                f"Discard local planner worktree changes and migrate to {planner_branch!r}?",
                default=False,
            )
            if not proceed:
                die("planner branch migration cancelled by user")
        fetch_result = exec.try_run_command(
            git.git_command(
                ["-C", str(mapped_path), "fetch", "origin", default_branch],
                git_path=git_path,
            )
        )
        if fetch_result is None:
            die("missing required command: git")
        sync_ref = _resolve_default_sync_ref(mapped_path, default_branch, git_path=git_path)
        if sync_ref is None:
            die(f"default branch {default_branch!r} not found for planner migration")
        exec.run_command(
            git.git_command(
                [
                    "-C",
                    str(mapped_path),
                    "checkout",
                    "-B",
                    planner_branch,
                    sync_ref,
                ],
                git_path=git_path,
            )
        )
    updated = worktrees.WorktreeMapping(
        epic_id=mapping.epic_id,
        worktree_path=mapping.worktree_path,
        root_branch=planner_branch,
        changesets=mapping.changesets,
        changeset_worktrees=mapping.changeset_worktrees,
    )
    worktrees.write_mapping(worktrees.mapping_path(project_data_dir, planner_key), updated)


class _StepFinish(Protocol):
    def __call__(self, extra: str | None = None) -> None: ...


def _step(label: str, *, timings: list[tuple[str, float]], trace: bool) -> _StepFinish:
    say(f"-> {label}")
    start = time.perf_counter()

    def finish(extra: str | None = None) -> None:
        elapsed = time.perf_counter() - start
        timings.append((label, elapsed))
        suffix = f" ({elapsed:.2f}s)" if trace or elapsed >= 0.5 else ""
        if extra:
            say(f"ok {label}{suffix}: {extra}")
        else:
            say(f"ok {label}{suffix}")

    return finish


def _report_timings(timings: list[tuple[str, float]], *, trace: bool) -> None:
    if not timings:
        return
    slow = [(label, elapsed) for label, elapsed in timings if elapsed >= 0.5]
    if not trace and not slow:
        return
    say("Timing summary:")
    for label, elapsed in sorted(timings, key=lambda item: item[1], reverse=True):
        if not trace and elapsed < 0.5:
            continue
        say(f"- {label}: {elapsed:.2f}s")


def run_planner(args: object) -> None:
    """Start a planning session for Beads epics and changesets."""
    timings: list[tuple[str, float]] = []
    trace = _trace_enabled(getattr(args, "trace", False))
    new_session_requested = bool(getattr(args, "new_session", False))
    project_root, project_config, _enlistment, repo_root = resolve_current_project_with_repo_root()
    project_data_dir = config.resolve_project_data_dir(project_root, project_config)
    beads_root = config.resolve_beads_root(project_data_dir, repo_root)
    project_enlistment = project_config.project.enlistment or _enlistment
    session_key = agent_home.generate_session_key()
    agent = agent_home.resolve_agent_home(
        project_data_dir,
        project_config,
        role="planner",
        session_key=session_key,
    )

    try:
        with agents.scoped_agent_env(agent.agent_id):
            say("Planner session")
            finish = _step("Prime beads", timings=timings, trace=trace)
            beads.run_bd_command(["prime"], beads_root=beads_root, cwd=repo_root)
            finish()
            finish = _step("Ensure planner agent bead", timings=timings, trace=trace)
            agent_bead = beads.ensure_agent_bead(
                agent.agent_id, beads_root=beads_root, cwd=repo_root, role="planner"
            )
            agent_bead_id = str(agent_bead.get("id") or "").strip()
            if not agent_bead_id:
                die("failed to determine planner agent bead id")
            saved_planner_session_id = _saved_planner_session_id(agent_bead)
            finish()
            if bool(getattr(args, "reconcile", False)):
                finish = _step("Reconcile blocked changesets", timings=timings, trace=trace)
                reconcile_result = work_cmd.reconcile_blocked_merged_changesets(
                    agent_id=agent.agent_id,
                    agent_bead_id=agent_bead_id,
                    project_config=project_config,
                    project_data_dir=project_data_dir,
                    beads_root=beads_root,
                    repo_root=repo_root,
                    git_path=config.resolve_git_path(project_config),
                    log=say,
                )
                finish(
                    extra=(
                        f"scanned={reconcile_result.scanned}, "
                        f"actionable={reconcile_result.actionable}, "
                        f"reconciled={reconcile_result.reconciled}, "
                        f"failed={reconcile_result.failed}"
                    )
                )
            finish = _step("Check inbox", timings=timings, trace=trace)
            _list_inbox_messages(agent.agent_id, beads_root=beads_root, repo_root=repo_root)
            finish()
            finish = _step("Check queue", timings=timings, trace=trace)
            _list_queue_messages(beads_root=beads_root, repo_root=repo_root)
            finish()
            git_path = config.resolve_git_path(project_config)
            finish = _step("Resolve default branch", timings=timings, trace=trace)
            default_branch = git.git_default_branch(repo_root, git_path=git_path)
            if not default_branch:
                die("failed to determine default branch for planner worktree")
            finish(f"default branch {default_branch}")
            external_providers = "none"
            provider_resolution = external_registry.PlannerProviderResolution(
                selected_provider=None,
                available_providers=tuple(),
                github_repo=None,
            )
            external_auto_export_guidance = (
                "Auto-export for new epics/changesets is disabled; "
                "import/export only when explicitly requested."
            )
            planner_key = f"planner-{agent.name}"
            planner_branch = _planner_branch_name(
                default_branch=default_branch, agent_name=agent.name
            )
            finish = _step("Prepare planner branch", timings=timings, trace=trace)
            _maybe_migrate_planner_mapping(
                project_data_dir=project_data_dir,
                planner_key=planner_key,
                planner_branch=planner_branch,
                default_branch=default_branch,
                git_path=git_path,
            )
            finish(planner_branch)
            finish = _step("Ensure planner worktree", timings=timings, trace=trace)
            worktree_path = worktrees.ensure_git_worktree(
                project_data_dir,
                repo_root,
                planner_key,
                root_branch=planner_branch,
                git_path=git_path,
            )
            finish(str(worktree_path))
            sync_service = planner_sync.PlannerSyncService(
                planner_sync.PlannerSyncContext(
                    agent_id=agent.agent_id,
                    agent_bead_id=agent_bead_id,
                    project_data_dir=project_data_dir,
                    repo_root=repo_root,
                    beads_root=beads_root,
                    worktree_path=worktree_path,
                    planner_branch=planner_branch,
                    default_branch=default_branch,
                    git_path=git_path,
                ),
                emit=say,
            )
            finish = _step("Sync planner worktree", timings=timings, trace=trace)
            startup_sync = sync_service.sync_startup()
            sync_detail = startup_sync.result or "skipped"
            if startup_sync.synced_sha:
                sync_detail = f"{sync_detail} ({startup_sync.synced_sha[:12]})"
            finish(sync_detail)
            skills_dir: Path | None = None
            if project_data_dir.exists():
                try:
                    finish = _step("Ensure skills", timings=timings, trace=trace)
                    sync_result = skills.sync_project_skills(
                        project_data_dir,
                        upgrade_policy=config.resolve_upgrade_policy(
                            project_config.atelier.upgrade
                        ),
                        yes=bool(getattr(args, "yes", False)),
                        interactive=(
                            sys.stdin.isatty()
                            and sys.stdout.isatty()
                            and not bool(getattr(args, "yes", False))
                        ),
                        prompt_update=lambda message: confirm(message, default=False),
                    )
                    skills_dir = sync_result.skills_dir
                    if sync_result.action in {"installed", "updated"}:
                        finish(f"{sync_result.action}: {skills_dir}")
                    else:
                        finish(str(skills_dir))
                except OSError:
                    skills_dir = None
            if skills_dir is not None:
                finish = _step("Link agent home", timings=timings, trace=trace)
                project_lookup_paths, _global_lookup_paths = agents.skill_lookup_paths(
                    project_config.agent.default
                )
                agent_home.ensure_agent_links(
                    agent,
                    worktree_path=worktree_path,
                    beads_root=beads_root,
                    skills_dir=skills_dir,
                    project_skill_lookup_paths=project_lookup_paths,
                )
                finish()
            finish = _step("Resolve external provider", timings=timings, trace=trace)
            provider_resolution = external_registry.resolve_planner_provider(
                project_config,
                repo_root,
                agent_name=project_config.agent.default,
                project_data_dir=project_data_dir,
                agent_home=agent.path,
                interactive=False,
            )
            provider_slugs = list(provider_resolution.available_providers)
            external_providers = ", ".join(provider_slugs) if provider_slugs else "none"
            selected_provider = provider_resolution.selected_provider
            if bool(project_config.project.auto_export_new) and selected_provider:
                external_auto_export_guidance = (
                    f"Auto-export new epics/changesets by default to "
                    f"{selected_provider}; use per-bead opt-out "
                    f"(`ext:no-export`) to skip."
                )
            finish(selected_provider or "none")
            hooks_dir = _planner_hooks_dir(agent.path)
            finish = _step("Install read-only guardrails", timings=timings, trace=trace)
            _ensure_planner_read_only_guardrails(worktree_path, hooks_dir, git_path=git_path)
            finish()
            planner_agents_path = agent.path / "AGENTS.md"
            planner_template = templates.planner_template(prefer_installed_if_modified=True)
            finish = _step("Render planner AGENTS.md", timings=timings, trace=trace)
            planner_content = prompting.render_template(
                planner_template,
                {
                    "agent_id": agent.agent_id,
                    "project_root": str(project_enlistment),
                    "repo_root": str(repo_root),
                    "project_data_dir": str(project_data_dir),
                    "beads_dir": str(beads_root),
                    "beads_prefix": "at",
                    "planner_worktree": str(worktree_path),
                    "planner_branch": planner_branch,
                    "default_branch": default_branch,
                    "external_providers": external_providers,
                    "external_auto_export_guidance": external_auto_export_guidance,
                },
            )
            finish()
            if agent.path.exists():
                paths.ensure_dir(planner_agents_path.parent)
                finish = _step("Write planner AGENTS.md", timings=timings, trace=trace)
                planner_agents_path.write_text(planner_content, encoding="utf-8")
                finish(str(planner_agents_path))
                finish = _step("Sync policy", timings=timings, trace=trace)
                policy.sync_agent_home_policy(
                    agent,
                    role=policy.ROLE_PLANNER,
                    beads_root=beads_root,
                    cwd=repo_root,
                )
                finish()
                finish = _step("Sync Beads addendum", timings=timings, trace=trace)
                prime_addendum = beads.prime_addendum(beads_root=beads_root, cwd=project_data_dir)
                updated_content = planner_agents_path.read_text(encoding="utf-8")
                next_content = agent_home.apply_beads_prime_addendum(
                    updated_content, prime_addendum
                )
                if next_content != updated_content:
                    planner_agents_path.write_text(next_content, encoding="utf-8")
                finish()
                updated_content = planner_agents_path.read_text(encoding="utf-8")
                agent_home.ensure_claude_compat(agent.path, updated_content)
            env = workspace.workspace_environment(
                project_enlistment,
                planner_branch,
                worktree_path,
                base_env=agents.agent_environment(agent.agent_id),
            )
            env.update(
                external_registry.planner_provider_environment(
                    project_config,
                    repo_root,
                    selected_provider=provider_resolution.selected_provider,
                    available_providers=provider_resolution.available_providers,
                    github_repo=provider_resolution.github_repo,
                )
            )
            env.update(
                planner_sync.runtime_environment(
                    agent_bead_id=agent_bead_id,
                    worktree_path=worktree_path,
                    planner_branch=planner_branch,
                    default_branch=default_branch,
                )
            )
            epic_id = getattr(args, "epic_id", None)
            if epic_id:
                env["ATELIER_PLAN_EPIC"] = str(epic_id)

            agent_spec = agents.get_agent(project_config.agent.default)
            if agent_spec is None:
                die(f"unsupported agent {project_config.agent.default!r}")
            agent_options = list(project_config.agent.options.get(agent_spec.name, []))
            hook_path = hooks.ensure_agent_hooks(agent, agent_spec)
            hooks.ensure_hooks_path(env, hook_path)
            sync_monitor = planner_sync.PlannerSyncMonitor(sync_service)
            finish = _step("Start planner sync monitor", timings=timings, trace=trace)
            sync_monitor.start()
            finish(f"every {sync_service.settings.interval_seconds}s")
            _report_timings(timings, trace=trace)
            planner_workspace_uid: str | None = None
            opening_prompt = ""
            if agent_spec.name == "codex":
                planner_workspace_uid = f"planner-{agent.name}"
                opening_prompt = workspace.workspace_session_identifier(
                    project_enlistment,
                    planner_branch,
                    planner_workspace_uid,
                )
            try:
                say(f"Starting {agent_spec.display_name} session")
                start_cmd, start_cwd = agent_spec.build_start_command(
                    agent.path, agent_options, opening_prompt
                )
                selection = _select_planner_session(
                    agent_spec=agent_spec,
                    project_enlistment=project_enlistment,
                    planner_branch=planner_branch,
                    planner_workspace_uid=planner_workspace_uid,
                    saved_session_id=saved_planner_session_id,
                    new_session=new_session_requested,
                )
                say(_planner_session_mode_line(selection))
                if selection.clear_saved_pointer and saved_planner_session_id:
                    beads.update_issue_description_fields(
                        agent_bead_id,
                        {_PLANNER_SESSION_ID_FIELD: None},
                        beads_root=beads_root,
                        cwd=repo_root,
                    )
                launch_cmd, launch_cwd = start_cmd, start_cwd
                if selection.mode == "resume" and selection.session_id:
                    resume = agent_spec.build_resume_command(
                        agent.path,
                        agent_options,
                        selection.session_id,
                    )
                    if resume is not None:
                        launch_cmd, launch_cwd = resume
                    else:
                        say(
                            "Planner session mode: start new "
                            "(resume command unavailable for this agent)."
                        )
                if agent_spec.name == "codex":
                    result = codex.run_codex_command(launch_cmd, cwd=launch_cwd, env=env)
                    if result is None:
                        die(f"missing required command: {launch_cmd[0]}")
                    if result.returncode != 0:
                        die(f"command failed: {' '.join(launch_cmd)}")
                    active_session_id = _clean_session_id(result.session_id)
                    if active_session_id is None and selection.mode == "resume":
                        active_session_id = selection.session_id
                    if active_session_id:
                        say(f"Planner session id: {active_session_id}")
                        if active_session_id != saved_planner_session_id:
                            beads.update_issue_description_fields(
                                agent_bead_id,
                                {_PLANNER_SESSION_ID_FIELD: active_session_id},
                                beads_root=beads_root,
                                cwd=repo_root,
                            )
                    else:
                        say("Planner session id: unavailable.")
                else:
                    exec.run_command(launch_cmd, cwd=launch_cwd, env=env)
            finally:
                sync_monitor.stop()
    finally:
        agent_home.cleanup_agent_home(agent, project_dir=project_data_dir)

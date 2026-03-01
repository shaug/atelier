"""Worker session agent preparation and execution helpers."""

from __future__ import annotations

import datetime as dt
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ... import (
    agent_home,
    agents,
    beads,
    codex,
    config,
    exec,
    hooks,
    paths,
    policy,
    prompting,
    skills,
    templates,
    workspace,
)


@dataclass(frozen=True)
class AgentSessionPreparation:
    agent_spec: agents.AgentSpec
    agent_options: list[str]
    project_enlistment: Path
    workspace_branch: str
    env: dict[str, str]


@dataclass(frozen=True)
class AgentSessionRunResult:
    started_at: dt.datetime
    returncode: int
    start_cmd: list[str]
    start_cwd: Path


class AgentSessionControl(Protocol):
    """Worker control hooks required by agent session helpers."""

    def confirm(self, prompt: str, *, default: bool = False) -> bool: ...

    def dry_run_log(self, message: str) -> None: ...

    def die(self, message: str) -> None: ...

    def say(self, message: str) -> None: ...


class AgentSessionCommandOps(Protocol):
    """Command rewriting hooks used by agent session launch."""

    def strip_flag_with_value(self, args: list[str], flag: str) -> list[str]: ...

    def with_codex_exec(self, cmd: list[str], prompt: str) -> list[str]: ...

    def ensure_exec_subcommand_flag(self, args: list[str], flag: str) -> list[str]: ...


class AgentSessionBlockedHandler(Protocol):
    """Changeset-state hooks used when session startup fails."""

    def mark_changeset_blocked(self, reason: str) -> None: ...


def prepare_agent_session(
    *,
    project_config: config.ProjectConfig,
    project_data_dir: Path,
    repo_root: Path,
    beads_root: Path,
    agent: agent_home.AgentHome,
    changeset_worktree_path: Path | None,
    selected_epic: str,
    changeset_id: str,
    root_branch_value: str,
    enlistment_path: Path,
    yes: bool,
    dry_run: bool,
    session_control: AgentSessionControl,
    command_ops: AgentSessionCommandOps,
) -> AgentSessionPreparation:
    """Prepare agent home, AGENTS template, and runtime env."""
    agent_spec = agents.get_agent(project_config.agent.default)
    if agent_spec is None:
        raise RuntimeError(f"unsupported agent {project_config.agent.default!r}")
    agent_options = list(project_config.agent.options.get(agent_spec.name, []))
    if agent_spec.name == "codex":
        agent_options = command_ops.strip_flag_with_value(agent_options, "--cd")

    project_enlistment_raw = project_config.project.enlistment or str(enlistment_path)
    project_enlistment = Path(project_enlistment_raw)
    workspace_branch = root_branch_value or ""
    if dry_run:
        worker_agents_path = (
            agent.path / "AGENTS.md" if changeset_worktree_path is not None else None
        )
        if worker_agents_path is not None:
            session_control.dry_run_log(f"Would write worker AGENTS.md to {worker_agents_path}")
            session_control.dry_run_log("Would sync Beads addendum into worker AGENTS.md.")
        if project_data_dir.exists():
            try:
                sync_result = skills.sync_project_skills(
                    project_data_dir,
                    upgrade_policy=config.resolve_upgrade_policy(project_config.atelier.upgrade),
                    yes=yes,
                    interactive=False,
                    dry_run=True,
                )
                session_control.dry_run_log(
                    f"Managed skills: {sync_result.action}"
                    + (f" ({sync_result.detail})" if sync_result.detail else "")
                )
            except OSError:
                pass
        session_control.dry_run_log("Would prepare workspace environment variables.")
    else:
        skills_dir: Path | None = None
        if project_data_dir.exists():
            try:
                sync_result = skills.sync_project_skills(
                    project_data_dir,
                    upgrade_policy=config.resolve_upgrade_policy(project_config.atelier.upgrade),
                    yes=yes,
                    interactive=(sys.stdin.isatty() and sys.stdout.isatty() and not yes),
                    prompt_update=lambda message: session_control.confirm(message, default=False),
                )
                skills_dir = sync_result.skills_dir
                if sync_result.action in {"installed", "updated", "up_to_date"}:
                    session_control.say(f"Managed skills: {sync_result.action}")
            except OSError:
                skills_dir = None
        if skills_dir is not None:
            project_lookup_paths, _global_lookup_paths = agents.skill_lookup_paths(agent_spec.name)
            if changeset_worktree_path is None:
                raise RuntimeError("missing changeset worktree path for agent link setup")
            agent_home.ensure_agent_links(
                agent,
                worktree_path=changeset_worktree_path,
                beads_root=beads_root,
                skills_dir=skills_dir,
                project_skill_lookup_paths=project_lookup_paths,
            )
        worker_agents_path = agent.path / "AGENTS.md"
        try:
            worker_template_result = templates.read_template_result(
                "AGENTS.worker.md.tmpl",
                prefer_installed_if_modified=True,
            )
        except templates.TemplateReadError as exc:
            fallback_attempts = " | ".join(exc.attempts) if exc.attempts else "no attempts recorded"
            raise RuntimeError(
                "worker_template_load_failed: "
                f"epic={selected_epic}; "
                f"worktree={changeset_worktree_path}; "
                f"template={exc.template}; "
                f"fallback_attempts={fallback_attempts}"
            ) from exc
        if worker_template_result.source != "packaged_default" or any(
            "unreadable" in attempt for attempt in worker_template_result.attempts
        ):
            session_control.say(
                "Worker template diagnostics: "
                f"epic={selected_epic}, "
                f"worktree={changeset_worktree_path}, "
                f"source={worker_template_result.source}, "
                f"attempts={' | '.join(worker_template_result.attempts)}"
            )
        worker_template = worker_template_result.text
        worker_content = prompting.render_template(
            worker_template,
            {
                "agent_id": agent.agent_id,
                "project_root": str(project_enlistment),
                "project_data_dir": str(project_data_dir),
                "beads_dir": str(beads_root),
                "beads_prefix": "at",
                "worker_worktree": str(changeset_worktree_path),
            },
        )
        if agent.path.exists():
            paths.ensure_dir(worker_agents_path.parent)
            worker_agents_path.write_text(worker_content, encoding="utf-8")
            policy.sync_agent_home_policy(
                agent,
                role=policy.ROLE_WORKER,
                beads_root=beads_root,
                cwd=repo_root,
            )
            prime_addendum = beads.prime_addendum(beads_root=beads_root, cwd=project_data_dir)
            updated_content = worker_agents_path.read_text(encoding="utf-8")
            next_content = agent_home.apply_beads_prime_addendum(
                updated_content,
                prime_addendum,
                role=policy.ROLE_WORKER,
            )
            if next_content != updated_content:
                worker_agents_path.write_text(next_content, encoding="utf-8")
            updated_content = worker_agents_path.read_text(encoding="utf-8")
            agent_home.ensure_claude_compat(agent.path, updated_content)

    env_workspace_path = changeset_worktree_path or (project_data_dir / "worktrees" / "unknown")
    env = workspace.workspace_environment(
        str(project_enlistment),
        workspace_branch,
        env_workspace_path,
        base_env=agents.agent_environment(agent.agent_id),
    )
    env["ATELIER_EPIC_ID"] = selected_epic
    if changeset_id:
        env["ATELIER_CHANGESET_ID"] = str(changeset_id)
    env["BEADS_DIR"] = str(beads_root)
    env["BEADS_DB"] = str(beads_root / "beads.db")
    return AgentSessionPreparation(
        agent_spec=agent_spec,
        agent_options=agent_options,
        project_enlistment=project_enlistment,
        workspace_branch=workspace_branch,
        env=env,
    )


def install_agent_hooks(
    *,
    dry_run: bool,
    agent: agent_home.AgentHome,
    agent_spec: agents.AgentSpec,
    env: dict[str, str],
    session_control: AgentSessionControl,
) -> None:
    """Install/attach runtime hooks for the session agent."""
    if dry_run:
        session_control.dry_run_log("Would ensure agent hooks are installed.")
        return
    hook_path = hooks.ensure_agent_hooks(agent, agent_spec)
    hooks.ensure_hooks_path(env, hook_path)


def start_agent_session(
    *,
    dry_run: bool,
    agent: agent_home.AgentHome,
    agent_spec: agents.AgentSpec,
    agent_options: list[str],
    opening_prompt: str,
    env: dict[str, str],
    command_ops: AgentSessionCommandOps,
    session_control: AgentSessionControl,
    blocked_handler: AgentSessionBlockedHandler,
) -> AgentSessionRunResult | None:
    """Run the configured agent and return runtime details."""
    start_cmd, start_cwd = agent_spec.build_start_command(
        agent.path,
        agent_options,
        opening_prompt,
    )
    if agent_spec.name == "codex":
        start_cmd = command_ops.with_codex_exec(start_cmd, opening_prompt)
        start_cmd = command_ops.strip_flag_with_value(start_cmd, "--cd")
        start_cmd = command_ops.ensure_exec_subcommand_flag(start_cmd, "--skip-git-repo-check")
        start_cwd = agent.path
    if dry_run:
        session_control.dry_run_log(f"Agent command: {' '.join(start_cmd)}")
        session_control.dry_run_log(f"Agent cwd: {start_cwd}")
        return None

    session_control.say(f"Starting {agent_spec.display_name} session")
    started_at = dt.datetime.now(tz=dt.timezone.utc)
    returncode = 0
    if agent_spec.name == "codex":
        result = codex.run_codex_command(start_cmd, cwd=start_cwd, env=env)
        if result is None:
            blocked_handler.mark_changeset_blocked(f"missing required command: {start_cmd[0]}")
            session_control.die(f"missing required command: {start_cmd[0]}")
            return None
        if result.returncode != 0:
            returncode = result.returncode
            blocked_handler.mark_changeset_blocked(f"command failed: {' '.join(start_cmd)}")
            session_control.die(f"command failed: {' '.join(start_cmd)}")
            return None
    else:
        result = exec.run_with_runner(
            exec.CommandRequest(
                argv=tuple(start_cmd),
                cwd=start_cwd,
                env=env,
                capture_output=False,
                text=False,
            )
        )
        if result is None:
            blocked_handler.mark_changeset_blocked(f"missing required command: {start_cmd[0]}")
            session_control.die(f"missing required command: {start_cmd[0]}")
            return None
        if result.returncode != 0:
            returncode = result.returncode
            blocked_handler.mark_changeset_blocked(f"command failed: {' '.join(start_cmd)}")
            session_control.die(f"command failed: {' '.join(start_cmd)}")
            return None

    effective_start_cwd = start_cwd or agent.path

    return AgentSessionRunResult(
        started_at=started_at,
        returncode=returncode,
        start_cmd=start_cmd,
        start_cwd=effective_start_cwd,
    )

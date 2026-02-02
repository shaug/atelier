"""Implementation for the ``atelier plan`` command."""

from __future__ import annotations

from .. import (
    agent_home,
    agents,
    beads,
    codex,
    config,
    exec,
    git,
    policy,
    workspace,
    worktrees,
)
from ..io import die, say
from .resolve import resolve_current_project_with_repo_root


def run_planner(args: object) -> None:
    """Start a planning session for Beads epics and changesets."""
    project_root, project_config, _enlistment, repo_root = (
        resolve_current_project_with_repo_root()
    )
    project_data_dir = config.resolve_project_data_dir(project_root, project_config)
    beads_root = config.resolve_beads_root(project_data_dir, repo_root)
    agent = agent_home.resolve_agent_home(
        project_data_dir, project_config, role="planner"
    )

    with agents.scoped_agent_env(agent.agent_id):
        say("Planner session")
        beads.run_bd_command(["prime"], beads_root=beads_root, cwd=repo_root)
        beads.ensure_agent_bead(
            agent.agent_id, beads_root=beads_root, cwd=repo_root, role="planner"
        )
        policy.sync_agent_home_policy(
            agent, role=policy.ROLE_PLANNER, beads_root=beads_root, cwd=repo_root
        )
        git_path = config.resolve_git_path(project_config)
        default_branch = git.git_default_branch(repo_root, git_path=git_path)
        if not default_branch:
            die("failed to determine default branch for planner worktree")
        planner_key = f"planner-{agent.name}"
        worktree_path = worktrees.ensure_git_worktree(
            project_data_dir,
            repo_root,
            planner_key,
            root_branch=default_branch,
            git_path=git_path,
        )
        project_enlistment = project_config.project.enlistment or _enlistment
        env = workspace.workspace_environment(
            project_enlistment,
            default_branch,
            worktree_path,
            base_env=agents.agent_environment(agent.agent_id),
        )
        epic_id = getattr(args, "epic_id", None)
        if epic_id:
            env["ATELIER_PLAN_EPIC"] = str(epic_id)

        agent_spec = agents.get_agent(project_config.agent.default)
        if agent_spec is None:
            die(f"unsupported agent {project_config.agent.default!r}")
        agent_options = list(project_config.agent.options.get(agent_spec.name, []))
        opening_prompt = ""
        if agent_spec.name == "codex":
            opening_prompt = workspace.workspace_session_identifier(
                project_enlistment,
                default_branch,
                f"planner-{agent.name}",
            )
        say(f"Starting {agent_spec.display_name} session")
        start_cmd, start_cwd = agent_spec.build_start_command(
            worktree_path, agent_options, opening_prompt
        )
        if agent_spec.name == "codex":
            result = codex.run_codex_command(start_cmd, cwd=start_cwd, env=env)
            if result is None:
                die(f"missing required command: {start_cmd[0]}")
            if result.returncode != 0:
                die(f"command failed: {' '.join(start_cmd)}")
        else:
            exec.run_command(start_cmd, cwd=start_cwd, env=env)

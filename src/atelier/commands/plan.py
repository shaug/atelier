"""Implementation for the ``atelier plan`` command."""

from __future__ import annotations

from pathlib import Path

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
    policy,
    prompting,
    skills,
    templates,
    workspace,
    worktrees,
)
from ..io import die, prompt, say
from .resolve import resolve_current_project_with_repo_root


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
        for issue in inbox:
            issue_id = issue.get("id") or ""
            title = issue.get("title") or ""
            say(f"- {issue_id} {title}")
        return
    say("No unread messages.")


def _list_queue_messages(*, beads_root: Path, repo_root: Path) -> None:
    queued = beads.list_queue_messages(beads_root=beads_root, cwd=repo_root)
    if queued:
        say("Queued messages:")
        for issue in queued:
            issue_id = issue.get("id") or ""
            queue_name = issue.get("queue") or "queue"
            title = issue.get("title") or ""
            say(f"- {issue_id} [{queue_name}] {title}")
        return
    say("No queued messages.")


def _list_draft_epics(*, beads_root: Path, repo_root: Path) -> list[dict[str, object]]:
    issues = beads.run_bd_json(
        ["list", "--label", "at:epic", "--label", "at:draft"],
        beads_root=beads_root,
        cwd=repo_root,
    )
    if not issues:
        say("No draft epics.")
        return []
    say("Draft epics:")
    for issue in issues:
        issue_id = issue.get("id") or ""
        status = issue.get("status") or "unknown"
        title = issue.get("title") or ""
        say(f"- {issue_id} [{status}] {title}")
    return issues


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
    exec.run_command(
        git.git_command(
            ["-C", str(worktree_path), "config", "core.hooksPath", str(hooks_dir)],
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


def _maybe_promote_draft_epic(
    issues: list[dict[str, object]],
    *,
    beads_root: Path,
    repo_root: Path,
) -> None:
    if not issues:
        return
    choice = prompt("Promote a draft epic to ready? (y/N)").strip().lower()
    if choice not in {"y", "yes"}:
        return
    epic_id = prompt("Draft epic id").strip()
    if not epic_id:
        die("draft epic id is required")
    valid_ids = {str(issue.get("id")) for issue in issues if issue.get("id")}
    if epic_id not in valid_ids:
        die(f"unknown draft epic id: {epic_id}")
    confirm = prompt(f"Promote {epic_id} to ready? (y/N)").strip().lower()
    if confirm not in {"y", "yes"}:
        say("Draft epic promotion cancelled.")
        return
    beads.run_bd_command(
        ["update", epic_id, "--remove-label", "at:draft", "--add-label", "at:ready"],
        beads_root=beads_root,
        cwd=repo_root,
    )
    say(f"Promoted draft epic: {epic_id}")


def run_planner(args: object) -> None:
    """Start a planning session for Beads epics and changesets."""
    project_root, project_config, _enlistment, repo_root = (
        resolve_current_project_with_repo_root()
    )
    project_data_dir = config.resolve_project_data_dir(project_root, project_config)
    beads_root = config.resolve_beads_root(project_data_dir, repo_root)
    project_enlistment = project_config.project.enlistment or _enlistment
    agent = agent_home.resolve_agent_home(
        project_data_dir, project_config, role="planner"
    )

    with agents.scoped_agent_env(agent.agent_id):
        say("Planner session")
        beads.run_bd_command(["prime"], beads_root=beads_root, cwd=repo_root)
        beads.ensure_agent_bead(
            agent.agent_id, beads_root=beads_root, cwd=repo_root, role="planner"
        )
        _list_inbox_messages(agent.agent_id, beads_root=beads_root, repo_root=repo_root)
        _list_queue_messages(beads_root=beads_root, repo_root=repo_root)
        draft_epics = _list_draft_epics(beads_root=beads_root, repo_root=repo_root)
        _maybe_promote_draft_epic(
            draft_epics, beads_root=beads_root, repo_root=repo_root
        )
        git_path = config.resolve_git_path(project_config)
        default_branch = git.git_default_branch(repo_root, git_path=git_path)
        if not default_branch:
            die("failed to determine default branch for planner worktree")
        provider_contexts = external_registry.resolve_external_providers(
            project_config, repo_root
        )
        provider_slugs = sorted(
            {context.provider.slug for context in provider_contexts if context.provider}
        )
        external_providers = ", ".join(provider_slugs) if provider_slugs else "none"
        planner_key = f"planner-{agent.name}"
        worktree_path = worktrees.ensure_git_worktree(
            project_data_dir,
            repo_root,
            planner_key,
            root_branch=default_branch,
            git_path=git_path,
        )
        skills_dir: Path | None = None
        if project_data_dir.exists():
            try:
                skills_dir = skills.ensure_project_skills(project_data_dir)
            except OSError:
                skills_dir = None
        if skills_dir is not None:
            agent_home.ensure_agent_links(
                agent,
                worktree_path=worktree_path,
                beads_root=beads_root,
                skills_dir=skills_dir,
            )
        hooks_dir = _planner_hooks_dir(agent.path)
        _ensure_planner_read_only_guardrails(
            worktree_path, hooks_dir, git_path=git_path
        )
        planner_agents_path = agent.path / "AGENTS.md"
        planner_template = templates.planner_template(prefer_installed_if_modified=True)
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
                "default_branch": default_branch,
                "external_providers": external_providers,
            },
        )
        if agent.path.exists():
            paths.ensure_dir(planner_agents_path.parent)
            planner_agents_path.write_text(planner_content, encoding="utf-8")
            policy.sync_agent_home_policy(
                agent, role=policy.ROLE_PLANNER, beads_root=beads_root, cwd=repo_root
            )
            updated_content = planner_agents_path.read_text(encoding="utf-8")
            agent_home.ensure_claude_compat(agent.path, updated_content)
        env = workspace.workspace_environment(
            project_enlistment,
            default_branch,
            worktree_path,
            base_env=agents.agent_environment(agent.agent_id),
        )
        env.update(
            external_registry.planner_provider_environment(project_config, repo_root)
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
        opening_prompt = ""
        if agent_spec.name == "codex":
            opening_prompt = workspace.workspace_session_identifier(
                project_enlistment,
                default_branch,
                f"planner-{agent.name}",
            )
        say(f"Starting {agent_spec.display_name} session")
        start_cmd, start_cwd = agent_spec.build_start_command(
            agent.path, agent_options, opening_prompt
        )
        if agent_spec.name == "codex":
            result = codex.run_codex_command(start_cmd, cwd=start_cwd, env=env)
            if result is None:
                die(f"missing required command: {start_cmd[0]}")
            if result.returncode != 0:
                die(f"command failed: {' '.join(start_cmd)}")
        else:
            exec.run_command(start_cmd, cwd=start_cwd, env=env)

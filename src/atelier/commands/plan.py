"""Implementation for the ``atelier plan`` command."""

from __future__ import annotations

import os
import time
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
    queued = beads.list_queue_messages(
        beads_root=beads_root, cwd=repo_root, unread_only=True
    )
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
    # Enable per-worktree config so hooksPath can be scoped to this worktree only.
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
    _promote_defined_changesets(epic_id, beads_root=beads_root, repo_root=repo_root)
    say(f"Promoted draft epic: {epic_id}")


def _promote_defined_changesets(
    epic_id: str, *, beads_root: Path, repo_root: Path
) -> None:
    all_changesets = beads.run_bd_json(
        ["list", "--parent", epic_id, "--label", "at:changeset"],
        beads_root=beads_root,
        cwd=repo_root,
    )
    if not all_changesets:
        say(f"No changesets found for {epic_id}.")
        return
    promoted: list[str] = []
    for issue in all_changesets:
        labels = issue.get("labels") or []
        if "cs:planned" not in labels:
            continue
        issue_id = issue.get("id")
        if not issue_id:
            continue
        beads.run_bd_command(
            [
                "update",
                str(issue_id),
                "--add-label",
                "cs:ready",
                "--remove-label",
                "cs:planned",
            ],
            beads_root=beads_root,
            cwd=repo_root,
        )
        promoted.append(str(issue_id))
    if not promoted:
        say(f"No planned changesets to promote for {epic_id}.")
        return
    say(f"Promoted changesets to ready: {', '.join(promoted)}")


def _trace_enabled() -> bool:
    return os.environ.get("ATELIER_PLAN_TRACE", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _planner_branch_name(*, default_branch: str, agent_name: str) -> str:
    token = "".join(
        ch.lower() if ch.isalnum() else "-" for ch in agent_name.strip() or "planner"
    )
    token = "-".join(part for part in token.split("-") if part)
    if not token:
        token = "planner"
    return f"{default_branch}-planner-{token}"


def _planner_worktree_path(
    project_data_dir: Path, planner_key: str
) -> tuple[worktrees.WorktreeMapping | None, Path]:
    mapping = worktrees.load_mapping(
        worktrees.mapping_path(project_data_dir, planner_key)
    )
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
            die(
                f"planner worktree has local changes: {mapped_path}; "
                "clean it before migrating planner branch"
            )
        fetch_result = exec.try_run_command(
            git.git_command(
                ["-C", str(mapped_path), "fetch", "origin", default_branch],
                git_path=git_path,
            )
        )
        if fetch_result is None:
            die("missing required command: git")
        sync_ref = _resolve_default_sync_ref(
            mapped_path, default_branch, git_path=git_path
        )
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
    worktrees.write_mapping(
        worktrees.mapping_path(project_data_dir, planner_key), updated
    )


def _sync_planner_branch(
    *,
    worktree_path: Path,
    planner_branch: str,
    default_branch: str,
    git_path: str | None,
) -> None:
    if not (worktree_path / ".git").exists():
        return
    if not _is_worktree_clean(worktree_path, git_path=git_path):
        say("Planner worktree has local changes; skipping planner branch sync.")
        return
    fetch_result = exec.try_run_command(
        git.git_command(
            ["-C", str(worktree_path), "fetch", "origin", default_branch],
            git_path=git_path,
        )
    )
    if fetch_result is None:
        die("missing required command: git")
    if fetch_result.returncode != 0:
        say(f"Warning: failed to fetch origin/{default_branch}; skipping planner sync.")
        return
    sync_ref = _resolve_default_sync_ref(
        worktree_path, default_branch, git_path=git_path
    )
    if sync_ref is None:
        say(
            f"Warning: default branch {default_branch!r} not found; skipping planner sync."
        )
        return
    exec.run_command(
        git.git_command(
            ["-C", str(worktree_path), "checkout", planner_branch],
            git_path=git_path,
        )
    )
    exec.run_command(
        git.git_command(
            ["-C", str(worktree_path), "reset", "--hard", sync_ref],
            git_path=git_path,
        )
    )


def _step(label: str, *, timings: list[tuple[str, float]], trace: bool) -> callable:
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
    trace = _trace_enabled()
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
        finish = _step("Prime beads", timings=timings, trace=trace)
        beads.run_bd_command(["prime"], beads_root=beads_root, cwd=repo_root)
        finish()
        finish = _step("Ensure planner agent bead", timings=timings, trace=trace)
        beads.ensure_agent_bead(
            agent.agent_id, beads_root=beads_root, cwd=repo_root, role="planner"
        )
        finish()
        finish = _step("Check inbox", timings=timings, trace=trace)
        _list_inbox_messages(agent.agent_id, beads_root=beads_root, repo_root=repo_root)
        finish()
        finish = _step("Check queue", timings=timings, trace=trace)
        _list_queue_messages(beads_root=beads_root, repo_root=repo_root)
        finish()
        finish = _step("List draft epics", timings=timings, trace=trace)
        draft_epics = _list_draft_epics(beads_root=beads_root, repo_root=repo_root)
        finish()
        finish = _step("Promote draft epic (optional)", timings=timings, trace=trace)
        _maybe_promote_draft_epic(
            draft_epics, beads_root=beads_root, repo_root=repo_root
        )
        finish()
        git_path = config.resolve_git_path(project_config)
        finish = _step("Resolve default branch", timings=timings, trace=trace)
        default_branch = git.git_default_branch(repo_root, git_path=git_path)
        if not default_branch:
            die("failed to determine default branch for planner worktree")
        finish(f"default branch {default_branch}")
        provider_contexts = external_registry.resolve_external_providers(
            project_config, repo_root
        )
        provider_slugs = sorted(
            {context.provider.slug for context in provider_contexts if context.provider}
        )
        external_providers = ", ".join(provider_slugs) if provider_slugs else "none"
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
        finish = _step("Sync planner worktree", timings=timings, trace=trace)
        _sync_planner_branch(
            worktree_path=worktree_path,
            planner_branch=planner_branch,
            default_branch=default_branch,
            git_path=git_path,
        )
        finish()
        skills_dir: Path | None = None
        if project_data_dir.exists():
            try:
                finish = _step("Ensure skills", timings=timings, trace=trace)
                skills_dir = skills.ensure_project_skills(project_data_dir)
                finish(str(skills_dir))
            except OSError:
                skills_dir = None
        if skills_dir is not None:
            finish = _step("Link agent home", timings=timings, trace=trace)
            agent_home.ensure_agent_links(
                agent,
                worktree_path=worktree_path,
                beads_root=beads_root,
                skills_dir=skills_dir,
            )
            finish()
        hooks_dir = _planner_hooks_dir(agent.path)
        finish = _step("Install read-only guardrails", timings=timings, trace=trace)
        _ensure_planner_read_only_guardrails(
            worktree_path, hooks_dir, git_path=git_path
        )
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
                agent, role=policy.ROLE_PLANNER, beads_root=beads_root, cwd=repo_root
            )
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
        _report_timings(timings, trace=trace)
        opening_prompt = ""
        if agent_spec.name == "codex":
            opening_prompt = workspace.workspace_session_identifier(
                project_enlistment,
                planner_branch,
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

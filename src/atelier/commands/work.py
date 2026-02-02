"""Worker session command implementation.

Starts a worker session by selecting an epic and its next ready changeset.
Used by ``atelier work``.
"""

from __future__ import annotations

import os
from pathlib import Path

from .. import agent_home, agents, beads, codex, config, exec, policy, root_branch
from .. import workspace, worktrees
from ..io import die, prompt, say
from .resolve import resolve_current_project_with_repo_root

_MODE_VALUES = {"prompt", "auto"}


def _normalize_mode(value: str | None) -> str:
    if value is None:
        value = os.environ.get("ATELIER_MODE", "prompt")
    normalized = value.strip().lower()
    if normalized not in _MODE_VALUES:
        die("mode must be one of: prompt, auto")
    return normalized


def _issue_labels(issue: dict[str, object]) -> set[str]:
    labels = issue.get("labels")
    if not isinstance(labels, list):
        return set()
    return {str(label) for label in labels if label is not None}


def _filter_epics(issues: list[dict[str, object]]) -> list[dict[str, object]]:
    filtered: list[dict[str, object]] = []
    for issue in issues:
        status = str(issue.get("status") or "")
        if status and status.lower() not in {"open"}:
            continue
        labels = _issue_labels(issue)
        if "at:draft" in labels:
            continue
        assignee = issue.get("assignee")
        if assignee:
            continue
        filtered.append(issue)
    return filtered


def _list_epics(*, beads_root: Path, repo_root: Path) -> list[dict[str, object]]:
    return beads.run_bd_json(
        ["list", "--label", "at:epic"], beads_root=beads_root, cwd=repo_root
    )


def _select_epic_prompt(issues: list[dict[str, object]]) -> str:
    epics = _filter_epics(issues)
    if not epics:
        die("no eligible epics found")
    say("Available epics:")
    for issue in epics:
        issue_id = issue.get("id") or ""
        status = issue.get("status") or "unknown"
        title = issue.get("title") or ""
        root_branch_value = beads.extract_workspace_root_branch(issue) or "unset"
        say(f"- {issue_id} [{status}] {root_branch_value} {title}")
    selection = prompt("Epic id")
    selection = selection.strip()
    if not selection:
        die("epic id is required")
    valid_ids = {str(issue.get("id")) for issue in epics if issue.get("id")}
    if selection not in valid_ids:
        die(f"unknown epic id: {selection}")
    return selection


def _select_epic_auto(*, beads_root: Path, repo_root: Path) -> str:
    ready = beads.run_bd_json(
        [
            "list",
            "--label",
            "at:epic",
            "--status",
            "open",
            "--no-assignee",
            "--limit",
            "1",
        ],
        beads_root=beads_root,
        cwd=repo_root,
    )
    ready = _filter_epics(ready)
    if ready:
        return str(ready[0].get("id"))
    die("no eligible epics found")


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
        ],
        beads_root=beads_root,
        cwd=repo_root,
    )


def start_worker(args: object) -> None:
    """Start a worker session by selecting an epic and changeset."""
    project_root, project_config, _enlistment, repo_root = (
        resolve_current_project_with_repo_root()
    )
    project_data_dir = config.resolve_project_data_dir(project_root, project_config)
    beads_root = config.resolve_beads_root(project_data_dir, repo_root)
    agent = agent_home.resolve_agent_home(
        project_data_dir, project_config, role="worker"
    )
    os.environ["ATELIER_AGENT_ID"] = agent.agent_id
    os.environ.setdefault("BD_ACTOR", agent.agent_id)
    os.environ.setdefault("BEADS_AGENT_NAME", agent.agent_id)
    agent_bead = beads.ensure_agent_bead(
        agent.agent_id, beads_root=beads_root, cwd=repo_root, role="worker"
    )
    policy.sync_agent_home_policy(
        agent, role=policy.ROLE_WORKER, beads_root=beads_root, cwd=repo_root
    )

    epic_id = getattr(args, "epic_id", None)
    mode = _normalize_mode(getattr(args, "mode", None))

    if epic_id:
        selected_epic = str(epic_id).strip()
        if not selected_epic:
            die("epic id must not be empty")
    elif mode == "auto":
        selected_epic = _select_epic_auto(beads_root=beads_root, repo_root=repo_root)
    else:
        issues = _list_epics(beads_root=beads_root, repo_root=repo_root)
        selected_epic = _select_epic_prompt(issues)

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
    agent_bead_id = agent_bead.get("id")
    if not isinstance(agent_bead_id, str) or not agent_bead_id:
        die("failed to resolve agent bead id")
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
    worktree_path = project_data_dir / mapping.worktree_path
    worktrees.ensure_changeset_checkout(
        worktree_path,
        branch,
        root_branch=root_branch_value,
        git_path=git_path,
    )
    say(f"Worktree: {worktree_path}")
    say(f"Changeset branch: {branch}")

    agent_spec = agents.get_agent(project_config.agent.default)
    if agent_spec is None:
        die(f"unsupported agent {project_config.agent.default!r}")
    agent_options = list(project_config.agent.options.get(agent_spec.name, []))
    project_enlistment = project_config.project.enlistment or _enlistment
    env = workspace.workspace_environment(
        project_enlistment,
        root_branch_value,
        worktree_path,
        base_env=agents.agent_environment(agent.agent_id),
    )
    opening_prompt = ""
    if agent_spec.name == "codex":
        opening_prompt = workspace.workspace_session_identifier(
            project_enlistment, root_branch_value, changeset_id or None
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

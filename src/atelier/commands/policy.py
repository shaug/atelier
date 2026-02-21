"""Project policy command implementation."""

from __future__ import annotations

from pathlib import Path

from .. import agent_home, beads, config, policy
from ..io import die, say, select
from .resolve import resolve_current_project_with_repo_root


def _select_policy_issue(issues: list[dict[str, object]], *, role: str) -> dict[str, object] | None:
    if not issues:
        return None
    if len(issues) == 1:
        return issues[0]
    choices: list[str] = []
    for issue in issues:
        issue_id = issue.get("id") or ""
        title = issue.get("title") or ""
        choices.append(f"{issue_id} {title}".strip())
    selection = select(f"Select {role} policy bead", choices, default=choices[0])
    selected_id = selection.split()[0] if selection else ""
    for issue in issues:
        if str(issue.get("id")) == selected_id:
            return issue
    return issues[0]


def _resolve_role_choice(role_flag: str | None, planner_body: str, worker_body: str) -> str:
    if role_flag:
        return role_flag
    planner_body = policy.normalize_policy_text(planner_body)
    worker_body = policy.normalize_policy_text(worker_body)
    if planner_body and worker_body and planner_body != worker_body:
        return select(
            "Edit policy for",
            [policy.ROLE_PLANNER, policy.ROLE_WORKER, policy.ROLE_BOTH],
        )
    return policy.ROLE_BOTH


def _apply_policy(
    role: str,
    body: str,
    *,
    issue: dict[str, object] | None,
    beads_root: Path,
    repo_root: Path,
) -> None:
    body = policy.normalize_policy_text(body)
    if issue is None:
        if not body.strip():
            return
        beads.create_policy_bead(role, body, beads_root=beads_root, cwd=repo_root)
        return
    issue_id = issue.get("id")
    if not isinstance(issue_id, str) or not issue_id:
        die("policy bead is missing an id")
    beads.update_policy_bead(issue_id, body, beads_root=beads_root, cwd=repo_root)


def edit_policy(args: object) -> None:
    """Edit project-wide policy stored in Beads."""
    project_root, project_config, _enlistment, repo_root = resolve_current_project_with_repo_root()
    project_data_dir = config.resolve_project_data_dir(project_root, project_config)
    beads_root = config.resolve_beads_root(project_data_dir, repo_root)
    role_flag = policy.normalize_role(getattr(args, "role", None))

    beads.run_bd_command(["prime"], beads_root=beads_root, cwd=repo_root)

    planner_issue = _select_policy_issue(
        beads.list_policy_beads(policy.ROLE_PLANNER, beads_root=beads_root, cwd=repo_root),
        role=policy.ROLE_PLANNER,
    )
    worker_issue = _select_policy_issue(
        beads.list_policy_beads(policy.ROLE_WORKER, beads_root=beads_root, cwd=repo_root),
        role=policy.ROLE_WORKER,
    )

    planner_body = beads.extract_policy_body(planner_issue) if planner_issue else ""
    worker_body = beads.extract_policy_body(worker_issue) if worker_issue else ""

    role_choice = _resolve_role_choice(role_flag, planner_body, worker_body)

    if role_choice == policy.ROLE_PLANNER:
        seed = planner_body or worker_body
        edited = policy.edit_policy_text(seed, project_config=project_config, cwd=repo_root)
        _apply_policy(
            policy.ROLE_PLANNER,
            edited,
            issue=planner_issue,
            beads_root=beads_root,
            repo_root=repo_root,
        )
        planner_home = agent_home.resolve_agent_home(
            project_data_dir, project_config, role=policy.ROLE_PLANNER
        )
        policy.sync_agent_home_policy(
            planner_home, role=policy.ROLE_PLANNER, beads_root=beads_root, cwd=repo_root
        )
        say("Updated planner policy")
        return

    if role_choice == policy.ROLE_WORKER:
        seed = worker_body or planner_body
        edited = policy.edit_policy_text(seed, project_config=project_config, cwd=repo_root)
        _apply_policy(
            policy.ROLE_WORKER,
            edited,
            issue=worker_issue,
            beads_root=beads_root,
            repo_root=repo_root,
        )
        worker_home = agent_home.resolve_agent_home(
            project_data_dir, project_config, role=policy.ROLE_WORKER
        )
        policy.sync_agent_home_policy(
            worker_home, role=policy.ROLE_WORKER, beads_root=beads_root, cwd=repo_root
        )
        say("Updated worker policy")
        return

    combined, split = policy.build_combined_policy(planner_body, worker_body)
    edited = policy.edit_policy_text(combined, project_config=project_config, cwd=repo_root)
    if split:
        sections = policy.split_combined_policy(edited)
        if sections:
            planner_next = sections.get(policy.ROLE_PLANNER, "")
            worker_next = sections.get(policy.ROLE_WORKER, "")
        else:
            planner_next = edited
            worker_next = edited
    else:
        planner_next = edited
        worker_next = edited

    _apply_policy(
        policy.ROLE_PLANNER,
        planner_next,
        issue=planner_issue,
        beads_root=beads_root,
        repo_root=repo_root,
    )
    _apply_policy(
        policy.ROLE_WORKER,
        worker_next,
        issue=worker_issue,
        beads_root=beads_root,
        repo_root=repo_root,
    )

    planner_home = agent_home.resolve_agent_home(
        project_data_dir, project_config, role=policy.ROLE_PLANNER
    )
    worker_home = agent_home.resolve_agent_home(
        project_data_dir, project_config, role=policy.ROLE_WORKER
    )
    policy.sync_agent_home_policy(
        planner_home, role=policy.ROLE_PLANNER, beads_root=beads_root, cwd=repo_root
    )
    policy.sync_agent_home_policy(
        worker_home, role=policy.ROLE_WORKER, beads_root=beads_root, cwd=repo_root
    )
    say("Updated project policy")


def show_policy(args: object) -> None:
    """Show project-wide policy stored in Beads."""
    project_root, project_config, _enlistment, repo_root = resolve_current_project_with_repo_root()
    project_data_dir = config.resolve_project_data_dir(project_root, project_config)
    beads_root = config.resolve_beads_root(project_data_dir, repo_root)
    role = policy.normalize_role(getattr(args, "role", None)) or policy.ROLE_BOTH

    beads.run_bd_command(["prime"], beads_root=beads_root, cwd=repo_root)

    planner_issues = beads.list_policy_beads(
        policy.ROLE_PLANNER, beads_root=beads_root, cwd=repo_root
    )
    worker_issues = beads.list_policy_beads(
        policy.ROLE_WORKER, beads_root=beads_root, cwd=repo_root
    )
    planner_body = (
        policy.normalize_policy_text(beads.extract_policy_body(planner_issues[0]))
        if planner_issues
        else ""
    )
    worker_body = (
        policy.normalize_policy_text(beads.extract_policy_body(worker_issues[0]))
        if worker_issues
        else ""
    )

    if role == policy.ROLE_PLANNER:
        if planner_body:
            say(planner_body)
        else:
            say("No planner policy set.")
        return

    if role == policy.ROLE_WORKER:
        if worker_body:
            say(worker_body)
        else:
            say("No worker policy set.")
        return

    combined, _ = policy.build_combined_policy(planner_body, worker_body)
    combined = policy.normalize_policy_text(combined)
    if combined:
        say(combined)
        return
    say("No project policy set.")

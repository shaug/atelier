"""Implementation for the ``atelier init`` command.

``atelier init`` registers the current repo in the Atelier data directory,
writes project configuration, and avoids modifying the repo itself.
"""

import sys
from pathlib import Path

from .. import (
    agent_home,
    beads,
    config,
    external_registry,
    git,
    paths,
    policy,
    project,
    skills,
)
from ..io import confirm, say, select


def init_project(args: object) -> None:
    """Initialize an Atelier project for the current Git repository.

    Args:
        args: CLI argument object with optional fields such as
            ``branch_prefix``, ``branch_pr``, ``branch_history``,
            ``branch_pr_strategy``, ``agent``, ``editor_edit``, and
            ``editor_work``.

    Returns:
        None.

    Example:
        $ atelier init
    """
    cwd = Path.cwd()
    _, enlistment_path, origin_raw, origin = git.resolve_repo_enlistment(cwd)

    project_dir = paths.project_dir_for_enlistment(enlistment_path, origin)
    config_path = paths.project_config_path(project_dir)
    config_payload = config.load_project_config(config_path)
    user_payload = config.load_json(paths.project_config_user_path(project_dir))
    payload = config.build_project_config(
        config_payload or {},
        enlistment_path,
        origin,
        origin_raw,
        args,
        prompt_missing_only=not bool(config_payload),
        raw_existing=user_payload,
    )
    project.ensure_project_dirs(project_dir)
    yes = bool(getattr(args, "yes", False))
    try:
        upgrade_policy = config.resolve_upgrade_policy(payload.atelier.upgrade)
        sync_result = skills.sync_project_skills(
            project_dir,
            upgrade_policy=upgrade_policy,
            yes=yes,
            interactive=(sys.stdin.isatty() and sys.stdout.isatty() and not yes),
            prompt_update=lambda message: confirm(message, default=False),
        )
        if sync_result.action in {"installed", "updated", "up_to_date"}:
            say(f"Managed skills: {sync_result.action}")
    except OSError:
        pass
    provider_resolution = external_registry.resolve_planner_provider(
        payload,
        Path(enlistment_path),
        agent_name=payload.agent.default,
        project_data_dir=project_dir,
        # Keep prompting centralized in init so "none" is always available.
        interactive=False,
    )
    selected_provider = provider_resolution.selected_provider
    current_provider = (payload.project.provider or "").strip().lower() or None
    current_auto_export = bool(payload.project.auto_export_new)
    interactive = sys.stdin.isatty() and sys.stdout.isatty() and not yes
    if interactive:
        available = list(provider_resolution.available_providers)
        if current_provider and current_provider not in available:
            available.append(current_provider)
        available = sorted(set(available))
        if available or current_provider:
            choices = ["none", *available]
            default_choice = selected_provider or current_provider or "none"
            if default_choice not in choices:
                default_choice = "none"
            selected_choice = select(
                "External ticket provider",
                choices,
                default_choice,
            )
            selected_provider = None if selected_choice == "none" else selected_choice
    if selected_provider and selected_provider != current_provider:
        payload = payload.model_copy(deep=True)
        payload.project.provider = selected_provider
    if selected_provider is None and current_provider is not None:
        payload = payload.model_copy(deep=True)
        payload.project.provider = None
    if selected_provider:
        say(f"Selected external provider: {selected_provider}")
    else:
        say("Selected external provider: none")
    next_auto_export = current_auto_export
    if selected_provider:
        if interactive:
            next_auto_export = confirm(
                f"Export all new epics/changesets to {selected_provider} by default?",
                default=current_auto_export,
            )
    else:
        next_auto_export = False
    if next_auto_export != current_auto_export:
        payload = payload.model_copy(deep=True)
        payload.project.auto_export_new = next_auto_export
    say(
        "Default auto-export for new epics/changesets: "
        + ("enabled" if bool(payload.project.auto_export_new) else "disabled")
    )
    say("Writing project configuration...")
    config.write_project_config(config_path, payload)
    project.ensure_project_scaffold(project_dir)

    beads_root = config.resolve_beads_root(project_dir, Path(enlistment_path))
    beads_cwd = project_dir
    say("Preparing Beads store...")
    beads.ensure_atelier_store(beads_root=beads_root, cwd=beads_cwd)
    beads.ensure_atelier_issue_prefix(beads_root=beads_root, cwd=beads_cwd)
    say("Priming Beads store...")
    beads.run_bd_command(["prime"], beads_root=beads_root, cwd=beads_cwd)
    say("Ensuring Beads issue types...")
    beads.ensure_atelier_types(beads_root=beads_root, cwd=beads_cwd)

    add_policy = False if yes else confirm("Add project-wide policy for agents?", default=False)
    if add_policy:
        planner_issue = beads.list_policy_beads(
            policy.ROLE_PLANNER, beads_root=beads_root, cwd=beads_cwd
        )
        worker_issue = beads.list_policy_beads(
            policy.ROLE_WORKER, beads_root=beads_root, cwd=beads_cwd
        )
        planner_body = beads.extract_policy_body(planner_issue[0]) if planner_issue else ""
        worker_body = beads.extract_policy_body(worker_issue[0]) if worker_issue else ""
        combined, split = policy.build_combined_policy(planner_body, worker_body)
        text = policy.edit_policy_text(combined, project_config=payload, cwd=cwd)
        if text.strip():
            if split:
                sections = policy.split_combined_policy(text)
                if sections:
                    planner_text = sections.get(policy.ROLE_PLANNER, "")
                    worker_text = sections.get(policy.ROLE_WORKER, "")
                else:
                    planner_text = text
                    worker_text = text
            else:
                planner_text = text
                worker_text = text
            if planner_issue:
                issue_id = planner_issue[0].get("id")
                if isinstance(issue_id, str) and issue_id:
                    beads.update_policy_bead(
                        issue_id,
                        planner_text,
                        beads_root=beads_root,
                        cwd=beads_cwd,
                    )
            else:
                beads.create_policy_bead(
                    policy.ROLE_PLANNER,
                    planner_text,
                    beads_root=beads_root,
                    cwd=beads_cwd,
                )
            if worker_issue:
                issue_id = worker_issue[0].get("id")
                if isinstance(issue_id, str) and issue_id:
                    beads.update_policy_bead(
                        issue_id,
                        worker_text,
                        beads_root=beads_root,
                        cwd=beads_cwd,
                    )
            else:
                beads.create_policy_bead(
                    policy.ROLE_WORKER,
                    worker_text,
                    beads_root=beads_root,
                    cwd=beads_cwd,
                )
            planner_home = agent_home.resolve_agent_home(
                project_dir, payload, role=policy.ROLE_PLANNER
            )
            worker_home = agent_home.resolve_agent_home(
                project_dir, payload, role=policy.ROLE_WORKER
            )
            policy.sync_agent_home_policy(
                planner_home,
                role=policy.ROLE_PLANNER,
                beads_root=beads_root,
                cwd=beads_cwd,
            )
            policy.sync_agent_home_policy(
                worker_home,
                role=policy.ROLE_WORKER,
                beads_root=beads_root,
                cwd=beads_cwd,
            )

    say("Initialized Atelier project")

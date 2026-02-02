"""Implementation for the ``atelier init`` command.

``atelier init`` registers the current repo in the Atelier data directory,
writes project configuration, and avoids modifying the repo itself.
"""

from pathlib import Path

from .. import agent_home, beads, config, git, paths, policy, project
from ..io import confirm, say


def init_project(args: object) -> None:
    """Initialize an Atelier project for the current Git repository.

    Args:
        args: CLI argument object with optional fields such as ``branch_prefix``,
            ``branch_pr``, ``branch_history``, ``agent``, ``editor_edit``, and
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
    missing_fields = config.user_config_missing_fields(user_payload)
    args_provided = any(
        getattr(args, name, None) is not None
        for name in (
            "branch_prefix",
            "branch_pr",
            "branch_history",
            "agent",
            "editor_edit",
            "editor_work",
            "editor",
        )
    )
    if config_payload and not missing_fields and not args_provided:
        say("Atelier project already initialized")
        return
    payload = config.build_project_config(
        config_payload or {},
        enlistment_path,
        origin,
        origin_raw,
        args,
        prompt_missing_only=True,
        raw_existing=user_payload,
    )
    project.ensure_project_dirs(project_dir)
    config.write_project_config(config_path, payload)
    project.ensure_project_scaffold(project_dir)

    if confirm("Add project-wide policy for agents?", default=False):
        beads_root = config.resolve_beads_root(project_dir, Path(enlistment_path))
        beads.run_bd_command(
            ["prime"], beads_root=beads_root, cwd=Path(enlistment_path)
        )
        planner_issue = beads.list_policy_beads(
            policy.ROLE_PLANNER, beads_root=beads_root, cwd=Path(enlistment_path)
        )
        worker_issue = beads.list_policy_beads(
            policy.ROLE_WORKER, beads_root=beads_root, cwd=Path(enlistment_path)
        )
        planner_body = (
            beads.extract_policy_body(planner_issue[0]) if planner_issue else ""
        )
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
                        cwd=Path(enlistment_path),
                    )
            else:
                beads.create_policy_bead(
                    policy.ROLE_PLANNER,
                    planner_text,
                    beads_root=beads_root,
                    cwd=Path(enlistment_path),
                )
            if worker_issue:
                issue_id = worker_issue[0].get("id")
                if isinstance(issue_id, str) and issue_id:
                    beads.update_policy_bead(
                        issue_id,
                        worker_text,
                        beads_root=beads_root,
                        cwd=Path(enlistment_path),
                    )
            else:
                beads.create_policy_bead(
                    policy.ROLE_WORKER,
                    worker_text,
                    beads_root=beads_root,
                    cwd=Path(enlistment_path),
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
                cwd=Path(enlistment_path),
            )
            policy.sync_agent_home_policy(
                worker_home,
                role=policy.ROLE_WORKER,
                beads_root=beads_root,
                cwd=Path(enlistment_path),
            )

    say("Initialized Atelier project")

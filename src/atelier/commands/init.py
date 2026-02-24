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
from ..io import confirm, die, say, select
from ..services import ServiceFailure
from ..services.project import (
    ComposeProjectConfigService,
    InitializeProjectDependencies,
    InitializeProjectRequest,
    InitializeProjectService,
    ResolveExternalProviderService,
)


def _build_init_service() -> InitializeProjectService:
    """Build init orchestration service with command-scoped dependencies.

    Returns:
        ``InitializeProjectService`` configured with command dependencies.
    """

    return InitializeProjectService(
        InitializeProjectDependencies(
            resolve_repo_enlistment=git.resolve_repo_enlistment,
            project_dir_for_enlistment=paths.project_dir_for_enlistment,
            project_config_path=paths.project_config_path,
            project_config_user_path=paths.project_config_user_path,
            load_project_config=config.load_project_config,
            load_json=config.load_json,
            ensure_project_dirs=project.ensure_project_dirs,
            resolve_upgrade_policy=config.resolve_upgrade_policy,
            sync_project_skills=skills.sync_project_skills,
            compose_config_service=ComposeProjectConfigService(
                build_config=config.build_project_config
            ),
            resolve_provider_service=ResolveExternalProviderService(
                resolve_provider=external_registry.resolve_planner_provider,
                choose_provider=select,
                confirm_choice=confirm,
            ),
            write_project_config=config.write_project_config,
            ensure_project_scaffold=project.ensure_project_scaffold,
            resolve_beads_root=config.resolve_beads_root,
            ensure_atelier_store=beads.ensure_atelier_store,
            ensure_atelier_issue_prefix=beads.ensure_atelier_issue_prefix,
            run_bd_command=beads.run_bd_command,
            ensure_atelier_types=beads.ensure_atelier_types,
            list_policy_beads=beads.list_policy_beads,
            extract_policy_body=beads.extract_policy_body,
            build_combined_policy=policy.build_combined_policy,
            edit_policy_text=policy.edit_policy_text,
            split_combined_policy=policy.split_combined_policy,
            update_policy_bead=beads.update_policy_bead,
            create_policy_bead=beads.create_policy_bead,
            resolve_agent_home=agent_home.resolve_agent_home,
            sync_agent_home_policy=policy.sync_agent_home_policy,
            confirm_choice=confirm,
        )
    )


def init_project(args: object) -> None:
    """Initialize an Atelier project for the current Git repository.

    Args:
        args: CLI argument object with optional fields such as
            ``branch_prefix``, ``branch_pr_mode``, ``branch_history``,
            ``branch_pr_strategy``, ``agent``, ``editor_edit``, and
            ``editor_work``.

    Returns:
        None.

    Example:
        $ atelier init
    """
    service = _build_init_service()
    result = service.run(
        InitializeProjectRequest(
            args=args,
            cwd=Path.cwd(),
            stdin_isatty=sys.stdin.isatty(),
            stdout_isatty=sys.stdout.isatty(),
        )
    )
    if isinstance(result, ServiceFailure):
        hint = f"\nHint: {result.recovery_hint}" if result.recovery_hint else ""
        die(f"init failed ({result.code}): {result.message}{hint}")
    for message in result.outcome.messages:
        say(message)

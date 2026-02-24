"""Implementation for the ``atelier init`` command.

``atelier init`` registers the current repo in the Atelier data directory,
writes project configuration, and avoids modifying the repo itself.
"""

import sys
from pathlib import Path

from .. import config, external_registry
from ..io import confirm, die, say, select
from ..services.project import (
    ComposeProjectConfigService,
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
        compose_config_service=ComposeProjectConfigService(
            build_config=config.build_project_config
        ),
        resolve_provider_service=ResolveExternalProviderService(
            resolve_provider=external_registry.resolve_planner_provider,
            choose_provider=select,
            confirm_choice=confirm,
        ),
        confirm_choice=confirm,
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
    if result.success is True:
        for message in result.outcome.messages:
            say(message)
    else:
        hint = f"\nHint: {result.recovery_hint}" if result.recovery_hint else ""
        die(f"init failed ({result.code}): {result.message}{hint}")

"""Implementation for the ``atelier init`` command.

``atelier init`` registers the current repo in the Atelier data directory,
writes project configuration, and avoids modifying the repo itself.
"""

import sys
from pathlib import Path
from typing import cast

from .. import config, external_registry
from ..io import confirm, die, say, select
from ..lib import apply
from ..services import ServiceFailure, ServiceSuccess
from ..services.project import (
    InitializeProjectOutcome,
    InitializeProjectService,
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
    result = InitializeProjectService.run_default(
        args=args,
        cwd=Path.cwd(),
        stdin_isatty=sys.stdin.isatty(),
        stdout_isatty=sys.stdout.isatty(),
        build_config=config.build_project_config,
        resolve_provider=external_registry.resolve_planner_provider,
        choose_provider=select,
        confirm_choice=confirm,
    )
    if not result.success:
        failure = cast(ServiceFailure, result)
        hint = f"\nHint: {failure.recovery_hint}" if failure.recovery_hint else ""
        die(f"init failed ({failure.code}): {failure.message}{hint}")
    success = cast(ServiceSuccess[InitializeProjectOutcome], result)
    apply(success.outcome.messages, say)

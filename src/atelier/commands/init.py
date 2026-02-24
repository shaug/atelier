"""Implementation for the ``atelier init`` command.

``atelier init`` registers the current repo in the Atelier data directory,
writes project configuration, and avoids modifying the repo itself.
"""

from ..io import die, say
from ..lib import apply
from ..services.project import InitializeProjectService


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
    result = InitializeProjectService.run(args=args)
    if result.success is False:
        failure = result
        hint = f"\nHint: {failure.recovery_hint}" if failure.recovery_hint else ""
        die(f"init failed ({failure.code}): {failure.message}{hint}")
    apply(say, result.outcome.messages)

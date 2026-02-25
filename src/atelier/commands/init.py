"""Implementation for the ``atelier init`` command.

``atelier init`` registers the current repo in the Atelier data directory,
writes project configuration, and avoids modifying the repo itself.
"""

from ..io import die, say
from ..lib import apply
from ..services import ServiceFailure
from ..services.project import InitializeProjectService, InitProjectArgs


def init_project(args: InitProjectArgs) -> None:
    """Initialize an Atelier project for the current Git repository.

    Args:
        args: Typed init arguments. The CLI layer must populate this from
            the parsed command before calling.

    Returns:
        None.

    Example:
        $ atelier init
    """
    try:
        outcome = InitializeProjectService.run(args=args)
        apply(say, outcome.messages)
    except ServiceFailure as e:
        hint = f"\nHint: {e.recovery_hint}" if e.recovery_hint else ""
        die(f"init failed ({e.code}): {e}{hint}")

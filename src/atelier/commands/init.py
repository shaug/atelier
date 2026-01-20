"""Implementation for the ``atelier init`` command."""

from pathlib import Path

from .. import config, git, paths, project
from ..io import say


def init_project(args: object) -> None:
    """Initialize an Atelier project for the current Git repository.

    Args:
        args: CLI argument object with optional fields such as ``branch_prefix``,
            ``branch_pr``, ``branch_history``, ``agent``, and ``editor``.

    Returns:
        None.

    Example:
        $ atelier init
    """
    cwd = Path.cwd()
    _, enlistment_path, origin_raw, origin = git.resolve_repo_enlistment(cwd)

    project_dir = paths.project_dir_for_enlistment(enlistment_path, origin)
    config_path = paths.project_config_path(project_dir)
    existing = config.load_project_config(config_path)
    payload = config.build_project_config(
        existing or {},
        enlistment_path,
        origin,
        origin_raw,
        args,
    )
    project.ensure_project_dirs(project_dir)
    config.write_json(config_path, payload)
    project.ensure_project_scaffold(project_dir)

    say("Initialized Atelier project")

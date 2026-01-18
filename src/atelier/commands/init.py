"""Implementation for the ``atelier init`` command."""

from pathlib import Path

from .. import config, git, paths, project
from ..io import die, say


def init_project(args: object) -> None:
    """Initialize an Atelier project for the current Git repository.

    Args:
        args: CLI argument object with optional fields such as ``branch_prefix``,
            ``branch_pr``, ``branch_history``, ``agent``, ``editor``, and
            ``workspace_template``.

    Returns:
        None.

    Example:
        $ atelier init --workspace-template
    """
    cwd = Path.cwd()
    repo_root = git.git_repo_root(cwd)
    if not repo_root:
        die("atelier init must be run inside a git repository")

    origin_raw = git.git_origin_url(repo_root)
    if not origin_raw:
        die("repo missing origin remote")
    origin = git.normalize_origin_url(origin_raw)
    if not origin:
        die("failed to normalize origin URL")

    project_dir = paths.project_dir_for_origin(origin)
    config_path = paths.project_config_path(project_dir)
    existing = config.load_project_config(config_path)
    payload = config.build_project_config(existing or {}, origin, origin_raw, args)
    project.ensure_project_dirs(project_dir)
    config.write_json(config_path, payload)
    project.ensure_project_scaffold(
        project_dir, bool(getattr(args, "workspace_template", False))
    )

    say("Initialized Atelier project")

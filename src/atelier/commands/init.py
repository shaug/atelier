"""Implementation for the ``atelier init`` command."""

from pathlib import Path

from .. import config, git, paths, project
from ..io import say


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
    config.update_project_managed_files(
        project_dir, config.managed_project_agents_updates(project_dir)
    )

    say("Initialized Atelier project")

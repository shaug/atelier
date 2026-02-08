"""Implementation for the ``atelier new`` command.

``atelier new`` creates a brand-new local git repository, registers it as an
Atelier project, and drops into planning mode.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

from .. import config, exec, paths
from ..io import die, prompt
from . import init as init_cmd
from . import plan as plan_cmd


def _dir_is_empty(path: Path) -> bool:
    if not path.exists():
        return True
    if not path.is_dir():
        die(f"path exists and is not a directory: {path}")
    return next(path.iterdir(), None) is None


def _resolve_project_path(path_input: str | None) -> Path:
    cwd = Path.cwd()
    if path_input is None:
        if _dir_is_empty(cwd):
            return cwd
        if sys.stdin.isatty() and sys.stdout.isatty():
            response = prompt("Project path", required=True)
            path_input = response
        else:
            die("current directory is not empty; provide a path")
    value = str(path_input).strip()
    if not value:
        die("project path is required")
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = (cwd / candidate).resolve()
    return candidate


def _ensure_empty_dir(path: Path) -> None:
    if path.exists():
        if not path.is_dir():
            die(f"path exists and is not a directory: {path}")
        if not _dir_is_empty(path):
            die(f"path is not empty: {path}")
        return
    paths.ensure_dir(path)


def new_project(args: object) -> None:
    """Create a brand-new local project and start planning.

    Args:
        args: CLI argument object with optional fields such as ``path``,
            ``branch_prefix``, ``branch_pr``, ``branch_history``,
            ``branch_pr_strategy``, ``agent``, ``editor_edit``, and
            ``editor_work``.

    Returns:
        None.

    Example:
        $ atelier new ~/code/greenfield
    """
    path_input = getattr(args, "path", None)
    target_dir = _resolve_project_path(path_input)
    _ensure_empty_dir(target_dir)

    default_branch = prompt("Default branch name", "main", required=True).strip()
    if not default_branch:
        die("default branch name is required")

    exec.run_command(["git", "init", "-b", default_branch], cwd=target_dir)
    exec.run_command(
        [
            "git",
            "-C",
            str(target_dir),
            "commit",
            "--allow-empty",
            "-m",
            "chore: initial",
        ]
    )

    original_cwd = Path.cwd()
    os.chdir(target_dir)
    try:
        init_cmd.init_project(
            SimpleNamespace(
                branch_prefix=getattr(args, "branch_prefix", None),
                branch_pr=getattr(args, "branch_pr", None),
                branch_history=getattr(args, "branch_history", None),
                branch_pr_strategy=getattr(args, "branch_pr_strategy", None),
                agent=getattr(args, "agent", None),
                editor_edit=getattr(args, "editor_edit", None),
                editor_work=getattr(args, "editor_work", None),
            )
        )

        enlistment_path = str(target_dir.resolve())
        project_dir = paths.project_dir_for_enlistment(enlistment_path, None)
        config_path = paths.project_config_path(project_dir)
        config_payload = config.load_project_config(config_path)
        if not config_payload:
            die("failed to load project config after initialization")
        if not config_payload.project.allow_mainline_workspace:
            project_section = config_payload.project.model_copy(
                update={"allow_mainline_workspace": True}
            )
            config_payload = config_payload.model_copy(
                update={"project": project_section}
            )
            config.write_project_config(config_path, config_payload)

        plan_cmd.run_planner(SimpleNamespace(create_epic=False, epic_id=None))
    finally:
        os.chdir(original_cwd)

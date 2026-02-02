"""Shared project resolution helpers for commands."""

from __future__ import annotations

from pathlib import Path

from .. import config, git, paths
from ..io import die


def resolve_project_for_enlistment(
    enlistment_path: str, origin: str | None
) -> tuple[Path, config.ProjectConfig, str]:
    """Resolve the current project config for a repo enlistment."""
    project_root = paths.project_dir_for_enlistment(enlistment_path, origin)
    config_path = paths.project_config_path(project_root)
    config_payload = config.load_project_config(config_path)
    if not config_payload:
        die("no Atelier project config found for this repo; run 'atelier init'")
    project_enlistment = config_payload.project.enlistment
    if project_enlistment and project_enlistment != enlistment_path:
        die("project enlistment does not match current repo path")
    return project_root, config_payload, enlistment_path


def resolve_current_project() -> tuple[Path, config.ProjectConfig, str]:
    """Resolve the current project from the working directory."""
    cwd = Path.cwd()
    _, enlistment_path, _, origin = git.resolve_repo_enlistment(cwd)
    return resolve_project_for_enlistment(enlistment_path, origin)


def resolve_current_project_with_repo_root() -> tuple[
    Path, config.ProjectConfig, str, Path
]:
    """Resolve the current project plus the repo root from the working directory."""
    cwd = Path.cwd()
    repo_root, enlistment_path, _, origin = git.resolve_repo_enlistment(cwd)
    project_root, config_payload, enlistment_path = resolve_project_for_enlistment(
        enlistment_path, origin
    )
    return project_root, config_payload, enlistment_path, repo_root

"""Implementation for the ``atelier config`` command."""

from __future__ import annotations

import json
from pathlib import Path

from .. import config, git, paths, workspace
from ..io import confirm, die, say


def _resolve_project() -> tuple[Path, config.ProjectConfig, str]:
    cwd = Path.cwd()
    _, enlistment_path, _, origin = git.resolve_repo_enlistment(cwd)
    project_root = paths.project_dir_for_enlistment(enlistment_path, origin)
    config_path = paths.project_config_path(project_root)
    config_payload = config.load_project_config(config_path)
    if not config_payload:
        die("no Atelier project config found for this repo; run 'atelier init'")
    project_enlistment = config_payload.project.enlistment
    if project_enlistment and project_enlistment != enlistment_path:
        die("project enlistment does not match current repo path")
    return project_root, config_payload, enlistment_path


def _emit_json(payload: dict) -> None:
    say(json.dumps(payload, indent=2))


def _apply_user_sections(
    base: config.ProjectConfig, updates: config.ProjectConfig
) -> config.ProjectConfig:
    return base.model_copy(
        update={
            "branch": updates.branch,
            "agent": updates.agent,
            "editor": updates.editor,
        }
    )


def show_config(args: object) -> None:
    """Show or update Atelier configuration for the current project."""
    workspace_name = getattr(args, "workspace_name", None)
    installed = bool(getattr(args, "installed", False))
    prompt_values = bool(getattr(args, "prompt", False))
    reset_values = bool(getattr(args, "reset", False))

    project_root, project_config, enlistment_path = _resolve_project()

    if workspace_name:
        if installed or prompt_values or reset_values:
            die("workspace config cannot be combined with --installed/--prompt/--reset")
        normalized = workspace.normalize_workspace_name(str(workspace_name))
        if not normalized:
            die("workspace branch must not be empty")
        branch, workspace_dir, exists = workspace.resolve_workspace_target(
            project_root,
            project_config.project.enlistment or enlistment_path,
            normalized,
            project_config.branch.prefix,
            False,
        )
        if not exists:
            die(f"workspace not found: {normalized}")
        workspace_config = config.load_workspace_config(
            paths.workspace_config_path(workspace_dir)
        )
        if not workspace_config:
            die(f"failed to load workspace config for {branch}")
        _emit_json(workspace_config.model_dump())
        return

    if installed:
        defaults = config.load_installed_defaults()
        if reset_values:
            if confirm("Reset installed defaults to packaged defaults?", default=False):
                defaults = config.default_user_config()
                config.write_installed_defaults(defaults)
            else:
                defaults = config.load_installed_defaults()
        if prompt_values:
            prompted = config.build_project_config(
                defaults,
                "",
                None,
                None,
                None,
                allow_editor_empty=True,
            )
            defaults = _apply_user_sections(defaults, prompted)
            config.write_installed_defaults(defaults)
        _emit_json(config.user_config_payload(defaults))
        return

    config_path = paths.project_config_path(project_root)
    updated = project_config

    if reset_values:
        if confirm("Reset config values to installed defaults?", default=False):
            defaults = config.load_installed_defaults()
            updated = _apply_user_sections(updated, defaults)
            config.write_json(config_path, updated)
        else:
            updated = project_config

    if prompt_values:
        prompted = config.build_project_config(
            updated,
            enlistment_path,
            updated.project.origin,
            updated.project.repo_url,
            None,
            allow_editor_empty=True,
        )
        updated = _apply_user_sections(updated, prompted)
        config.write_json(config_path, updated)

    _emit_json(updated.model_dump())

"""Implementation for the ``atelier config`` command."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from .. import config, editor, exec, git, paths, workspace
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
    atelier_section = base.atelier.model_copy(
        update={"upgrade": updates.atelier.upgrade}
    )
    return base.model_copy(
        update={
            "branch": updates.branch,
            "agent": updates.agent,
            "editor": updates.editor,
            "atelier": atelier_section,
        }
    )


def _edit_user_config(
    *,
    payload: dict,
    editor_cmd: list[str],
    target_path: Path,
    cwd: Path,
) -> None:
    temp_path: Path | None = None
    wrote = False
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as fh:
            temp_path = Path(fh.name)
            json.dump(payload, fh, indent=2)
            fh.write("\n")
        exec.run_command([*editor_cmd, str(temp_path)], cwd=cwd)
        if temp_path is None:
            die("failed to locate edited config")
        try:
            edited_payload = json.loads(temp_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            die(f"invalid JSON in edited config ({temp_path}): {exc}")
        parsed = config.parse_project_user_config(edited_payload, temp_path)
        paths.ensure_dir(target_path.parent)
        config.write_json(target_path, parsed)
        wrote = True
    finally:
        if wrote and temp_path is not None:
            temp_path.unlink(missing_ok=True)


def show_config(args: object) -> None:
    """Show or update Atelier configuration for the current project."""
    workspace_name = getattr(args, "workspace_name", None)
    installed = bool(getattr(args, "installed", False))
    prompt_values = bool(getattr(args, "prompt", False))
    reset_values = bool(getattr(args, "reset", False))
    edit_values = bool(getattr(args, "edit", False))

    if prompt_values and edit_values:
        die("--prompt and --edit cannot be combined")

    project_root, project_config, enlistment_path = _resolve_project()

    if workspace_name:
        if installed or prompt_values or reset_values or edit_values:
            die(
                "workspace config cannot be combined with --installed/--prompt/--reset/--edit"
            )
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
                user_defaults = config.default_user_config()
                config.write_installed_defaults(user_defaults)
                defaults = config.merge_project_configs(
                    config.ProjectSystemConfig(), user_defaults
                )
            else:
                defaults = config.load_installed_defaults()
        if edit_values:
            _edit_user_config(
                payload=config.user_config_payload(defaults),
                editor_cmd=editor.resolve_editor_command(defaults, role="edit"),
                target_path=paths.installed_config_path(),
                cwd=project_root,
            )
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
            user_config = config.parse_project_user_config(
                config.user_config_payload(updated)
            )
            config.write_project_user_config(
                paths.project_config_user_path(project_root), user_config
            )
        else:
            updated = project_config

    if edit_values:
        _edit_user_config(
            payload=config.user_config_payload(updated),
            editor_cmd=editor.resolve_editor_command(updated, role="edit"),
            target_path=paths.project_config_user_path(project_root),
            cwd=project_root,
        )
        updated = config.load_project_config(config_path) or updated

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
        user_config = config.parse_project_user_config(
            config.user_config_payload(updated)
        )
        config.write_project_user_config(
            paths.project_config_user_path(project_root), user_config
        )

    _emit_json(updated.model_dump())

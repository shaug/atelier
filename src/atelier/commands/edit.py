"""Implementation for the ``atelier edit`` command."""

from __future__ import annotations

import shutil
from pathlib import Path

from .. import config, editor, exec, git, paths, templates, workspace
from ..io import die


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


def edit_files(args: object) -> None:
    """Open editable project/workspace documents in ``editor.edit``."""
    workspace_name = getattr(args, "workspace_name", None)
    edit_project = bool(getattr(args, "project", False))
    if edit_project and workspace_name:
        die("cannot combine --project with a workspace argument")
    if not edit_project and not workspace_name:
        die("must specify --project or a workspace branch")

    project_root, project_config, enlistment_path = _resolve_project()
    editor_cmd = editor.resolve_editor_command(project_config, role="edit")
    git_path = config.resolve_git_path(project_config)

    if edit_project:
        project_path = project_root / "PROJECT.md"
        if not project_path.exists():
            project_path.write_text(
                templates.project_md_template(prefer_installed=True), encoding="utf-8"
            )
        exec.run_command([*editor_cmd, str(project_path)], cwd=project_root)
        return

    normalized = workspace.normalize_workspace_name(str(workspace_name))
    if not normalized:
        die("workspace branch must not be empty")
    branch, workspace_dir, exists = workspace.resolve_workspace_target(
        project_root,
        project_config.project.enlistment or enlistment_path,
        normalized,
        project_config.branch.prefix,
        False,
        git_path,
    )
    if not exists:
        die(f"workspace not found: {normalized}")

    success_path = workspace_dir / "SUCCESS.md"
    if success_path.exists():
        target_path = success_path
    else:
        template_path = project_root / paths.TEMPLATES_DIRNAME / "SUCCESS.md"
        if template_path.exists():
            shutil.copyfile(template_path, success_path)
        else:
            success_path.write_text(
                templates.success_md_template(prefer_installed=True),
                encoding="utf-8",
            )
        target_path = success_path

    exec.run_command([*editor_cmd, str(target_path)], cwd=workspace_dir)

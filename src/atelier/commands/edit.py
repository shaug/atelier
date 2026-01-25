"""Implementation for the ``atelier edit`` command."""

from __future__ import annotations

import shutil

from .. import config, editor, exec, paths, templates
from ..io import die
from .resolve import resolve_current_project, resolve_workspace_target


def edit_files(args: object) -> None:
    """Open editable project/workspace documents in ``editor.edit``."""
    workspace_name = getattr(args, "workspace_name", None)
    edit_project = bool(getattr(args, "project", False))
    if edit_project and workspace_name:
        die("cannot combine --project with a workspace argument")
    if not edit_project and not workspace_name:
        die("must specify --project or a workspace branch")

    project_root, project_config, enlistment_path = resolve_current_project()
    editor_cmd = editor.resolve_editor_command(project_config, role="edit")
    git_path = config.resolve_git_path(project_config)

    if edit_project:
        project_path = project_root / "PROJECT.md"
        if not project_path.exists():
            project_path.write_text(
                templates.project_md_template(prefer_installed_if_modified=True),
                encoding="utf-8",
            )
        exec.run_command([*editor_cmd, str(project_path)], cwd=project_root)
        return

    branch, workspace_dir = resolve_workspace_target(
        project_root=project_root,
        project_config=project_config,
        enlistment_path=enlistment_path,
        workspace_name=str(workspace_name),
        raw=False,
        git_path=git_path,
    )

    success_path = workspace_dir / "SUCCESS.md"
    if success_path.exists():
        target_path = success_path
    else:
        template_path = project_root / paths.TEMPLATES_DIRNAME / "SUCCESS.md"
        if template_path.exists():
            shutil.copyfile(template_path, success_path)
        else:
            success_path.write_text(
                templates.success_md_template(prefer_installed_if_modified=True),
                encoding="utf-8",
            )
        target_path = success_path

    exec.run_command([*editor_cmd, str(target_path)], cwd=workspace_dir)

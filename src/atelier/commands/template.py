"""Implementation for the ``atelier template`` command."""

from __future__ import annotations

from pathlib import Path

from .. import config, editor, exec, git, paths, templates
from ..io import die, say

TEMPLATE_TARGETS = {
    "project": ("project", "PROJECT.md"),
    "workspace": ("workspace", "SUCCESS.md"),
}


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


def _installed_template_path(*parts: str) -> Path:
    return paths.installed_templates_dir().joinpath(*parts)


def render_template(args: object) -> None:
    """Render or edit templates for the current project."""
    target = getattr(args, "target", None)
    if target == "success":
        target = "workspace"
    if target not in TEMPLATE_TARGETS:
        die("template target must be one of: project, workspace, success")

    installed = bool(getattr(args, "installed", False))
    edit_mode = bool(getattr(args, "edit", False))

    project_root, project_config, _ = _resolve_project()

    if target == "project":
        parts = TEMPLATE_TARGETS["project"]
        text = templates.project_md_template(prefer_installed=True)
        template_path = _installed_template_path(*parts)
    else:
        parts = TEMPLATE_TARGETS["workspace"]
        project_template_path = project_root / paths.TEMPLATES_DIRNAME / "SUCCESS.md"
        if not installed and project_template_path.exists():
            text = project_template_path.read_text(encoding="utf-8")
            template_path = project_template_path
        else:
            text = templates.success_md_template(prefer_installed=True)
            template_path = _installed_template_path(*parts)

    if not edit_mode:
        say(text)
        return

    if not template_path.exists():
        paths.ensure_dir(template_path.parent)
        template_path.write_text(text, encoding="utf-8")

    editor_cmd = editor.resolve_editor_command(project_config)
    exec.run_command([*editor_cmd, str(template_path)], cwd=project_root)

"""Implementation for the ``atelier template`` command."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from .. import config, editor, exec, git, paths, templates
from ..io import die, say, warn

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


def _edit_template(
    *,
    text: str,
    target_path: Path,
    editor_cmd: list[str],
    cwd: Path,
) -> None:
    temp_path: Path | None = None
    wrote = False
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=target_path.suffix or ".md",
            delete=False,
            encoding="utf-8",
        ) as fh:
            temp_path = Path(fh.name)
            fh.write(text)
        exec.run_command([*editor_cmd, str(temp_path)], cwd=cwd)
        if temp_path is None:
            die("failed to locate edited template")
        paths.ensure_dir(target_path.parent)
        shutil.copyfile(temp_path, target_path)
        wrote = True
    finally:
        if wrote and temp_path is not None:
            temp_path.unlink(missing_ok=True)


def render_template(args: object) -> None:
    """Render or edit templates for the current project."""
    target = getattr(args, "target", None)
    if target == "success":
        target = "workspace"
    if target not in TEMPLATE_TARGETS:
        die("template target must be one of: project, workspace, success")

    installed = bool(getattr(args, "installed", False))
    edit_mode = bool(getattr(args, "edit", False))
    ticket = bool(getattr(args, "ticket", False))

    project_root, project_config, _ = _resolve_project()

    if target == "project":
        if ticket:
            warn("ignoring --ticket for project templates")
        project_template_path = project_root / "PROJECT.md"
        if not installed and project_template_path.exists():
            text = project_template_path.read_text(encoding="utf-8")
        else:
            text = templates.project_md_template(prefer_installed=True)
        target_path = project_template_path
    else:
        if ticket:
            project_template_path = (
                project_root / paths.TEMPLATES_DIRNAME / "SUCCESS.ticket.md"
            )
            if not installed and project_template_path.exists():
                text = project_template_path.read_text(encoding="utf-8")
            else:
                text = templates.ticket_success_md_template(prefer_installed=True)
            target_path = project_template_path
        else:
            project_template_path = (
                project_root / paths.TEMPLATES_DIRNAME / "SUCCESS.md"
            )
            if not installed and project_template_path.exists():
                text = project_template_path.read_text(encoding="utf-8")
            else:
                text = templates.success_md_template(prefer_installed=True)
            target_path = project_template_path

    if not edit_mode:
        say(text)
        return

    editor_cmd = editor.resolve_editor_command(project_config, role="edit")
    _edit_template(
        text=text,
        target_path=target_path,
        editor_cmd=editor_cmd,
        cwd=project_root,
    )

"""Implementation for the ``atelier template`` command."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from .. import editor, exec, paths, templates
from ..io import die, say, warn
from .resolve import resolve_current_project

TEMPLATE_TARGETS = {
    "project": ("project", "PROJECT.md"),
    "workspace": ("workspace", "SUCCESS.md"),
}


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

    project_root, project_config, _ = resolve_current_project()

    if target == "project":
        if ticket:
            warn("ignoring --ticket for project templates")
        project_template_path = project_root / "PROJECT.md"
        if not installed and project_template_path.exists():
            text = project_template_path.read_text(encoding="utf-8")
        else:
            text = templates.project_md_template(prefer_installed_if_modified=True)
        target_path = project_template_path
    else:
        if ticket:
            project_template_path = (
                project_root / paths.TEMPLATES_DIRNAME / "SUCCESS.ticket.md"
            )
            if not installed and project_template_path.exists():
                text = project_template_path.read_text(encoding="utf-8")
            else:
                text = templates.ticket_success_md_template(
                    prefer_installed_if_modified=True
                )
            target_path = project_template_path
        else:
            project_template_path = (
                project_root / paths.TEMPLATES_DIRNAME / "SUCCESS.md"
            )
            if not installed and project_template_path.exists():
                text = project_template_path.read_text(encoding="utf-8")
            else:
                text = templates.success_md_template(prefer_installed_if_modified=True)
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

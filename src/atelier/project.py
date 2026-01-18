"""Project directory scaffolding helpers for Atelier."""

from pathlib import Path

from . import templates
from .io import say
from .paths import TEMPLATES_DIRNAME, WORKSPACES_DIRNAME, ensure_dir


def ensure_project_dirs(project_dir: Path) -> None:
    """Ensure the base project directories exist.

    Args:
        project_dir: Path to the project directory.

    Returns:
        None.

    Example:
        >>> ensure_project_dirs(Path("/tmp/atelier-project"))
    """
    ensure_dir(project_dir)
    ensure_dir(project_dir / WORKSPACES_DIRNAME)


def ensure_project_scaffold(project_dir: Path, create_workspace_template: bool) -> None:
    """Create project-level files and optional templates when missing.

    Args:
        project_dir: Path to the project directory.
        create_workspace_template: When true, create ``templates/WORKSPACE.md``.

    Returns:
        None.

    Example:
        >>> ensure_project_scaffold(Path("/tmp/atelier-project"), False)
    """
    ensure_project_dirs(project_dir)

    agents_path = project_dir / "AGENTS.md"
    if not agents_path.exists():
        agents_path.write_text(templates.project_agents_template(), encoding="utf-8")
        say("Created AGENTS.md")

    project_md_path = project_dir / "PROJECT.md"
    if not project_md_path.exists():
        project_md_path.write_text(templates.project_md_template(), encoding="utf-8")
        say("Created PROJECT.md")

    if create_workspace_template:
        workspace_template_path = project_dir / TEMPLATES_DIRNAME / "WORKSPACE.md"
        if not workspace_template_path.exists():
            ensure_dir(workspace_template_path.parent)
            workspace_template_path.write_text(
                templates.workspace_md_template(), encoding="utf-8"
            )
            say("Created templates/WORKSPACE.md")

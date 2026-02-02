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


def ensure_project_scaffold(project_dir: Path) -> None:
    """Create project-level files and templates when missing.

    Args:
        project_dir: Path to the project directory.

    Returns:
        None.

    Example:
        >>> ensure_project_scaffold(Path("/tmp/atelier-project"))
    """
    ensure_project_dirs(project_dir)

    templates_dir = project_dir / TEMPLATES_DIRNAME
    agents_template_path = templates_dir / "AGENTS.md"
    if not agents_template_path.exists():
        ensure_dir(agents_template_path.parent)
        agents_template_path.write_text(
            templates.agents_template(prefer_installed_if_modified=True),
            encoding="utf-8",
        )
        say("Created templates/AGENTS.md")

    project_md_path = project_dir / "PROJECT.md"
    if not project_md_path.exists():
        project_md_path.write_text(
            templates.project_md_template(prefer_installed_if_modified=True),
            encoding="utf-8",
        )
        say("Created PROJECT.md")

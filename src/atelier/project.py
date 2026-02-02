"""Project directory scaffolding helpers for Atelier."""

from pathlib import Path

from .paths import ensure_dir


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


def ensure_project_scaffold(project_dir: Path) -> None:
    """Ensure project-level scaffolding is present.

    Args:
        project_dir: Path to the project directory.

    Returns:
        None.

    Example:
        >>> ensure_project_scaffold(Path("/tmp/atelier-project"))
    """
    ensure_project_dirs(project_dir)

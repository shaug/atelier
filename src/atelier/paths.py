"""Path helpers for locating Atelier data directories and files."""

import hashlib
from pathlib import Path

from platformdirs import user_data_dir

ATELIER_APP_NAME = "atelier"
PROJECTS_DIRNAME = "projects"
WORKSPACES_DIRNAME = "workspaces"
TEMPLATES_DIRNAME = "templates"
PROJECT_CONFIG_FILENAME = "config.json"
WORKSPACE_CONFIG_FILENAME = "config.json"


def atelier_data_dir() -> Path:
    """Return the base Atelier data directory.

    Returns:
        Path to the user data directory for Atelier.

    Example:
        >>> isinstance(atelier_data_dir(), Path)
        True
    """
    return Path(user_data_dir(ATELIER_APP_NAME))


def projects_root() -> Path:
    """Return the root directory for Atelier projects.

    Returns:
        Path to the projects root directory.

    Example:
        >>> projects_root().name == PROJECTS_DIRNAME
        True
    """
    return atelier_data_dir() / PROJECTS_DIRNAME


def project_key(origin: str) -> str:
    """Hash a normalized origin string into a project key.

    Args:
        origin: Normalized origin string.

    Returns:
        Hex digest project key.

    Example:
        >>> len(project_key("github.com/org/repo")) == 64
        True
    """
    return hashlib.sha256(origin.encode("utf-8")).hexdigest()


def workspace_key(branch: str) -> str:
    """Hash a workspace branch name into a workspace key.

    Args:
        branch: Workspace branch name.

    Returns:
        Hex digest workspace key.

    Example:
        >>> len(workspace_key("feat/demo")) == 64
        True
    """
    return hashlib.sha256(branch.encode("utf-8")).hexdigest()


def project_dir_for_origin(origin: str) -> Path:
    """Return the project directory for a normalized origin.

    Args:
        origin: Normalized origin string.

    Returns:
        Project directory path.

    Example:
        >>> project_dir_for_origin("github.com/org/repo").name == project_key("github.com/org/repo")
        True
    """
    return projects_root() / project_key(origin)


def project_config_path(project_dir: Path) -> Path:
    """Return the path to a project's ``config.json`` file.

    Args:
        project_dir: Project directory path.

    Returns:
        Path to ``config.json``.

    Example:
        >>> project_config_path(Path("/tmp/project")).name == PROJECT_CONFIG_FILENAME
        True
    """
    return project_dir / PROJECT_CONFIG_FILENAME


def workspaces_root_for_project(project_dir: Path) -> Path:
    """Return the workspaces root directory for a project.

    Args:
        project_dir: Project directory path.

    Returns:
        Path to the workspaces root.

    Example:
        >>> workspaces_root_for_project(Path("/tmp/project")).name == WORKSPACES_DIRNAME
        True
    """
    return project_dir / WORKSPACES_DIRNAME


def workspace_dir_for_branch(project_dir: Path, branch: str) -> Path:
    """Return the workspace directory path for a branch.

    Args:
        project_dir: Project directory path.
        branch: Workspace branch name.

    Returns:
        Path to the workspace directory.

    Example:
        >>> workspace_dir_for_branch(Path("/tmp/project"), "feat/demo").parent.name == WORKSPACES_DIRNAME
        True
    """
    return workspaces_root_for_project(project_dir) / workspace_key(branch)


def workspace_config_path(workspace_dir: Path) -> Path:
    """Return the path to a workspace ``config.json`` file.

    Args:
        workspace_dir: Workspace directory path.

    Returns:
        Path to ``config.json``.

    Example:
        >>> workspace_config_path(Path("/tmp/workspace")).name == WORKSPACE_CONFIG_FILENAME
        True
    """
    return workspace_dir / WORKSPACE_CONFIG_FILENAME


def ensure_dir(path: Path) -> None:
    """Create a directory if it does not exist.

    Args:
        path: Directory path to ensure exists.

    Returns:
        None.

    Example:
        >>> ensure_dir(Path("/tmp/atelier-dir"))
    """
    path.mkdir(parents=True, exist_ok=True)

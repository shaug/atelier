"""Path helpers for locating Atelier data directories and files."""

import hashlib
import string
from pathlib import Path

from platformdirs import user_data_dir

ATELIER_APP_NAME = "atelier"
PROJECTS_DIRNAME = "projects"
WORKSPACES_DIRNAME = "workspaces"
WORKTREES_DIRNAME = "worktrees"
TEMPLATES_DIRNAME = "templates"
SKILLS_DIRNAME = "skills"
AGENTS_DIRNAME = "agents"
BEADS_DIRNAME = ".beads"
LEGACY_CONFIG_FILENAME = "config.json"
PROJECT_CONFIG_SYS_FILENAME = "config.sys.json"
PROJECT_CONFIG_USER_FILENAME = "config.user.json"
WORKSPACE_CONFIG_SYS_FILENAME = "config.sys.json"
WORKSPACE_CONFIG_USER_FILENAME = "config.user.json"
INSTALLED_CONFIG_USER_FILENAME = "config.user.json"


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


def installed_templates_dir() -> Path:
    """Return the root directory for the installed template cache.

    Returns:
        Path to the installed template cache directory.

    Example:
        >>> installed_templates_dir().name == TEMPLATES_DIRNAME
        True
    """
    return atelier_data_dir() / TEMPLATES_DIRNAME


def installed_config_path() -> Path:
    """Return the path to the installed defaults config file.

    Returns:
        Path to the installed defaults config file.
    """
    return atelier_data_dir() / INSTALLED_CONFIG_USER_FILENAME


def project_beads_dir(project_dir: Path) -> Path:
    """Return the Beads directory for a project.

    Returns:
        Path to the project-scoped Beads directory.

    Example:
        >>> project_beads_dir(Path(\"/tmp/project\")).name == BEADS_DIRNAME
        True
    """
    return project_dir / BEADS_DIRNAME


def project_worktrees_dir(project_dir: Path) -> Path:
    """Return the worktrees directory for a project."""
    return project_dir / WORKTREES_DIRNAME


def project_skills_dir(project_dir: Path) -> Path:
    """Return the skills directory for a project."""
    return project_dir / SKILLS_DIRNAME


def project_agents_dir(project_dir: Path) -> Path:
    """Return the agents directory for a project."""
    return project_dir / AGENTS_DIRNAME


def installed_legacy_config_path() -> Path:
    """Return the legacy installed defaults config path."""
    return atelier_data_dir() / LEGACY_CONFIG_FILENAME


def project_key(origin: str) -> str:
    """Hash a normalized origin string into a legacy project key.

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
    """Hash a workspace branch name into a legacy workspace key.

    Args:
        branch: Workspace branch name.

    Returns:
        Hex digest workspace key.

    Example:
        >>> len(workspace_key("feat/demo")) == 64
        True
    """
    return hashlib.sha256(branch.encode("utf-8")).hexdigest()


_URL_SAFE_CHARS = set(string.ascii_letters + string.digits + "-._~")


def _short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]


def _normalize_filespace(value: str, *, strip_git: bool) -> str:
    raw = value.strip()
    if strip_git and raw.startswith("git@"):
        raw = raw[len("git@") :]
    if strip_git and raw.lower().endswith(".git"):
        raw = raw[: -len(".git")]
    raw = raw.strip(" .\t\r\n")
    normalized = "".join(char if char in _URL_SAFE_CHARS else "-" for char in raw)
    return normalized.strip(" .\t\r\n")


def legacy_project_dir_name(origin: str) -> str:
    """Return the normalized legacy project directory name for an origin.

    Args:
        origin: Normalized origin string.

    Returns:
        Normalized project directory name with a short hash suffix.

    Example:
        >>> legacy_project_dir_name("git@github.com:org/repo.git").startswith("github.com-org-repo-")
        True
    """
    base = _normalize_filespace(origin, strip_git=True)
    suffix = _short_hash(origin)
    if not base:
        return suffix
    return f"{base}-{suffix}"


def project_dir_name(enlistment_path: str) -> str:
    """Return the normalized project directory name for an enlistment path.

    Args:
        enlistment_path: Absolute path to the local enlistment.

    Returns:
        Normalized project directory name with a short hash suffix.

    Example:
        >>> project_dir_name("/path/to/gumshoe").startswith("gumshoe-")
        True
    """
    base = _normalize_filespace(Path(enlistment_path).name, strip_git=False)
    suffix = _short_hash(enlistment_path)
    if not base:
        return suffix
    return f"{base}-{suffix}"


def legacy_workspace_dir_name(branch: str) -> str:
    """Return the normalized legacy workspace directory name for a branch.

    Args:
        branch: Workspace branch name.

    Returns:
        Normalized workspace directory name with a short hash suffix.

    Example:
        >>> legacy_workspace_dir_name("feat/demo").startswith("feat-demo-")
        True
    """
    base = _normalize_filespace(branch, strip_git=False)
    suffix = _short_hash(branch)
    if not base:
        return suffix
    return f"{base}-{suffix}"


def workspace_dir_name(branch: str, workspace_id: str) -> str:
    """Return the normalized workspace directory name for a workspace ID.

    Args:
        branch: Workspace branch name.
        workspace_id: Full workspace identifier string.

    Returns:
        Normalized workspace directory name with a short hash suffix.

    Example:
        >>> workspace_dir_name("feat/demo", "atelier:/repo:feat/demo").startswith("feat-demo-")
        True
    """
    base = _normalize_filespace(branch, strip_git=False)
    suffix = _short_hash(workspace_id)
    if not base:
        return suffix
    return f"{base}-{suffix}"


def project_dir_for_origin(origin: str) -> Path:
    """Return the legacy project directory for a normalized origin.

    Args:
        origin: Normalized origin string.

    Returns:
        Project directory path.

    Example:
        >>> project_dir_for_origin("github.com/org/repo").parent.name == PROJECTS_DIRNAME
        True
    """
    legacy_dir = projects_root() / project_key(origin)
    if legacy_dir.exists():
        return legacy_dir
    return projects_root() / legacy_project_dir_name(origin)


def project_dir_for_enlistment(enlistment_path: str, origin: str | None) -> Path:
    """Return the project directory for an enlistment path.

    Args:
        enlistment_path: Absolute path to the local enlistment.
        origin: Normalized repo origin string or ``None``.

    Returns:
        Project directory path.

    Example:
        >>> project_dir_for_enlistment("/repo", None).parent.name == PROJECTS_DIRNAME
        True
    """
    if origin:
        legacy_dir = projects_root() / project_key(origin)
        if legacy_dir.exists():
            return legacy_dir
        legacy_short = projects_root() / legacy_project_dir_name(origin)
        if legacy_short.exists():
            return legacy_short
    return projects_root() / project_dir_name(enlistment_path)


def project_config_sys_path(project_dir: Path) -> Path:
    """Return the path to a project's system config file.

    Args:
        project_dir: Project directory path.

    Returns:
        Path to ``config.sys.json``.

    Example:
        >>> project_config_sys_path(Path("/tmp/project")).name == PROJECT_CONFIG_SYS_FILENAME
        True
    """
    return project_dir / PROJECT_CONFIG_SYS_FILENAME


def project_config_user_path(project_dir: Path) -> Path:
    """Return the path to a project's user config file."""
    return project_dir / PROJECT_CONFIG_USER_FILENAME


def project_config_legacy_path(project_dir: Path) -> Path:
    """Return the legacy project config path."""
    return project_dir / LEGACY_CONFIG_FILENAME


def project_config_path(project_dir: Path) -> Path:
    """Return the path to a project's system config file."""
    return project_config_sys_path(project_dir)


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


def workspace_dir_for_branch(
    project_dir: Path, branch: str, workspace_id: str | None
) -> Path:
    """Return the workspace directory path for a branch.

    Args:
        project_dir: Project directory path.
        branch: Workspace branch name.

    Returns:
        Path to the workspace directory.

    Example:
        >>> workspace_dir_for_branch(Path("/tmp/project"), "feat/demo", "atelier:/repo:feat/demo").parent.name == WORKSPACES_DIRNAME
        True
    """
    workspaces_root = workspaces_root_for_project(project_dir)
    legacy_dir = workspaces_root / workspace_key(branch)
    if legacy_dir.exists():
        return legacy_dir
    legacy_short = workspaces_root / legacy_workspace_dir_name(branch)
    if legacy_short.exists():
        return legacy_short
    if not workspace_id:
        raise ValueError("workspace_id is required for workspace directory naming")
    return workspaces_root / workspace_dir_name(branch, workspace_id)


def workspace_config_sys_path(workspace_dir: Path) -> Path:
    """Return the path to a workspace system config file.

    Args:
        workspace_dir: Workspace directory path.

    Returns:
        Path to ``config.sys.json``.

    Example:
        >>> workspace_config_sys_path(Path("/tmp/workspace")).name == WORKSPACE_CONFIG_SYS_FILENAME
        True
    """
    return workspace_dir / WORKSPACE_CONFIG_SYS_FILENAME


def workspace_config_user_path(workspace_dir: Path) -> Path:
    """Return the path to a workspace user config file."""
    return workspace_dir / WORKSPACE_CONFIG_USER_FILENAME


def workspace_config_legacy_path(workspace_dir: Path) -> Path:
    """Return the legacy workspace config path."""
    return workspace_dir / LEGACY_CONFIG_FILENAME


def workspace_config_path(workspace_dir: Path) -> Path:
    """Return the path to a workspace system config file."""
    return workspace_config_sys_path(workspace_dir)


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

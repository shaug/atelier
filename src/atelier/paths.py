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
    return Path(user_data_dir(ATELIER_APP_NAME))


def projects_root() -> Path:
    return atelier_data_dir() / PROJECTS_DIRNAME


def project_key(origin: str) -> str:
    return hashlib.sha256(origin.encode("utf-8")).hexdigest()


def workspace_key(branch: str) -> str:
    return hashlib.sha256(branch.encode("utf-8")).hexdigest()


def project_dir_for_origin(origin: str) -> Path:
    return projects_root() / project_key(origin)


def project_config_path(project_dir: Path) -> Path:
    return project_dir / PROJECT_CONFIG_FILENAME


def workspaces_root_for_project(project_dir: Path) -> Path:
    return project_dir / WORKSPACES_DIRNAME


def workspace_dir_for_branch(project_dir: Path, branch: str) -> Path:
    return workspaces_root_for_project(project_dir) / workspace_key(branch)


def workspace_config_path(workspace_dir: Path) -> Path:
    return workspace_dir / WORKSPACE_CONFIG_FILENAME


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)

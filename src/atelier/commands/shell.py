"""Implementation for the ``atelier shell`` command.

Resolves the workspace repo and opens a shell or command using the configured
defaults and platform detection.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from .. import command as command_util
from .. import config, exec, git, paths, term, workspace
from ..io import die

try:  # pragma: no cover - optional dependency
    import shellingham
except ImportError:  # pragma: no cover - optional dependency
    shellingham = None


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


def _resolve_workspace_repo(workspace_name: str) -> tuple[str, Path, Path, str]:
    if not workspace_name:
        die("workspace branch must not be empty")

    project_root, project_config, enlistment_path = _resolve_project()
    project_enlistment = project_config.project.enlistment or enlistment_path

    normalized = workspace.normalize_workspace_name(str(workspace_name))
    if not normalized:
        die("workspace branch must not be empty")

    git_path = config.resolve_git_path(project_config)

    branch, workspace_dir, exists = workspace.resolve_workspace_target(
        project_root,
        project_config.project.enlistment or enlistment_path,
        normalized,
        project_config.branch.prefix,
        False,
        git_path,
    )
    if not exists:
        die(f"workspace not found: {normalized}")

    repo_dir = workspace_dir / "repo"
    if not repo_dir.exists():
        die(f"workspace repo missing for {branch}")
    if not git.git_is_repo(repo_dir, git_path=git_path):
        die("workspace repo exists but is not a git repository")

    return branch, workspace_dir, repo_dir, project_enlistment


def _looks_like_path(value: str) -> bool:
    if not value:
        return False
    if os.name == "nt":
        if "\\" in value or ":" in value:
            return True
        return value.lower().endswith(".exe")
    return "/" in value


def _detect_shell() -> str | None:
    if shellingham is None:
        return None
    try:
        detected = shellingham.detect_shell()
    except Exception:  # pragma: no cover - best-effort detection
        return None
    if not detected:
        return None
    first, second = detected
    if _looks_like_path(second):
        return second
    if _looks_like_path(first):
        return first
    return second or first


def _fallback_shell() -> str:
    if os.name == "nt":
        return os.environ.get("COMSPEC") or "cmd.exe"
    shell_env = os.environ.get("SHELL")
    if shell_env:
        return shell_env
    if shutil.which("bash"):
        return "bash"
    return "sh"


def _resolve_shell_command(shell_override: str | None) -> list[str]:
    if shell_override:
        normalized = command_util.normalize_command(shell_override)
        if normalized:
            return normalized
        return [str(shell_override)]
    detected = _detect_shell()
    return [detected or _fallback_shell()]


def _run_and_exit(
    cmd: list[str],
    cwd: Path,
    env: dict[str, str],
) -> None:
    result = exec.run_command_status(cmd, cwd=cwd, env=env)
    if result is None:
        die(f"missing required command: {cmd[0]}")
    raise SystemExit(result.returncode)


def open_workspace_shell(args: object, *, require_command: bool = False) -> None:
    """Open a shell in the workspace repo/root or run a command there."""
    workspace_name = getattr(args, "workspace_name", None)
    shell_override = getattr(args, "shell", None)
    command = list(getattr(args, "command", []) or [])
    workspace_root = bool(getattr(args, "workspace_root", False))

    branch, workspace_dir, repo_dir, project_enlistment = _resolve_workspace_repo(
        str(workspace_name or "")
    )
    env = workspace.workspace_environment(
        project_enlistment,
        branch,
        workspace_dir,
    )
    target_dir = workspace_dir if workspace_root else repo_dir
    if bool(getattr(args, "set_title", False)):
        title = term.workspace_title(project_enlistment, branch)
        term.emit_title_escape(title)

    if require_command and not command:
        die("command required for 'atelier exec'")

    if command:
        _run_and_exit(command, target_dir, env)
    _run_and_exit(_resolve_shell_command(shell_override), target_dir, env)

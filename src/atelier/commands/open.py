"""Implementation for the ``atelier open`` command.

``atelier open`` opens a shell in the worktree or runs a command there.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from .. import beads, branching, config, exec, term, workspace, worktrees
from .. import command as command_util
from ..io import die, select
from .resolve import resolve_current_project_with_repo_root

try:  # pragma: no cover - optional dependency
    import shellingham
except ImportError:  # pragma: no cover - optional dependency
    shellingham = None


def _workspace_choice_label(issue: dict[str, object], root_branch: str) -> str:
    status = issue.get("status") or "unknown"
    title = issue.get("title") or ""
    issue_id = issue.get("id") or ""
    return f"{root_branch} [{status}] {title} ({issue_id})"


def _select_epic_by_workspace(
    *,
    workspace_name: str | None,
    raw: bool,
    branch_prefix: str,
    beads_root: Path,
    repo_root: Path,
) -> tuple[dict[str, object], str]:
    if workspace_name:
        candidates = branching.candidates_for_root_branch(workspace_name, branch_prefix, raw)
        matches: list[dict[str, object]] = []
        for candidate in candidates:
            matches.extend(
                beads.find_epics_by_root_branch(candidate, beads_root=beads_root, cwd=repo_root)
            )
        if not matches:
            die(f"no epic found for workspace {workspace_name!r}")
    else:
        matches = beads.run_bd_json(
            ["list", "--label", "at:epic"], beads_root=beads_root, cwd=repo_root
        )
        matches = [
            issue
            for issue in matches
            if beads.extract_workspace_root_branch(issue) is not None
            and str(issue.get("status") or "").lower() in {"", "open", "in_progress", "ready"}
        ]
        if not matches:
            die("no epics with workspace branches found")

    choices: dict[str, dict[str, object]] = {}
    for issue in matches:
        root_branch = beads.extract_workspace_root_branch(issue)
        if not root_branch:
            continue
        label = _workspace_choice_label(issue, root_branch)
        choices[label] = issue

    if not choices:
        die("no eligible epics found for the workspace selection")

    if len(choices) == 1:
        issue = next(iter(choices.values()))
        root_branch = beads.extract_workspace_root_branch(issue) or ""
        return issue, root_branch

    selection = select("Workspace to open", list(choices.keys()))
    issue = choices[selection]
    root_branch = beads.extract_workspace_root_branch(issue) or ""
    return issue, root_branch


def _resolve_worktree_path(
    project_dir: Path,
    repo_root: Path,
    epic_id: str,
    root_branch: str,
    worktree_relpath: str | None,
    *,
    git_path: str | None = None,
) -> Path:
    mapping = worktrees.load_mapping(worktrees.mapping_path(project_dir, epic_id))
    if mapping is None:
        if not worktree_relpath:
            die("worktree not initialized; run 'atelier work' first")
        candidate = Path(worktree_relpath)
        worktree_path = candidate if candidate.is_absolute() else project_dir / candidate
    else:
        mapping = worktrees.ensure_worktree_mapping(
            project_dir,
            epic_id,
            root_branch,
            repo_root=repo_root,
            git_path=git_path,
        )
        worktree_path = project_dir / mapping.worktree_path
    if not worktree_path.exists():
        die("worktree missing; run 'atelier work' first")
    if not (worktree_path / ".git").exists():
        die("worktree path exists but is not a git worktree")
    return worktree_path


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
        return [shell_override]
    detected = _detect_shell()
    return [detected or _fallback_shell()]


def _run_and_exit(cmd: list[str], cwd: Path, env: dict[str, str]) -> None:
    result = exec.run_with_runner(
        exec.CommandRequest(
            argv=tuple(cmd),
            cwd=cwd,
            env=env,
            capture_output=False,
            text=False,
        )
    )
    if result is None:
        die(f"missing required command: {cmd[0]}")
    raise SystemExit(result.returncode)


def open_worktree(args: object) -> None:
    """Open a shell (or run a command) in the selected worktree."""
    workspace_name = getattr(args, "workspace_name", None)
    raw = bool(getattr(args, "raw", False))
    command = list(getattr(args, "command", []) or [])
    shell_override = getattr(args, "shell", None)
    workspace_root = bool(getattr(args, "workspace_root", False))
    set_title = bool(getattr(args, "set_title", False))

    project_root, project_config, enlistment_path, repo_root = (
        resolve_current_project_with_repo_root()
    )
    project_data_dir = config.resolve_project_data_dir(project_root, project_config)
    git_path = config.resolve_git_path(project_config)
    beads_root = config.resolve_beads_root(project_data_dir, repo_root)
    beads.run_bd_command(["prime"], beads_root=beads_root, cwd=repo_root)

    issue, root_branch = _select_epic_by_workspace(
        workspace_name=str(workspace_name) if workspace_name else None,
        raw=raw,
        branch_prefix=project_config.branch.prefix,
        beads_root=beads_root,
        repo_root=repo_root,
    )
    if not root_branch:
        die("selected epic is missing workspace.root_branch")

    worktree_path = _resolve_worktree_path(
        project_data_dir,
        repo_root,
        str(issue.get("id") or ""),
        root_branch,
        beads.extract_worktree_path(issue),
        git_path=git_path,
    )
    project_enlistment = project_config.project.enlistment or enlistment_path
    env = workspace.workspace_environment(project_enlistment, root_branch, worktree_path)
    if set_title:
        title = term.workspace_title(project_enlistment, root_branch)
        term.emit_title_escape(title)

    target_dir = worktree_path if workspace_root else worktree_path

    if command:
        _run_and_exit(command, target_dir, env)
    _run_and_exit(_resolve_shell_command(shell_override), target_dir, env)

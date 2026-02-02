"""Implementation for the ``atelier edit`` command.

``atelier edit`` opens the workspace repo in the configured work editor.
"""

from __future__ import annotations

from pathlib import Path

from .. import beads, branching, config, editor, exec, term, workspace, worktrees
from ..io import die, select
from .resolve import resolve_current_project_with_repo_root


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
        candidates = branching.candidates_for_root_branch(
            workspace_name, branch_prefix, raw
        )
        matches: list[dict[str, object]] = []
        for candidate in candidates:
            matches.extend(
                beads.find_epics_by_root_branch(
                    candidate, beads_root=beads_root, cwd=repo_root
                )
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
            and str(issue.get("status") or "").lower()
            in {"", "open", "in_progress", "ready"}
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


def _resolve_worktree_path(project_dir: Path, epic_id: str, root_branch: str) -> Path:
    mapping = worktrees.load_mapping(worktrees.mapping_path(project_dir, epic_id))
    if mapping is None:
        die("worktree not initialized; run 'atelier work' first")
    if mapping.root_branch and mapping.root_branch != root_branch:
        die("workspace root branch does not match worktree mapping")
    if not mapping.root_branch:
        die("worktree mapping missing root branch")
    worktree_path = project_dir / mapping.worktree_path
    if not worktree_path.exists():
        die("worktree missing; run 'atelier work' first")
    if not (worktree_path / ".git").exists():
        die("worktree path exists but is not a git worktree")
    return worktree_path


def open_workspace_editor(args: object) -> None:
    """Open the workspace repo (or root) in the configured work editor."""
    workspace_name = getattr(args, "workspace_name", None)
    raw = bool(getattr(args, "raw", False))
    workspace_root = bool(getattr(args, "workspace_root", False))
    set_title = bool(getattr(args, "set_title", False))

    project_root, project_config, enlistment_path, repo_root = (
        resolve_current_project_with_repo_root()
    )
    project_data_dir = config.resolve_project_data_dir(project_root, project_config)
    beads_root = config.resolve_beads_root(project_data_dir, repo_root)
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
        project_data_dir, str(issue.get("id") or ""), root_branch
    )
    project_enlistment = project_config.project.enlistment or enlistment_path
    env = workspace.workspace_environment(
        project_enlistment,
        root_branch,
        worktree_path,
    )
    if set_title:
        title = term.workspace_title(project_enlistment, root_branch)
        term.emit_title_escape(title)
    target_dir = worktree_path if workspace_root else worktree_path
    editor_cmd = editor.resolve_editor_command(project_config, role="work")
    exec.run_command_detached([*editor_cmd, str(target_dir)], cwd=target_dir, env=env)

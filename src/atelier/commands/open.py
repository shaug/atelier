"""Implementation for the ``atelier open`` command.

``atelier open`` opens a shell in the worktree or runs a command there.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from .. import beads, branching, changesets, config, exec, lifecycle, term, workspace, worktrees
from .. import command as command_util
from ..io import die, select
from .resolve import resolve_current_project_with_repo_root

try:  # pragma: no cover - optional dependency
    import shellingham
except ImportError:  # pragma: no cover - optional dependency
    shellingham = None

_OPENABLE_CHANGESET_STATUSES = frozenset({"open", "in_progress", "blocked"})


def _issue_id(issue: dict[str, object]) -> str:
    value = issue.get("id")
    return str(value).strip() if value is not None else ""


def _issue_status(issue: dict[str, object]) -> str:
    canonical = lifecycle.canonical_lifecycle_status(issue.get("status"))
    if canonical:
        return canonical
    raw = str(issue.get("status") or "").strip()
    return raw or "unknown"


@dataclass(frozen=True)
class _WorkspaceSelection:
    epic_issue: dict[str, object]
    changeset_issue: dict[str, object]
    epic_id: str
    changeset_id: str
    root_branch: str
    workspace_branch: str
    worktree_relpath: str | None = None


def _list_eligible_epics(*, beads_root: Path, repo_root: Path) -> list[dict[str, object]]:
    issues = beads.list_epics(beads_root=beads_root, cwd=repo_root, include_closed=False)
    return [
        issue
        for issue in issues
        if beads.extract_workspace_root_branch(issue)
        and lifecycle.canonical_lifecycle_status(issue.get("status")) != "closed"
    ]


def _changeset_pr_context(issue: dict[str, object]) -> str | None:
    description = issue.get("description")
    metadata = changesets.parse_review_metadata(description if isinstance(description, str) else "")
    parts: list[str] = []
    if metadata.pr_number:
        parts.append(f"#{metadata.pr_number}")
    normalized_state = lifecycle.normalize_review_state(metadata.pr_state)
    if normalized_state:
        parts.append(normalized_state)
    elif metadata.pr_state:
        cleaned = metadata.pr_state.strip()
        if cleaned:
            parts.append(cleaned)
    if metadata.pr_url:
        parts.append(metadata.pr_url)
    if not parts:
        return None
    return " ".join(parts)


def _workspace_choice_label(selection: _WorkspaceSelection) -> str:
    status = _issue_status(selection.changeset_issue)
    title = str(selection.changeset_issue.get("title") or "").strip() or "(untitled)"
    label = f"{selection.changeset_id} [{status}] {title} ({selection.workspace_branch})"
    pr_context = _changeset_pr_context(selection.changeset_issue)
    if pr_context:
        return f"{label} - PR {pr_context}"
    return label


def _is_openable_changeset(issue: dict[str, object]) -> bool:
    return _issue_status(issue) in _OPENABLE_CHANGESET_STATUSES


def _list_openable_changesets(
    *,
    project_dir: Path,
    beads_root: Path,
    repo_root: Path,
) -> list[_WorkspaceSelection]:
    selections: list[_WorkspaceSelection] = []
    for epic_issue in _list_eligible_epics(beads_root=beads_root, repo_root=repo_root):
        root_branch = beads.extract_workspace_root_branch(epic_issue)
        if not root_branch:
            continue
        epic_id = _issue_id(epic_issue)
        if not epic_id:
            continue

        mapping = worktrees.load_mapping(worktrees.mapping_path(project_dir, epic_id))
        work_children = beads.list_work_children(
            epic_id,
            beads_root=beads_root,
            cwd=repo_root,
            include_closed=True,
        )
        if work_children:
            candidate_issues = beads.list_descendant_changesets(
                epic_id,
                beads_root=beads_root,
                cwd=repo_root,
                include_closed=True,
            )
        else:
            candidate_issues = [epic_issue]

        for changeset_issue in candidate_issues:
            changeset_id = _issue_id(changeset_issue)
            if not changeset_id or not _is_openable_changeset(changeset_issue):
                continue
            workspace_branch = mapping.changesets.get(changeset_id) if mapping is not None else None
            if not workspace_branch and changeset_id == epic_id:
                workspace_branch = root_branch
            if not workspace_branch:
                continue

            worktree_relpath: str | None = None
            if mapping is not None:
                if changeset_id == epic_id:
                    worktree_relpath = mapping.worktree_path
                else:
                    worktree_relpath = mapping.changeset_worktrees.get(changeset_id)
            if not worktree_relpath and changeset_id == epic_id:
                worktree_relpath = beads.extract_worktree_path(epic_issue)
            if changeset_id != epic_id and not worktree_relpath:
                continue

            selections.append(
                _WorkspaceSelection(
                    epic_issue=epic_issue,
                    changeset_issue=changeset_issue,
                    epic_id=epic_id,
                    changeset_id=changeset_id,
                    root_branch=root_branch,
                    workspace_branch=workspace_branch,
                    worktree_relpath=worktree_relpath,
                )
            )

    deduped: dict[tuple[str, str], _WorkspaceSelection] = {}
    for selection in selections:
        deduped[(selection.epic_id, selection.changeset_id)] = selection
    return sorted(
        deduped.values(),
        key=lambda selection: (
            selection.changeset_id,
            selection.workspace_branch,
            selection.epic_id,
        ),
    )


def _known_changeset_values(selections: list[_WorkspaceSelection]) -> tuple[str, str]:
    known_ids = sorted({selection.changeset_id for selection in selections})
    known_branches = sorted(
        {selection.workspace_branch for selection in selections}
        | {selection.root_branch for selection in selections}
    )
    id_text = ", ".join(known_ids[:8]) if known_ids else "(none)"
    branch_text = ", ".join(known_branches[:8]) if known_branches else "(none)"
    return id_text, branch_text


def _unmapped_input_message(workspace_name: str, selections: list[_WorkspaceSelection]) -> str:
    id_text, branch_text = _known_changeset_values(selections)
    first = next(iter(sorted({selection.changeset_id for selection in selections})), None)
    example = first or "<changeset-id>"
    return (
        f"no mapped active changeset found for input {workspace_name!r}. "
        f"try an explicit changeset id (for example: atelier open {example}). "
        f"known changeset ids: {id_text}. known changeset/workspace branches: {branch_text}"
    )


def _ambiguous_input_message(workspace_name: str, matches: list[_WorkspaceSelection]) -> str:
    details = ", ".join(
        f"{selection.changeset_id} ({selection.workspace_branch})"
        for selection in sorted(
            matches,
            key=lambda selection: (
                selection.changeset_id,
                selection.workspace_branch,
                selection.epic_id,
            ),
        )[:8]
    )
    return (
        f"input {workspace_name!r} matches multiple changesets: {details}. "
        "specify a changeset id explicitly (for example: atelier open <changeset-id>)"
    )


def _select_changeset_by_workspace(
    *,
    project_dir: Path,
    workspace_name: str | None,
    raw: bool,
    branch_prefix: str,
    beads_root: Path,
    repo_root: Path,
) -> _WorkspaceSelection:
    selections = _list_openable_changesets(
        project_dir=project_dir,
        beads_root=beads_root,
        repo_root=repo_root,
    )
    if not selections:
        die("no mapped open/in_progress/blocked changesets found")

    if workspace_name:
        direct_matches = [
            selection for selection in selections if selection.changeset_id == workspace_name
        ]
        if len(direct_matches) == 1:
            return direct_matches[0]
        if len(direct_matches) > 1:
            die(_ambiguous_input_message(workspace_name, direct_matches))

        candidates = branching.candidates_for_root_branch(workspace_name, branch_prefix, raw)
        candidate_set = {candidate for candidate in candidates if candidate}
        matches: dict[tuple[str, str], _WorkspaceSelection] = {}
        for selection in selections:
            if (
                selection.workspace_branch in candidate_set
                or selection.root_branch in candidate_set
            ):
                matches[(selection.epic_id, selection.changeset_id)] = selection

        if not matches:
            die(_unmapped_input_message(workspace_name, selections))

        resolved = sorted(
            matches.values(),
            key=lambda selection: (
                selection.changeset_id,
                selection.workspace_branch,
                selection.epic_id,
            ),
        )
        if len(resolved) > 1:
            die(_ambiguous_input_message(workspace_name, resolved))
        return resolved[0]

    choices: dict[str, _WorkspaceSelection] = {}
    for selection in selections:
        label = _workspace_choice_label(selection)
        choices[label] = selection

    if len(choices) == 1:
        return next(iter(choices.values()))

    selected = select("Changeset to open", list(choices.keys()))
    return choices[selected]


def _select_epic_by_workspace(
    *,
    project_dir: Path,
    workspace_name: str | None,
    raw: bool,
    branch_prefix: str,
    beads_root: Path,
    repo_root: Path,
) -> _WorkspaceSelection:
    """Backwards-compatible shim for legacy call sites and tests."""
    return _select_changeset_by_workspace(
        project_dir=project_dir,
        workspace_name=workspace_name,
        raw=raw,
        branch_prefix=branch_prefix,
        beads_root=beads_root,
        repo_root=repo_root,
    )


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
    else:
        mapping = worktrees.ensure_worktree_mapping(
            project_dir,
            epic_id,
            root_branch,
            repo_root=repo_root,
            git_path=git_path,
        )
    target_relpath = worktree_relpath
    if not target_relpath and mapping is not None:
        target_relpath = mapping.worktree_path
    if not target_relpath:
        die("worktree not initialized; run 'atelier work' first")
    candidate = Path(target_relpath)
    worktree_path = candidate if candidate.is_absolute() else project_dir / candidate
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

    selection = _select_changeset_by_workspace(
        project_dir=project_data_dir,
        workspace_name=str(workspace_name) if workspace_name else None,
        raw=raw,
        branch_prefix=project_config.branch.prefix,
        beads_root=beads_root,
        repo_root=repo_root,
    )
    if not selection.root_branch:
        die("selected changeset is missing workspace.root_branch")

    worktree_path = _resolve_worktree_path(
        project_data_dir,
        repo_root,
        selection.epic_id,
        selection.root_branch,
        selection.worktree_relpath,
        git_path=git_path,
    )
    project_enlistment = project_config.project.enlistment or enlistment_path
    env = workspace.workspace_environment(
        project_enlistment,
        selection.workspace_branch,
        worktree_path,
    )
    if set_title:
        title = term.workspace_title(project_enlistment, selection.workspace_branch)
        term.emit_title_escape(title)

    target_dir = worktree_path if workspace_root else worktree_path

    if command:
        _run_and_exit(command, target_dir, env)
    _run_and_exit(_resolve_shell_command(shell_override), target_dir, env)

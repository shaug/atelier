"""Implementation for the ``atelier describe`` command."""

from __future__ import annotations

import json
from pathlib import Path

from rich import box
from rich.console import Console
from rich.table import Table

from .. import config, git, paths, workspace
from ..io import die, say, warn

_FORMATS = {"table", "json"}


def describe(args: object) -> None:
    """Describe project or workspace status."""
    workspace_name = getattr(args, "workspace_name", None)
    finalized = bool(getattr(args, "finalized", False))
    no_finalized = bool(getattr(args, "no_finalized", False))
    format_value = str(getattr(args, "format", "table") or "table").lower()

    if finalized and no_finalized:
        die("cannot combine --finalized and --no-finalized")
    if format_value not in _FORMATS:
        die(f"unsupported format: {format_value}")

    project_root, project_config, enlistment_path, repo_root = _resolve_project()
    git_path = config.resolve_git_path(project_config)

    if workspace_name:
        _describe_workspace(
            str(workspace_name),
            project_root,
            project_config,
            enlistment_path,
            repo_root,
            git_path,
            format_value,
            finalized=finalized,
            no_finalized=no_finalized,
        )
        return

    _describe_project(
        project_root,
        project_config,
        enlistment_path,
        repo_root,
        git_path,
        format_value,
        finalized=finalized,
        no_finalized=no_finalized,
    )


def _resolve_project() -> tuple[Path, config.ProjectConfig, str, Path]:
    cwd = Path.cwd()
    repo_root, enlistment_path, _, origin = git.resolve_repo_enlistment(cwd)
    project_root = paths.project_dir_for_enlistment(enlistment_path, origin)
    config_path = paths.project_config_path(project_root)
    config_payload = config.load_project_config(config_path)
    if not config_payload:
        die("no Atelier project config found for this repo; run 'atelier init'")
    project_enlistment = config_payload.project.enlistment
    if project_enlistment and project_enlistment != enlistment_path:
        die("project enlistment does not match current repo path")
    return project_root, config_payload, enlistment_path, repo_root


def _describe_project(
    project_root: Path,
    project_config: config.ProjectConfig,
    enlistment_path: str,
    repo_root: Path,
    git_path: str | None,
    format_value: str,
    *,
    finalized: bool,
    no_finalized: bool,
) -> None:
    workspaces = workspace.collect_workspaces(
        project_root,
        project_config,
        with_status=True,
        enlistment_repo_dir=repo_root,
        git_path=git_path,
    )
    workspaces = sorted(workspaces, key=lambda item: item.get("name", ""))
    filtered = _apply_finalized_filter(workspaces, finalized, no_finalized)
    summaries = [_workspace_summary(item) for item in filtered]
    counts = _status_counts(summaries)
    project_info = _project_info(
        project_root,
        project_config,
        enlistment_path,
        repo_root,
        git_path,
    )
    payload = {
        "scope": "project",
        "project": project_info,
        "filters": {"finalized": finalized, "no_finalized": no_finalized},
        "counts": counts,
        "workspaces": summaries,
    }
    if format_value == "json":
        _emit_json(payload)
        return
    _render_project_table(project_info, summaries, counts)


def _describe_workspace(
    workspace_name: str,
    project_root: Path,
    project_config: config.ProjectConfig,
    enlistment_path: str,
    repo_root: Path,
    git_path: str | None,
    format_value: str,
    *,
    finalized: bool,
    no_finalized: bool,
) -> None:
    normalized = workspace.normalize_workspace_name(workspace_name)
    if not normalized:
        die("workspace branch must not be empty")

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
    repo_available = False
    if repo_dir.exists() and git.git_is_repo(repo_dir, git_path=git_path):
        repo_available = True
    elif repo_dir.exists():
        warn("workspace repo exists but is not a git repository")
    else:
        warn("workspace repo missing; status data omitted")

    workspace_config = config.load_workspace_config(
        paths.workspace_config_path(workspace_dir)
    )

    detail = _workspace_detail(
        branch,
        workspace_dir,
        repo_dir if repo_available else None,
        repo_root,
        git_path,
        workspace_config,
    )

    if finalized and detail.get("finalized") is not True:
        die("workspace is not finalized")
    if no_finalized and detail.get("finalized") is True:
        die("workspace is finalized")

    project_info = _project_info(
        project_root,
        project_config,
        enlistment_path,
        repo_root,
        git_path,
    )
    payload = {
        "scope": "workspace",
        "project": project_info,
        "workspace": detail,
    }
    if format_value == "json":
        _emit_json(payload)
        return
    _render_workspace_table(project_info, detail)


def _project_info(
    project_root: Path,
    project_config: config.ProjectConfig,
    enlistment_path: str,
    repo_root: Path,
    git_path: str | None,
) -> dict[str, object]:
    project_section = project_config.project
    mainline_branch = None
    if git.git_is_repo(repo_root, git_path=git_path):
        mainline_branch = git.git_default_branch(repo_root, git_path=git_path)
    return {
        "project_dir": str(project_root),
        "repo_root": str(repo_root),
        "enlistment": project_section.enlistment or enlistment_path,
        "origin": project_section.origin,
        "repo_url": project_section.repo_url,
        "branch_prefix": project_config.branch.prefix,
        "branch_pr": project_config.branch.pr,
        "branch_history": project_config.branch.history,
        "allow_mainline_workspace": project_section.allow_mainline_workspace,
        "provider": project_section.provider,
        "provider_url": project_section.provider_url,
        "owner": project_section.owner,
        "mainline_branch": mainline_branch,
    }


def _workspace_summary(item: dict) -> dict[str, object]:
    return {
        "name": item.get("name"),
        "branch": item.get("branch"),
        "path": str(item.get("path")) if item.get("path") is not None else None,
        "repo_dir": str(item.get("repo_dir"))
        if item.get("repo_dir") is not None
        else None,
        "checked_out": item.get("checked_out"),
        "clean": item.get("clean"),
        "pushed": item.get("pushed"),
        "finalized": item.get("finalized"),
    }


def _workspace_detail(
    branch: str,
    workspace_dir: Path,
    repo_dir: Path | None,
    repo_root: Path,
    git_path: str | None,
    workspace_config: config.WorkspaceConfig | None,
) -> dict[str, object]:
    checked_out = None
    clean = None
    pushed = None
    finalized = None
    mainline_branch = None
    ahead = None
    behind = None
    diff_stat: list[str] = []
    last_commit: dict[str, object] | None = None

    if repo_dir is not None:
        current_branch = git.git_current_branch(repo_dir, git_path=git_path)
        checked_out = current_branch == branch if current_branch else None
        clean = git.git_is_clean(repo_dir, git_path=git_path)
        pushed = git.git_has_remote_branch(repo_dir, branch, git_path=git_path)
        finalization_tag = workspace.finalization_tag_name(branch)
        finalized = git.git_tag_exists(repo_dir, finalization_tag, git_path=git_path)
        if finalized is not True:
            finalized = git.git_tag_exists(
                repo_root, finalization_tag, git_path=git_path
            )
        mainline_branch = git.git_default_branch(repo_dir, git_path=git_path)
        if mainline_branch:
            ahead = git.git_commits_ahead(
                repo_dir, mainline_branch, branch, git_path=git_path
            )
            behind = git.git_commits_ahead(
                repo_dir, branch, mainline_branch, git_path=git_path
            )
            diff_stat = git.git_diff_stat(
                repo_dir, mainline_branch, branch, git_path=git_path
            )
        last_commit = git.git_last_commit(repo_dir, branch, git_path=git_path)

    return {
        "name": branch,
        "branch": branch,
        "path": str(workspace_dir),
        "repo_dir": str(repo_dir) if repo_dir is not None else None,
        "repo_available": repo_dir is not None,
        "checked_out": checked_out,
        "clean": clean,
        "dirty": None if clean is None else not clean,
        "pushed": pushed,
        "finalized": finalized,
        "mainline": {
            "branch": mainline_branch,
            "ahead": ahead,
            "behind": behind,
            "diffstat": diff_stat,
        },
        "last_commit": last_commit,
        "session": _workspace_session(workspace_config),
    }


def _workspace_session(
    workspace_config: config.WorkspaceConfig | None,
) -> dict[str, object] | None:
    if workspace_config is None:
        return None
    session = workspace_config.workspace.session
    if session is None:
        return None
    return {
        "agent": session.agent,
        "id": session.id,
        "resume_command": session.resume_command,
    }


def _apply_finalized_filter(
    workspaces: list[dict], finalized: bool, no_finalized: bool
) -> list[dict]:
    if finalized:
        return [item for item in workspaces if item.get("finalized") is True]
    if no_finalized:
        return [item for item in workspaces if item.get("finalized") is not True]
    return list(workspaces)


def _status_counts(workspaces: list[dict]) -> dict[str, int]:
    def count(key: str, value: bool) -> int:
        return sum(1 for item in workspaces if item.get(key) is value)

    return {
        "workspaces": len(workspaces),
        "checked_out": count("checked_out", True),
        "clean": count("clean", True),
        "dirty": count("clean", False),
        "pushed": count("pushed", True),
        "finalized": count("finalized", True),
    }


def _emit_json(payload: dict) -> None:
    say(json.dumps(payload, indent=2, sort_keys=True))


def _display_value(value: object) -> str:
    if value is None:
        return "unknown"
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def _render_project_table(
    project_info: dict[str, object],
    workspaces: list[dict[str, object]],
    counts: dict[str, int],
) -> None:
    console = Console()

    overview = Table(title="Project Overview", box=box.SIMPLE, show_header=False)
    overview.add_column("Field", style="bold")
    overview.add_column("Value", overflow="fold")
    overview.add_row("Enlistment", _display_value(project_info.get("enlistment")))
    overview.add_row("Project dir", _display_value(project_info.get("project_dir")))
    overview.add_row("Repo root", _display_value(project_info.get("repo_root")))
    overview.add_row("Origin", _display_value(project_info.get("origin")))
    overview.add_row("Repo URL", _display_value(project_info.get("repo_url")))
    overview.add_row("Branch prefix", _display_value(project_info.get("branch_prefix")))
    overview.add_row("Branch PRs", _display_value(project_info.get("branch_pr")))
    overview.add_row(
        "Branch history", _display_value(project_info.get("branch_history"))
    )
    overview.add_row(
        "Allow mainline", _display_value(project_info.get("allow_mainline_workspace"))
    )
    overview.add_row(
        "Mainline branch", _display_value(project_info.get("mainline_branch"))
    )
    overview.add_row("Workspaces", _display_value(counts.get("workspaces")))
    overview.add_row("Finalized", _display_value(counts.get("finalized")))
    overview.add_row("Checked out", _display_value(counts.get("checked_out")))
    overview.add_row("Clean", _display_value(counts.get("clean")))
    overview.add_row("Dirty", _display_value(counts.get("dirty")))
    overview.add_row("Pushed", _display_value(counts.get("pushed")))
    console.print(overview)

    if not workspaces:
        console.print("No workspaces found.")
        return

    table = Table(title="Workspaces", box=box.SIMPLE)
    table.add_column("Workspace", no_wrap=True)
    table.add_column("Checked out", justify="center")
    table.add_column("Clean", justify="center")
    table.add_column("Pushed", justify="center")
    table.add_column("Finalized", justify="center")
    for item in workspaces:
        table.add_row(
            str(item.get("name", "")),
            workspace.format_status(item.get("checked_out")),
            workspace.format_status(item.get("clean")),
            workspace.format_status(item.get("pushed")),
            workspace.format_status(item.get("finalized")),
        )
    console.print(table)


def _render_workspace_table(
    project_info: dict[str, object],
    detail: dict[str, object],
) -> None:
    console = Console()

    project_table = Table(title="Project", box=box.SIMPLE, show_header=False)
    project_table.add_column("Field", style="bold")
    project_table.add_column("Value", overflow="fold")
    project_table.add_row("Enlistment", _display_value(project_info.get("enlistment")))
    project_table.add_row(
        "Project dir", _display_value(project_info.get("project_dir"))
    )
    project_table.add_row("Repo root", _display_value(project_info.get("repo_root")))
    project_table.add_row(
        "Mainline branch", _display_value(project_info.get("mainline_branch"))
    )
    console.print(project_table)

    workspace_table = Table(title="Workspace", box=box.SIMPLE, show_header=False)
    workspace_table.add_column("Field", style="bold")
    workspace_table.add_column("Value", overflow="fold")
    workspace_table.add_row("Name", _display_value(detail.get("name")))
    workspace_table.add_row("Path", _display_value(detail.get("path")))
    workspace_table.add_row("Repo", _display_value(detail.get("repo_dir")))
    workspace_table.add_row(
        "Checked out", workspace.format_status(detail.get("checked_out"))
    )
    workspace_table.add_row("Clean", workspace.format_status(detail.get("clean")))
    workspace_table.add_row("Pushed", workspace.format_status(detail.get("pushed")))
    workspace_table.add_row(
        "Finalized", workspace.format_status(detail.get("finalized"))
    )
    workspace_table.add_row("Last commit", _format_commit(detail.get("last_commit")))
    console.print(workspace_table)

    mainline = detail.get("mainline") or {}
    mainline_table = Table(
        title="Mainline Comparison", box=box.SIMPLE, show_header=False
    )
    mainline_table.add_column("Field", style="bold")
    mainline_table.add_column("Value", overflow="fold")
    mainline_table.add_row("Mainline", _display_value(mainline.get("branch")))
    mainline_table.add_row("Commits ahead", _display_value(mainline.get("ahead")))
    mainline_table.add_row("Commits behind", _display_value(mainline.get("behind")))
    console.print(mainline_table)

    diff_stat = mainline.get("diffstat") or []
    if diff_stat:
        diff_table = Table(title="Diffstat", box=box.SIMPLE, show_header=False)
        diff_table.add_column("Line", overflow="fold")
        for line in diff_stat:
            diff_table.add_row(str(line))
        console.print(diff_table)


def _format_commit(value: object) -> str:
    if not isinstance(value, dict):
        return "unknown"
    short_hash = value.get("short_hash") or value.get("hash") or ""
    subject = value.get("subject") or ""
    if short_hash and subject:
        return f"{short_hash} {subject}"
    if short_hash:
        return str(short_hash)
    if subject:
        return str(subject)
    return "unknown"

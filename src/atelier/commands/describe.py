"""Implementation for the ``atelier describe`` command."""

from __future__ import annotations

import json
from pathlib import Path

from rich import box
from rich.console import Console
from rich.table import Table

from .. import config, git, paths, workspace
from ..io import die, say, warn
from .resolve import (
    resolve_current_project_with_repo_root,
    resolve_workspace_target,
)

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

    project_root, project_config, enlistment_path, repo_root = (
        resolve_current_project_with_repo_root()
    )
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
    branch, workspace_dir = resolve_workspace_target(
        project_root=project_root,
        project_config=project_config,
        enlistment_path=enlistment_path,
        workspace_name=workspace_name,
        raw=False,
        git_path=git_path,
    )

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

    branch_pr, branch_history = _resolve_publish_settings(
        project_config, workspace_config
    )

    detail = _workspace_detail(
        branch,
        workspace_dir,
        repo_dir if repo_available else None,
        repo_root,
        git_path,
        workspace_config,
        branch_pr,
        branch_history,
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
    state = _derive_workspace_state(
        finalized=item.get("finalized"),
        repo_available=item.get("repo_available"),
        branch_pr=item.get("branch_pr"),
        branch_history=item.get("branch_history"),
        pushed=item.get("pushed"),
        committed_work=item.get("committed_work"),
        mainline=item.get("mainline"),
    )
    return {
        "name": item.get("name"),
        "branch": item.get("branch"),
        "path": str(item.get("path")) if item.get("path") is not None else None,
        "repo_dir": str(item.get("repo_dir"))
        if item.get("repo_dir") is not None
        else None,
        "repo_available": item.get("repo_available"),
        "branch_pr": item.get("branch_pr"),
        "branch_history": item.get("branch_history"),
        "checked_out": item.get("checked_out"),
        "clean": item.get("clean"),
        "pushed": item.get("pushed"),
        "finalized": item.get("finalized"),
        "base": item.get("base"),
        "work_commits": item.get("work_commits"),
        "committed_work": item.get("committed_work"),
        "state": state,
        "mainline": item.get("mainline"),
    }


def _workspace_detail(
    branch: str,
    workspace_dir: Path,
    repo_dir: Path | None,
    repo_root: Path,
    git_path: str | None,
    workspace_config: config.WorkspaceConfig | None,
    branch_pr: bool | None,
    branch_history: str | None,
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
    base = workspace.workspace_base_payload(workspace_config)
    work_commits: int | None = None
    committed_work: bool | None = None

    if repo_dir is not None:
        current_branch = git.git_current_branch(repo_dir, git_path=git_path)
        checked_out = current_branch == branch if current_branch else None
        clean = git.git_is_clean(repo_dir, git_path=git_path)
        if branch_pr is True:
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
        base_sha = base.get("sha") if base else None
        work_commits, committed_work = workspace.workspace_committed_work(
            repo_dir,
            branch,
            base_sha,
            git_path=git_path,
        )
        last_commit = git.git_last_commit(repo_dir, branch, git_path=git_path)

    state = _derive_workspace_state(
        finalized=finalized,
        repo_available=repo_dir is not None,
        branch_pr=branch_pr,
        branch_history=branch_history,
        pushed=pushed,
        committed_work=committed_work,
        mainline={
            "branch": mainline_branch,
            "ahead": ahead,
            "behind": behind,
        },
    )

    return {
        "name": branch,
        "branch": branch,
        "path": str(workspace_dir),
        "repo_dir": str(repo_dir) if repo_dir is not None else None,
        "repo_available": repo_dir is not None,
        "branch_pr": branch_pr,
        "branch_history": branch_history,
        "checked_out": checked_out,
        "clean": clean,
        "dirty": None if clean is None else not clean,
        "pushed": pushed,
        "finalized": finalized,
        "base": base,
        "work_commits": work_commits,
        "committed_work": committed_work,
        "state": state,
        "mainline": {
            "branch": mainline_branch,
            "ahead": ahead,
            "behind": behind,
            "diffstat": diff_stat,
        },
        "last_commit": last_commit,
        "session": _workspace_session(workspace_config),
    }


def _resolve_publish_settings(
    project_config: config.ProjectConfig,
    workspace_config: config.WorkspaceConfig | None,
) -> tuple[bool | None, str | None]:
    branch_pr = None
    branch_history = None
    if workspace_config is not None:
        branch_pr = workspace_config.workspace.branch_pr
        branch_history = workspace_config.workspace.branch_history
    if branch_pr is None:
        branch_pr = project_config.branch.pr
    if branch_history is None:
        branch_history = project_config.branch.history
    return branch_pr, branch_history


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


def _format_publish_mode(branch_pr: bool | None, branch_history: str | None) -> str:
    if branch_pr is None and branch_history is None:
        return "unknown"
    if branch_pr is None:
        pr_label = "unknown"
    else:
        pr_label = "pr" if branch_pr else "direct"
    if branch_history:
        return f"{pr_label}, {branch_history}"
    return pr_label


def _derive_workspace_state(
    *,
    finalized: bool | None,
    repo_available: bool | None,
    branch_pr: bool | None,
    branch_history: str | None,
    pushed: bool | None,
    committed_work: bool | None,
    mainline: dict[str, object] | None,
) -> str:
    if finalized is True:
        return "finalized"
    if repo_available is False:
        return "repo missing"
    if mainline is None:
        return "unknown"
    ahead = mainline.get("ahead")
    behind = mainline.get("behind")
    if not isinstance(ahead, int) or not isinstance(behind, int):
        return "unknown"
    history = branch_history or "manual"
    needs_rebase = history in {"rebase", "squash"} and behind > 0
    if branch_pr is True:
        if ahead > 0 and pushed is False:
            return "needs push"
        if needs_rebase:
            return "needs rebase"
        if ahead == 0:
            return "no changes"
        return "ready for pr"
    if ahead == 0:
        if needs_rebase:
            return "needs rebase"
        if committed_work is True:
            return "work done"
        return "no changes"
    if needs_rebase:
        return "needs rebase"
    return "needs integration"


def _render_project_table(
    project_info: dict[str, object],
    workspaces: list[dict[str, object]],
    counts: dict[str, int],
) -> None:
    console = Console()

    def resolve_branch_pr(item: dict[str, object]) -> bool | None:
        value = item.get("branch_pr")
        if value is None:
            value = project_info.get("branch_pr")
        return value

    show_pushed = any(resolve_branch_pr(item) is True for item in workspaces)

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
    if show_pushed:
        overview.add_row("Pushed", _display_value(counts.get("pushed")))
    console.print(overview)

    if not workspaces:
        console.print("No workspaces found.")
        return

    table = Table(title="Workspaces", box=box.SIMPLE)
    table.add_column("Workspace", no_wrap=True)
    table.add_column("State", no_wrap=True)
    table.add_column("Work", justify="center")
    table.add_column("Finalized", justify="center")
    table.add_column("Checked out", justify="center")
    table.add_column("Clean", justify="center")
    if show_pushed:
        table.add_column("Pushed", justify="center")
    for item in workspaces:
        finalized = item.get("finalized") is True
        branch_pr = resolve_branch_pr(item) is True
        table.add_row(
            str(item.get("name", "")),
            _display_value(item.get("state")),
            workspace.format_status(item.get("committed_work")),
            workspace.format_status(item.get("finalized")),
            "" if finalized else workspace.format_status(item.get("checked_out")),
            "" if finalized else workspace.format_status(item.get("clean")),
            *(
                [
                    ""
                    if finalized or not branch_pr
                    else workspace.format_status(item.get("pushed"))
                ]
                if show_pushed
                else []
            ),
        )
    console.print(table)


def _render_workspace_table(
    project_info: dict[str, object],
    detail: dict[str, object],
) -> None:
    console = Console()
    finalized = detail.get("finalized") is True
    branch_pr = detail.get("branch_pr")
    if branch_pr is None:
        branch_pr = project_info.get("branch_pr")
    branch_history = detail.get("branch_history")
    if branch_history is None:
        branch_history = project_info.get("branch_history")

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
    workspace_table.add_row("Publish", _format_publish_mode(branch_pr, branch_history))
    workspace_table.add_row(
        "Finalized", workspace.format_status(detail.get("finalized"))
    )
    if detail.get("base") is not None:
        workspace_table.add_row("Starting point", _format_base(detail.get("base")))
    workspace_table.add_row("State", _display_value(detail.get("state")))
    workspace_table.add_row(
        "Committed work", workspace.format_status(detail.get("committed_work"))
    )
    if detail.get("work_commits") is not None:
        workspace_table.add_row(
            "Work commits", _display_value(detail.get("work_commits"))
        )
    if not finalized:
        workspace_table.add_row(
            "Checked out", workspace.format_status(detail.get("checked_out"))
        )
        workspace_table.add_row("Clean", workspace.format_status(detail.get("clean")))
        if branch_pr is True:
            workspace_table.add_row(
                "Pushed", workspace.format_status(detail.get("pushed"))
            )
        workspace_table.add_row(
            "Last commit", _format_commit(detail.get("last_commit"))
        )
    console.print(workspace_table)

    if finalized:
        return

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


def _format_base(value: object) -> str:
    if not isinstance(value, dict):
        return "unknown"
    branch = value.get("default_branch") or ""
    sha = value.get("sha") or ""
    short_sha = sha[:8] if isinstance(sha, str) and sha else ""
    if branch and short_sha:
        return f"{branch}@{short_sha}"
    if branch:
        return str(branch)
    if short_sha:
        return str(short_sha)
    return "unknown"

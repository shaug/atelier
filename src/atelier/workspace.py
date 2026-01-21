"""Workspace helpers for locating, creating, and summarizing workspaces."""

import concurrent.futures
import datetime as dt
from pathlib import Path

from . import __version__, config, git, templates
from .io import die, link_or_copy, warn
from .paths import (
    TEMPLATES_DIRNAME,
    WORKSPACES_DIRNAME,
    workspace_config_path,
    workspace_dir_for_branch,
)

BACKGROUND_COMMIT_LIMIT = 20


def workspace_identifier(project_enlistment: str, workspace_branch: str) -> str:
    """Build the stable workspace identifier string.

    Args:
        project_enlistment: Absolute path to the local enlistment.
        workspace_branch: Workspace branch name.

    Returns:
        Workspace identifier string (``atelier:<enlistment-path>:<branch>``).

    Example:
        >>> workspace_identifier("/repo", "feat/demo")
        'atelier:/repo:feat/demo'
    """
    enlistment = project_enlistment
    branch = workspace_branch.lstrip("/")
    return f"atelier:{enlistment}:{branch}"


def workspace_candidate_branches(name: str, branch_prefix: str, raw: bool) -> list[str]:
    """Generate candidate branch names for a workspace lookup.

    Args:
        name: Workspace name input.
        branch_prefix: Prefix to prepend when ``raw`` is false.
        raw: When true, do not apply the prefix.

    Returns:
        List of candidate branch names.

    Example:
        >>> workspace_candidate_branches("feat/demo", "scott/", False)
        ['scott/feat/demo', 'feat/demo']
    """
    if raw:
        return [name]
    if branch_prefix and name.startswith(branch_prefix):
        return [name]
    candidates = []
    prefixed = f"{branch_prefix}{name}"
    if prefixed:
        candidates.append(prefixed)
    if name and name not in candidates:
        candidates.append(name)
    return candidates


def find_workspace_for_branch(
    project_dir: Path, project_enlistment: str, branch: str
) -> tuple[Path, config.WorkspaceConfig] | None:
    """Find an existing workspace directory and config for a branch.

    Args:
        project_dir: Project directory path.
        project_enlistment: Absolute path to the local enlistment.
        branch: Workspace branch name.

    Returns:
        Tuple of ``(workspace_dir, workspace_config)`` or ``None`` if missing.

    Example:
        >>> find_workspace_for_branch(Path("/tmp/project"), "feat/demo") is None
        True
    """
    workspace_id = workspace_identifier(project_enlistment, branch)
    workspace_dir = workspace_dir_for_branch(project_dir, branch, workspace_id)
    config_path = workspace_config_path(workspace_dir)
    if not config_path.exists():
        if workspace_dir.exists():
            die("workspace config missing for existing workspace directory")
        return None
    payload = config.load_workspace_config(config_path)
    if not payload:
        die("failed to load workspace config")
    stored_branch = payload.workspace.branch
    if stored_branch != branch:
        die("workspace branch does not match workspace directory")
    return workspace_dir, payload


def resolve_workspace_target(
    project_dir: Path,
    project_enlistment: str,
    name: str,
    branch_prefix: str,
    raw: bool,
) -> tuple[str, Path, bool]:
    """Resolve the target workspace branch and directory.

    Args:
        project_dir: Project directory path.
        project_enlistment: Absolute path to the local enlistment.
        name: Workspace branch input.
        branch_prefix: Prefix to apply when ``raw`` is false.
        raw: When true, use the name as-is.

    Returns:
        Tuple of ``(branch, workspace_dir, exists)`` where ``exists`` indicates
        whether a matching workspace config was found.

    Example:
        >>> resolve_workspace_target(Path("/tmp/project"), "/repo", "feat/demo", "", True)[0]
        'feat/demo'
    """
    candidates = workspace_candidate_branches(name, branch_prefix, raw)
    for branch in candidates:
        found = find_workspace_for_branch(project_dir, project_enlistment, branch)
        if found:
            workspace_dir, _ = found
            return branch, workspace_dir, True

    branch = candidates[0]
    workspace_id = workspace_identifier(project_enlistment, branch)
    workspace_dir = workspace_dir_for_branch(project_dir, branch, workspace_id)
    if workspace_dir.exists():
        config_path = workspace_config_path(workspace_dir)
        if not config_path.exists():
            die("workspace config missing for existing workspace directory")
        payload = config.load_workspace_config(config_path)
        if not payload:
            die("failed to load workspace config")
        stored_branch = payload.workspace.branch
        if stored_branch != branch:
            die("workspace branch does not match workspace directory")
    return branch, workspace_dir, False


def normalize_workspace_name(value: str) -> str:
    """Normalize and validate workspace branch input.

    Args:
        value: Raw workspace name input.

    Returns:
        Normalized branch name string.

    Example:
        >>> normalize_workspace_name("feat/demo")
        'feat/demo'
    """
    raw = value.strip()
    if not raw:
        return ""
    normalized = raw.replace("\\", "/")
    if normalized.startswith("/"):
        die("workspace branch must not be an absolute path")
    if ".." in Path(normalized).parts:
        die("workspace branch cannot contain '..'")
    return normalized


def finalization_tag_name(workspace_branch: str) -> str:
    """Return the local finalization tag name for a workspace branch.

    Args:
        workspace_branch: Workspace branch name.

    Returns:
        Finalization tag string (``atelier/<branch>/finalized``).

    Example:
        >>> finalization_tag_name("feat/demo")
        'atelier/feat/demo/finalized'
    """
    branch = workspace_branch.lstrip("/")
    return f"atelier/{branch}/finalized"


def workspace_branch_for_dir(workspace_dir: Path) -> str:
    """Read the workspace branch name from its config file.

    Args:
        workspace_dir: Workspace directory path.

    Returns:
        Branch name string.

    Example:
        >>> workspace_branch_for_dir(Path("/tmp/workspace"))  # doctest: +SKIP
        'feat/demo'
    """
    config_path = workspace_config_path(workspace_dir)
    workspace_config = config.load_workspace_config(config_path)
    if not workspace_config:
        die("failed to load workspace config")
    return workspace_config.workspace.branch


def ensure_workspace_metadata(
    workspace_dir: Path,
    agents_path: Path,
    persist_path: Path,
    workspace_config_file: Path,
    project_root: Path,
    project_enlistment: str,
    workspace_branch: str,
    branch_pr: bool,
    branch_history: str,
    upgrade_policy: str | None,
) -> None:
    """Ensure workspace config and managed workspace files exist.

    Args:
        workspace_dir: Workspace directory path.
        agents_path: Path to ``AGENTS.md`` in the workspace.
        persist_path: Path to ``PERSIST.md`` in the workspace.
        workspace_config_file: Path to workspace ``config.sys.json``.
        project_root: Project directory path.
        project_enlistment: Absolute path to the local enlistment.
        workspace_branch: Workspace branch name.
        branch_pr: Whether pull requests are expected.
        branch_history: History policy (manual|squash|merge|rebase).
        upgrade_policy: Template upgrade policy (always|ask|manual).

    Returns:
        None.

    Example:
        >>> ensure_workspace_metadata(Path("/tmp/workspace"), Path("/tmp/workspace/AGENTS.md"), Path("/tmp/workspace/PERSIST.md"), Path("/tmp/workspace/config.sys.json"), Path("/tmp/project"), "/repo", "feat/demo", True, "manual", "ask")
    """
    workspace_config_exists = workspace_config_file.exists()
    if not workspace_config_exists:
        workspace_id = workspace_identifier(project_enlistment, workspace_branch)
        workspace_config = config.WorkspaceConfig(
            workspace={
                "branch": workspace_branch,
                "branch_pr": branch_pr,
                "branch_history": branch_history,
                "id": workspace_id,
            },
            atelier={
                "version": __version__,
                "created_at": config.utc_now(),
                "upgrade": upgrade_policy,
            },
        )
        config.write_workspace_config(workspace_config_file, workspace_config)

    if workspace_config_exists:
        stored_pr, stored_history = config.read_workspace_branch_settings(workspace_dir)
        if stored_pr is None or stored_history is None:
            die("workspace missing branch settings")
        integration_pr = stored_pr
        integration_history = stored_history
    else:
        integration_pr = branch_pr
        integration_history = branch_history

    if not agents_path.exists():
        template_override = project_root / TEMPLATES_DIRNAME / "AGENTS.md"
        if template_override.exists():
            link_or_copy(template_override, agents_path)
        else:
            agents_path.write_text(
                templates.render_workspace_agents(), encoding="utf-8"
            )

    project_md_path = project_root / "PROJECT.md"
    workspace_project_path = workspace_dir / "PROJECT.md"
    if project_md_path.exists() and not workspace_project_path.exists():
        link_or_copy(project_md_path, workspace_project_path)

    if not persist_path.exists():
        persist_path.write_text(
            templates.render_persist(integration_pr, integration_history),
            encoding="utf-8",
        )


def workspace_up_to_date(
    checked_out: bool | None, clean: bool | None, remote_equal: bool | None
) -> str:
    """Convert workspace status flags into a summary string.

    Args:
        checked_out: Whether the workspace branch is checked out.
        clean: Whether the working tree is clean.
        remote_equal: Whether local ``HEAD`` matches the remote branch.

    Returns:
        ``yes``, ``no``, or ``unknown``.

    Example:
        >>> workspace_up_to_date(True, True, True)
        'yes'
    """
    if checked_out is False or clean is False or remote_equal is False:
        return "no"
    if checked_out is None or clean is None or remote_equal is None:
        return "unknown"
    return "yes"


def format_status(value: bool | None) -> str:
    """Format a tri-state status into ``yes``/``no``/``unknown``.

    Args:
        value: Boolean status or ``None``.

    Returns:
        String representation.

    Example:
        >>> format_status(None)
        'unknown'
    """
    if value is None:
        return "unknown"
    return "yes" if value else "no"


def append_workspace_branch_summary(
    agents_path: Path,
    repo_dir: Path,
    mainline_branch: str,
    workspace_branch: str,
) -> None:
    """Append branch sync status details to ``AGENTS.md``.

    Args:
        agents_path: Path to workspace ``AGENTS.md``.
        repo_dir: Path to workspace ``repo/`` directory.
        mainline_branch: Default branch name.
        workspace_branch: Workspace branch name.

    Returns:
        None.

    Example:
        >>> append_workspace_branch_summary(Path("/tmp/AGENTS.md"), Path("/tmp/repo"), "main", "feat/demo")
    """
    if not agents_path.exists():
        return
    if not repo_dir.exists() or not git.git_is_repo(repo_dir):
        warn("could not append branch summary to AGENTS.md (repo unavailable)")
        return

    pr_message = git.gh_pr_message(repo_dir)
    commit_messages = []
    if not pr_message:
        commit_messages = git.git_commit_messages(
            repo_dir, mainline_branch, workspace_branch
        )

    commits_ahead = git.git_commits_ahead(repo_dir, mainline_branch, workspace_branch)
    diff_names = git.git_diff_name_status(repo_dir, mainline_branch, workspace_branch)
    diff_stat = git.git_diff_stat(repo_dir, mainline_branch, workspace_branch)

    checked_out = None
    current_branch = git.git_current_branch(repo_dir)
    if current_branch:
        checked_out = current_branch == workspace_branch
    clean = git.git_is_clean(repo_dir)
    remote_equal = git.git_head_matches_remote(repo_dir, workspace_branch)
    up_to_date = workspace_up_to_date(checked_out, clean, remote_equal)

    today = dt.datetime.now(tz=dt.timezone.utc).strftime("%Y-%m-%d")
    content = agents_path.read_text(encoding="utf-8")
    if content and not content.endswith("\n"):
        content += "\n"

    lines = [
        "---",
        "",
        "## Branch Sync Status (Latest)",
        "",
        f"- Date checked: {today}",
        f"- Branch: `{workspace_branch}`",
        f"- Mainline: `{mainline_branch}`",
        f"- Workspace up to date with branch: {up_to_date}",
    ]
    if checked_out is not None:
        lines.append(f"- Branch checked out: {format_status(checked_out)}")
    if clean is not None:
        lines.append(f"- Working tree clean: {format_status(clean)}")
    if remote_equal is not None:
        lines.append(f"- Matches remote: {format_status(remote_equal)}")

    if pr_message:
        lines.extend(
            [
                "",
                f"## Latest PR Message (generated {today})",
                "",
                f"- PR: #{pr_message.get('number')} {pr_message.get('title')}",
            ]
        )
        body = pr_message.get("body")
        if body:
            lines.extend(["- Body:", "", "```text", body.rstrip(), "```"])
        else:
            lines.append("- Body: (empty)")
    else:
        lines.extend(["", f"## Latest Commit Message(s) (generated {today})", ""])
        if commit_messages:
            for index, message in enumerate(commit_messages, start=1):
                lines.append(f"- Commit {index}:")
                lines.extend(["", "```text", message.rstrip(), "```"])
        else:
            lines.append("- None (no commits ahead of mainline).")

    lines.extend(["", f"## Review vs Mainline (`{mainline_branch}`)", ""])
    if commits_ahead is not None:
        lines.append(f"- Commits ahead: {commits_ahead}")
    if diff_names:
        lines.append("- Files changed:")
        lines.extend([f"  - `{line}`" for line in diff_names])
    else:
        lines.append("- Files changed: none")
    if diff_stat:
        lines.extend(["", "```text", *diff_stat, "```"])

    content = content + "\n".join(lines).rstrip() + "\n"
    agents_path.write_text(content, encoding="utf-8")


def write_background_snapshot(
    background_path: Path,
    repo_dir: Path,
    mainline_branch: str,
    workspace_branch: str,
) -> None:
    """Write ``BACKGROUND.md`` for a workspace created from an existing branch.

    Args:
        background_path: Path to ``BACKGROUND.md``.
        repo_dir: Path to workspace ``repo/`` directory.
        mainline_branch: Default branch name.
        workspace_branch: Workspace branch name.

    Returns:
        None.
    """
    if background_path.exists():
        return
    if not repo_dir.exists() or not git.git_is_repo(repo_dir):
        warn("could not write BACKGROUND.md (repo unavailable)")
        return

    today = dt.datetime.now(tz=dt.timezone.utc).strftime("%Y-%m-%d")
    lines = [
        "# Background Snapshot",
        "",
        "Captured at workspace creation time; not updated automatically.",
        "",
        f"- Date captured: {today}",
        f"- Branch: `{workspace_branch}`",
        f"- Mainline: `{mainline_branch}`",
    ]

    pr_message = git.gh_pr_message(repo_dir)
    if pr_message:
        title = pr_message.get("title")
        number = pr_message.get("number")
        pr_label = f"#{number} {title}" if number else f"{title}"
        lines.extend(
            [
                "",
                f"## PR Snapshot (generated {today})",
                "",
                f"- PR: {pr_label}",
            ]
        )
        body = pr_message.get("body")
        if body:
            lines.extend(["- Body:", "", "```text", body.rstrip(), "```"])
        else:
            lines.append("- Body: (empty)")
    else:
        subjects = git.git_commit_subjects_since_merge_base(
            repo_dir, mainline_branch, workspace_branch, limit=BACKGROUND_COMMIT_LIMIT
        )
        lines.extend(
            ["", f"## Commit Subjects since merge-base (generated {today})", ""]
        )
        if subjects:
            lines.extend([f"- {subject}" for subject in subjects])
        else:
            lines.append("- None (no commits ahead of mainline).")

    background_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def collect_workspaces(
    project_root: Path, config_payload: config.ProjectConfig, with_status: bool = True
) -> list[dict]:
    """Collect workspace metadata for a project.

    Args:
        project_root: Project directory path.
        config_payload: Project config payload.
        with_status: When true, compute status info from each workspace repo.

    Returns:
        List of workspace dicts with name, path, branch, and status fields.

    Example:
        >>> isinstance(collect_workspaces(Path("/tmp/project"), config.ProjectConfig(), False), list)
        True
    """
    workspaces_root = project_root / WORKSPACES_DIRNAME
    if not workspaces_root.exists():
        return []
    workspace_configs: list[Path] = []
    for workspace_dir in sorted(workspaces_root.iterdir()):
        if not workspace_dir.is_dir():
            continue
        config_path = workspace_config_path(workspace_dir)
        if not config_path.exists():
            warn(f"workspace config missing at {config_path}")
            continue
        workspace_configs.append(config_path)
    if not workspace_configs:
        return []

    def build_workspace(config_path: Path) -> dict | None:
        workspace_dir = config_path.parent
        payload = config.load_workspace_config(config_path)
        if not payload:
            warn(f"failed to load workspace config at {config_path}")
            return None
        branch = payload.workspace.branch
        workspace_name = branch
        repo_dir = workspace_dir / "repo"
        checked_out: bool | None = None
        clean: bool | None = None
        pushed: bool | None = None
        finalized: bool | None = None
        if with_status and repo_dir.exists():
            current_branch = git.git_current_branch(repo_dir)
            checked_out = current_branch == branch if current_branch else None
            if current_branch and current_branch == branch:
                clean = git.git_is_clean(repo_dir)
            else:
                clean = None
            pushed = git.git_has_remote_branch(repo_dir, branch)
            finalized = git.git_tag_exists(repo_dir, finalization_tag_name(branch))
        return {
            "name": workspace_name,
            "path": workspace_dir,
            "repo_dir": repo_dir,
            "branch": branch,
            "checked_out": checked_out,
            "clean": clean,
            "pushed": pushed,
            "finalized": finalized,
        }

    max_workers = min(8, len(workspace_configs))
    if max_workers <= 1:
        workspaces = [
            workspace
            for workspace in (
                build_workspace(config_path) for config_path in workspace_configs
            )
            if workspace is not None
        ]
        return sorted(workspaces, key=lambda item: item["name"])

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        workspaces = [
            workspace
            for workspace in executor.map(build_workspace, workspace_configs)
            if workspace is not None
        ]
    return sorted(workspaces, key=lambda item: item["name"])

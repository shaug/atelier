import concurrent.futures
import datetime as dt
from pathlib import Path

from . import __version__, config, git, templates
from .io import die, warn
from .paths import (
    TEMPLATES_DIRNAME,
    WORKSPACES_DIRNAME,
    workspace_config_path,
    workspace_dir_for_branch,
)


def workspace_identifier(project_origin: str, workspace_branch: str) -> str:
    origin = project_origin.rstrip("/")
    branch = workspace_branch.lstrip("/")
    return f"atelier:{origin}/{branch}"


def require_workspace_branch(config_path: Path, workspace_config: dict) -> str:
    workspace_section = workspace_config.get("workspace", {})
    branch = workspace_section.get("branch")
    if not branch:
        die(f"workspace config missing branch at {config_path}")
    return str(branch)


def workspace_candidate_branches(name: str, branch_prefix: str, raw: bool) -> list[str]:
    if raw:
        return [name]
    candidates = []
    prefixed = f"{branch_prefix}{name}"
    if prefixed:
        candidates.append(prefixed)
    if name and name not in candidates:
        candidates.append(name)
    return candidates


def find_workspace_for_branch(
    project_dir: Path, branch: str
) -> tuple[Path, dict] | None:
    workspace_dir = workspace_dir_for_branch(project_dir, branch)
    config_path = workspace_config_path(workspace_dir)
    if not config_path.exists():
        if workspace_dir.exists():
            die("workspace config missing for existing workspace directory")
        return None
    payload = config.load_json(config_path)
    if not payload:
        die("failed to load workspace config")
    stored_branch = require_workspace_branch(config_path, payload)
    if stored_branch != branch:
        die("workspace branch does not match hashed directory")
    return workspace_dir, payload


def resolve_workspace_target(
    project_dir: Path, name: str, branch_prefix: str, raw: bool
) -> tuple[str, Path, bool]:
    candidates = workspace_candidate_branches(name, branch_prefix, raw)
    for branch in candidates:
        found = find_workspace_for_branch(project_dir, branch)
        if found:
            workspace_dir, _ = found
            return branch, workspace_dir, True

    branch = candidates[0]
    workspace_dir = workspace_dir_for_branch(project_dir, branch)
    if workspace_dir.exists():
        config_path = workspace_config_path(workspace_dir)
        if not config_path.exists():
            die("workspace config missing for existing workspace directory")
        payload = config.load_json(config_path) or {}
        stored_branch = require_workspace_branch(config_path, payload)
        if stored_branch != branch:
            die("workspace branch does not match hashed directory")
    return branch, workspace_dir, False


def normalize_workspace_name(value: str) -> str:
    raw = value.strip()
    if not raw:
        return ""
    normalized = raw.replace("\\", "/")
    if normalized.startswith("/"):
        die("workspace branch must not be an absolute path")
    if ".." in Path(normalized).parts:
        die("workspace branch cannot contain '..'")
    return normalized


def workspace_branch_for_dir(workspace_dir: Path) -> str:
    config_path = workspace_config_path(workspace_dir)
    workspace_config = config.load_json(config_path) or {}
    branch = require_workspace_branch(config_path, workspace_config)
    return branch


def ensure_workspace_metadata(
    workspace_dir: Path,
    agents_path: Path,
    workspace_config_file: Path,
    project_root: Path,
    project_origin: str,
    workspace_branch: str,
    branch_pr: bool,
    branch_history: str,
) -> None:
    workspace_config_exists = workspace_config_file.exists()
    if not workspace_config_exists:
        workspace_id = workspace_identifier(project_origin, workspace_branch)
        workspace_config = {
            "workspace": {
                "branch": workspace_branch,
                "branch_pr": branch_pr,
                "branch_history": branch_history,
                "id": workspace_id,
            },
            "atelier": {
                "version": __version__,
                "created_at": config.utc_now(),
            },
        }
        config.write_json(workspace_config_file, workspace_config)

    if agents_path.exists():
        return

    if workspace_config_exists:
        stored_pr, stored_history = config.read_workspace_branch_settings(workspace_dir)
        if stored_pr is None or not isinstance(stored_pr, bool):
            die("workspace missing branch.pr setting")
        if stored_history is None or not isinstance(stored_history, str):
            die("workspace missing branch.history setting")
        stored_history = config.normalize_branch_history(
            stored_history, "workspace branch.history"
        )
        integration_pr = stored_pr
        integration_history = stored_history
    else:
        integration_pr = branch_pr
        integration_history = branch_history

    integration_strategy = templates.render_integration_strategy(
        integration_pr, integration_history
    )
    template_override = project_root / TEMPLATES_DIRNAME / "AGENTS.md"
    if template_override.exists():
        content = template_override.read_text(encoding="utf-8")
        if "## Integration Strategy" not in content:
            if content and not content.endswith("\n"):
                content += "\n"
            content = content.rstrip() + "\n\n" + integration_strategy + "\n"
        agents_path.write_text(content, encoding="utf-8")
    else:
        workspace_id = workspace_identifier(project_origin, workspace_branch)
        agents_path.write_text(
            templates.render_workspace_agents(workspace_id, integration_strategy),
            encoding="utf-8",
        )


def workspace_up_to_date(
    checked_out: bool | None, clean: bool | None, remote_equal: bool | None
) -> str:
    if checked_out is False or clean is False or remote_equal is False:
        return "no"
    if checked_out is None or clean is None or remote_equal is None:
        return "unknown"
    return "yes"


def format_status(value: bool | None) -> str:
    if value is None:
        return "unknown"
    return "yes" if value else "no"


def append_workspace_branch_summary(
    agents_path: Path,
    repo_dir: Path,
    mainline_branch: str,
    workspace_branch: str,
) -> None:
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


def collect_workspaces(
    project_root: Path, config_payload: dict, with_status: bool = True
) -> list[dict]:
    branch_config = config.resolve_branch_config(config_payload)
    config.resolve_branch_pr(branch_config)
    config.resolve_branch_history(branch_config)
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
        payload = config.load_json(config_path)
        if not payload:
            warn(f"failed to load workspace config at {config_path}")
            return None
        branch = require_workspace_branch(config_path, payload)
        workspace_name = branch
        repo_dir = workspace_dir / "repo"
        checked_out: bool | None = None
        clean: bool | None = None
        pushed: bool | None = None
        if with_status and repo_dir.exists():
            current_branch = git.git_current_branch(repo_dir)
            checked_out = current_branch == branch if current_branch else None
            if current_branch and current_branch == branch:
                clean = git.git_is_clean(repo_dir)
            else:
                clean = None
            pushed = git.git_has_remote_branch(repo_dir, branch)
        return {
            "name": workspace_name,
            "path": workspace_dir,
            "repo_dir": repo_dir,
            "branch": branch,
            "checked_out": checked_out,
            "clean": clean,
            "pushed": pushed,
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

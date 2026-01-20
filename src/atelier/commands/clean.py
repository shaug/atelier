"""Implementation for the ``atelier clean`` command."""

import shutil
from pathlib import Path

from .. import config, exec, git, paths, workspace
from ..io import die, say, warn


def confirm_delete(workspace_name: str) -> bool:
    """Prompt to confirm workspace deletion.

    Args:
        workspace_name: Workspace branch name to confirm.

    Returns:
        ``True`` when the user confirms deletion.

    Example:
        Delete workspace feat/demo? [y/N]:
    """
    response = input(f"Delete workspace {workspace_name}? [y/N]: ").strip().lower()
    return response in {"y", "yes"}


def delete_workspace_branch(
    repo_dir: Path, workspace_branch: str, default_branch: str
) -> None:
    """Delete local and remote workspace branches when possible.

    Args:
        repo_dir: Path to the workspace ``repo/`` directory.
        workspace_branch: Branch name to delete.
        default_branch: Default branch to switch to before deletion.

    Returns:
        None.

    Example:
        >>> from pathlib import Path
        >>> isinstance(repo_dir := Path("."), Path)
        True
    """
    if not repo_dir.exists():
        return
    if not git.git_is_repo(repo_dir):
        return

    current_branch = git.git_current_branch(repo_dir)
    if current_branch == workspace_branch:
        result = exec.try_run_command(
            ["git", "-C", str(repo_dir), "checkout", default_branch]
        )
        if result is None or result.returncode != 0:
            warn(
                f"failed to checkout {default_branch} before deleting {workspace_branch}"
            )
            return

    if git.git_ref_exists(repo_dir, f"refs/heads/{workspace_branch}"):
        result = exec.try_run_command(
            ["git", "-C", str(repo_dir), "branch", "-D", workspace_branch]
        )
        if result is None or result.returncode != 0:
            warn(f"failed to delete local branch {workspace_branch}")

    remote_exists = git.git_has_remote_branch(repo_dir, workspace_branch)
    if remote_exists is False:
        return
    result = exec.try_run_command(
        ["git", "-C", str(repo_dir), "push", "origin", "--delete", workspace_branch]
    )
    if result is None or result.returncode != 0:
        warn(f"failed to delete remote branch {workspace_branch}")


def clean_workspaces(args: object) -> None:
    """Clean workspaces based on status or explicit targets.

    Args:
        args: CLI argument object with ``all``, ``force``, ``no_branch``, and
            ``workspace_names`` fields.

    Returns:
        None.

    Example:
        $ atelier clean --all --force
    """
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

    branch_prefix = config_payload.branch.prefix

    requested = []
    for name in getattr(args, "workspace_names", []) or []:
        if not name.strip():
            continue
        normalized = workspace.normalize_workspace_name(name)
        if not normalized:
            continue
        branch, _, exists = workspace.resolve_workspace_target(
            project_root,
            project_enlistment or enlistment_path,
            normalized,
            branch_prefix,
            False,
        )
        if not exists:
            warn(f"workspace not found: {normalized}")
            continue
        requested.append(branch)

    workspaces = workspace.collect_workspaces(
        project_root, config_payload, with_status=not (args.all or requested)
    )
    if not workspaces:
        say("No workspaces found.")
        return

    workspaces_by_name = {item["name"]: item for item in workspaces}
    if args.all and requested:
        die("cannot combine --all with workspace branches")

    if args.all:
        targets = list(workspaces)
    elif requested:
        targets = []
        for name in requested:
            item = workspaces_by_name.get(name)
            if not item:
                warn(f"workspace not found: {name}")
                continue
            targets.append(item)
    else:
        targets = [item for item in workspaces if item["finalized"] is True]

    if not targets:
        say("No workspaces to clean.")
        return

    for item in targets:
        name = item["name"]
        if not args.force and not confirm_delete(name):
            say(f"Skipped workspace {name}")
            continue
        if not getattr(args, "no_branch", False):
            default_branch = git.git_default_branch(item["repo_dir"])
            if not default_branch:
                warn(
                    "failed to determine default branch for "
                    f"{item['branch']}; skipping branch deletion"
                )
            else:
                delete_workspace_branch(
                    item["repo_dir"], item["branch"], default_branch
                )
        try:
            shutil.rmtree(item["path"])
        except OSError as exc:
            warn(f"failed to delete workspace {name}: {exc}")
            continue
        say(f"Deleted workspace {name}")

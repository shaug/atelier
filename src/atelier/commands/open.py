import shutil
import subprocess
from pathlib import Path

from .. import config, editor, exec, git, paths, project, sessions, workspace
from ..io import die, say, warn


def open_workspace(args: object) -> None:
    cwd = Path.cwd()
    repo_root = git.git_repo_root(cwd)
    if not repo_root:
        die("atelier open must be run inside a git repository")

    origin_raw = git.git_origin_url(repo_root)
    if not origin_raw:
        die("repo missing origin remote")
    origin = git.normalize_origin_url(origin_raw)
    if not origin:
        die("failed to normalize origin URL")

    project_dir = paths.project_dir_for_origin(origin)
    config_path = paths.project_config_path(project_dir)
    config_payload = config.load_json(config_path) or {}
    if not config_payload:
        config_payload = config.build_project_config({}, origin, origin_raw, None)
        project.ensure_project_dirs(project_dir)
        config.write_json(config_path, config_payload)
        project.ensure_project_scaffold(project_dir, False)
    else:
        project.ensure_project_dirs(project_dir)

    project_section = (
        config_payload.get("project")
        if isinstance(config_payload.get("project"), dict)
        else {}
    )
    project_origin = project_section.get("origin")
    if not project_origin:
        project_section["origin"] = origin
        project_section.setdefault("repo_url", origin_raw)
        config_payload["project"] = project_section
        config.write_json(config_path, config_payload)
        project_origin = origin
    if project_origin != origin:
        die("project origin does not match current repo origin")

    branch_config = config.resolve_branch_config(config_payload)
    branch_pr = config.resolve_branch_pr(branch_config)
    branch_history = config.resolve_branch_history(branch_config)
    branch_pr_override, branch_history_override = config.resolve_branch_overrides(args)
    effective_branch_pr = (
        branch_pr_override if branch_pr_override is not None else branch_pr
    )
    effective_branch_history = (
        branch_history_override
        if branch_history_override is not None
        else branch_history
    )

    workspace_name_input = getattr(args, "workspace_name", None)
    raw_branch = bool(getattr(args, "raw", False))

    if not workspace_name_input:
        if raw_branch:
            die("workspace branch is required when using --raw")
        workspace_name_input = resolve_implicit_workspace_name(
            repo_root, config_payload
        )
        raw_branch = True

    workspace_name_input = workspace.normalize_workspace_name(str(workspace_name_input))
    if not workspace_name_input:
        die("workspace branch is required")

    branch_prefix = branch_config.get("prefix", "")
    workspace_branch, workspace_dir, workspace_config_exists = (
        workspace.resolve_workspace_target(
            project_dir,
            workspace_name_input,
            branch_prefix,
            raw_branch,
        )
    )
    if not workspace_branch:
        die("workspace branch is required")

    agents_path = workspace_dir / "AGENTS.md"
    workspace_config_file = paths.workspace_config_path(workspace_dir)
    is_new_workspace = not workspace_config_exists
    if workspace_config_exists:
        if branch_pr_override is not None or branch_history_override is not None:
            stored_pr, stored_history = config.read_workspace_branch_settings(
                workspace_dir
            )
            if branch_pr_override is not None:
                if stored_pr is None or not isinstance(stored_pr, bool):
                    die("workspace missing branch.pr setting")
                if stored_pr != branch_pr_override:
                    die(
                        "specified branch.pr does not match workspace config "
                        f"({branch_pr_override} != {stored_pr})"
                    )
            if branch_history_override is not None:
                if stored_history is None or not isinstance(stored_history, str):
                    die("workspace missing branch.history setting")
                stored_history = config.normalize_branch_history(
                    stored_history, "workspace branch.history"
                )
                if stored_history != branch_history_override:
                    die(
                        "specified branch.history does not match workspace config "
                        f"({branch_history_override} != {stored_history})"
                    )
        stored_branch = workspace.workspace_branch_for_dir(workspace_dir)
        if stored_branch != workspace_branch:
            die("workspace branch does not match configured workspace branch")
    paths.ensure_dir(workspace_dir)
    workspace.ensure_workspace_metadata(
        workspace_dir=workspace_dir,
        agents_path=agents_path,
        workspace_config_file=workspace_config_file,
        project_root=project_dir,
        project_origin=project_origin,
        workspace_branch=workspace_branch,
        branch_pr=effective_branch_pr,
        branch_history=effective_branch_history,
    )
    workspace_policy_template = project_dir / paths.TEMPLATES_DIRNAME / "WORKSPACE.md"
    workspace_policy_path = workspace_dir / "WORKSPACE.md"
    if workspace_policy_template.exists() and not workspace_policy_path.exists():
        shutil.copyfile(workspace_policy_template, workspace_policy_path)

    repo_dir = workspace_dir / "repo"
    project_repo_url = origin_raw

    should_open_editor = False
    editor_cmd: list[str] | None = None
    if not repo_dir.exists():
        should_open_editor = True
        exec.run_command(["git", "clone", project_repo_url, str(repo_dir)])
    else:
        if not git.git_is_repo(repo_dir):
            die("repo exists but is not a git repository")
        remote_check = subprocess.run(
            ["git", "-C", str(repo_dir), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            check=False,
        )
        if remote_check.returncode != 0:
            die("repo missing origin remote")
        current_remote = remote_check.stdout.strip()
        if not current_remote:
            die("repo missing origin remote")
        if current_remote != project_repo_url:
            warn("repo remote differs from current origin; using existing repo")

    current_branch = git.git_current_branch(repo_dir)
    if current_branch is None:
        die("failed to determine repo branch")
    repo_clean = git.git_is_clean(repo_dir)
    if repo_clean is None:
        die("failed to determine repo status")

    default_branch = git.git_default_branch(repo_dir)
    if not default_branch:
        die("failed to determine default branch from repo")

    skip_default_checkout = False
    skip_workspace_checkout = False
    if not repo_clean:
        if current_branch not in {default_branch, workspace_branch}:
            die(
                "repo has uncommitted changes on "
                f"{current_branch!r}; checkout {workspace_branch!r} or "
                f"{default_branch!r} and try again, or commit/stash your changes"
            )
        if current_branch != default_branch:
            skip_default_checkout = True
        if current_branch == workspace_branch:
            skip_workspace_checkout = True

    if not skip_default_checkout:
        exec.run_command(["git", "-C", str(repo_dir), "checkout", default_branch])

    local_branch = git.git_ref_exists(repo_dir, f"refs/heads/{workspace_branch}")
    remote_branch = git.git_ref_exists(
        repo_dir, f"refs/remotes/origin/{workspace_branch}"
    )
    if not remote_branch:
        remote_branch = git.git_has_remote_branch(repo_dir, workspace_branch) is True
        if remote_branch:
            exec.run_command(
                ["git", "-C", str(repo_dir), "fetch", "origin", workspace_branch]
            )
    existing_branch = local_branch or remote_branch

    if skip_workspace_checkout:
        pass
    elif local_branch:
        exec.run_command(["git", "-C", str(repo_dir), "checkout", workspace_branch])
    elif remote_branch:
        exec.run_command(
            [
                "git",
                "-C",
                str(repo_dir),
                "checkout",
                "-b",
                workspace_branch,
                "--track",
                f"origin/{workspace_branch}",
            ]
        )
    else:
        exec.run_command(
            ["git", "-C", str(repo_dir), "checkout", "-b", workspace_branch]
        )

    agent_default = config_payload.get("agent", {}).get("default", "codex")
    if agent_default != "codex":
        die("only 'codex' is supported as the agent in v2")

    agent_options = config_payload.get("agent", {}).get("options", {}).get("codex", [])
    if not isinstance(agent_options, list):
        agent_options = []
    agent_options = [str(opt) for opt in agent_options]

    if is_new_workspace and existing_branch:
        workspace.append_workspace_branch_summary(
            agents_path, repo_dir, default_branch, workspace_branch
        )

    if should_open_editor:
        if editor_cmd is None:
            editor_cmd = editor.resolve_editor_command(config_payload)
        try:
            agents_target = agents_path.relative_to(workspace_dir)
        except ValueError:
            agents_target = agents_path
        exec.run_command([*editor_cmd, str(agents_target)], cwd=workspace_dir)

    session_id = sessions.find_codex_session(project_origin, workspace_branch)
    if session_id:
        say(f"Resuming Codex session {session_id}")
        exec.run_command(
            ["codex", "--cd", str(workspace_dir), *agent_options, "resume", session_id]
        )
    else:
        opening_prompt = workspace.workspace_identifier(
            project_origin, workspace_branch
        )
        say("Starting new Codex session")
        exec.run_command(
            ["codex", "--cd", str(workspace_dir), *agent_options, opening_prompt]
        )


def resolve_implicit_workspace_name(repo_root: Path, config_payload: dict) -> str:
    default_branch = git.git_default_branch(repo_root)
    if not default_branch:
        die("failed to determine default branch from repo")

    current_branch = git.git_current_branch(repo_root)
    if not current_branch:
        die("failed to determine current branch")
    if current_branch == default_branch:
        die(
            "implicit open requires a non-default branch; "
            f"current branch is {default_branch!r}"
        )

    clean = git.git_is_clean(repo_root)
    if clean is not True:
        die("implicit open requires a clean working tree")

    fully_pushed = git.git_branch_fully_pushed(repo_root)
    if fully_pushed is None:
        die("implicit open requires the branch to be pushed to its upstream")
    if fully_pushed is False:
        die("implicit open requires the branch to be fully pushed to its upstream")

    return current_branch

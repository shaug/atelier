"""Implementation for the ``atelier open`` command."""

import difflib
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .. import (
    __version__,
    agents,
    config,
    editor,
    exec,
    git,
    paths,
    project,
    templates,
    workspace,
)
from ..io import confirm, die, link_or_copy, say, warn


def confirm_remove_finalization_tag(workspace_branch: str, tag: str) -> bool:
    """Prompt to remove an existing finalization tag before reopening.

    Args:
        workspace_branch: Workspace branch name.
        tag: Finalization tag name.

    Returns:
        ``True`` when the user confirms tag removal.
    """
    return confirm(
        "Workspace "
        f"{workspace_branch} has finalization tag {tag}. "
        "Remove it before continuing?",
        default=False,
    )


@dataclass
class ManagedTemplateUpdate:
    description: str
    path: Path
    new_text: str
    current_text: str | None
    current_hash: str | None
    stored_hash: str | None
    update_hash: Callable[[str], None] | None
    create: Callable[[], None] | None
    write_text: Callable[[str], None] | None
    unmodified: bool
    needs_update: bool


def build_managed_template_update(
    *,
    description: str,
    path: Path,
    new_text: str,
    stored_hash: str | None,
    update_hash: Callable[[str], None] | None,
    create: Callable[[], None] | None = None,
    write_text: Callable[[str], None] | None = None,
) -> ManagedTemplateUpdate:
    if path.exists():
        current_text = path.read_text(encoding="utf-8")
        current_hash = config.hash_text(current_text)
    else:
        current_text = None
        current_hash = None
    if current_text is None:
        unmodified = True
        needs_update = True
    else:
        if stored_hash is not None:
            unmodified = current_hash == stored_hash
        else:
            unmodified = current_text == new_text
        needs_update = current_text != new_text
    return ManagedTemplateUpdate(
        description=description,
        path=path,
        new_text=new_text,
        current_text=current_text,
        current_hash=current_hash,
        stored_hash=stored_hash,
        update_hash=update_hash,
        create=create,
        write_text=write_text,
        unmodified=unmodified,
        needs_update=needs_update,
    )


def apply_managed_template_update(item: ManagedTemplateUpdate) -> None:
    if item.current_text is None:
        if item.create is not None:
            item.create()
        elif item.write_text is not None:
            item.write_text(item.new_text)
        else:
            item.path.write_text(item.new_text, encoding="utf-8")
    else:
        if item.write_text is not None:
            item.write_text(item.new_text)
        else:
            item.path.write_text(item.new_text, encoding="utf-8")
    if item.update_hash is not None:
        item.update_hash(config.hash_text(item.new_text))


def maybe_record_managed_hash(item: ManagedTemplateUpdate) -> bool:
    if (
        item.update_hash is None
        or item.current_hash is None
        or item.stored_hash == item.current_hash
        or item.needs_update
    ):
        return False
    item.update_hash(item.current_hash)
    return True


def show_template_diff(item: ManagedTemplateUpdate) -> None:
    before = item.current_text or ""
    diff_lines = difflib.unified_diff(
        before.splitlines(),
        item.new_text.splitlines(),
        fromfile=str(item.path),
        tofile=str(item.path),
        lineterm="",
    )
    say(f"Diff for {item.description}:")
    for line in diff_lines:
        say(line)


def confirm_template_update(description: str) -> bool:
    return confirm(f"Apply update for {description}?", default=False)


def apply_upgrade_policy(
    *,
    policy: str,
    items: list[ManagedTemplateUpdate],
    skip_command: str,
) -> bool:
    changed = False
    for item in items:
        if not item.needs_update:
            if maybe_record_managed_hash(item):
                changed = True
            continue
        if policy == "always":
            if item.unmodified:
                apply_managed_template_update(item)
                changed = True
            else:
                warn(
                    "skipping "
                    f"{item.description} because it appears modified; "
                    f"run `{skip_command}` to upgrade it manually"
                )
            continue
        if policy == "ask":
            show_template_diff(item)
            if confirm_template_update(item.description):
                apply_managed_template_update(item)
                changed = True
            continue
    return changed


def update_project_atelier(
    project_dir: Path, *, version: str | None = None, upgrade: str | None = None
) -> None:
    system_path = paths.project_config_sys_path(project_dir)
    user_path = paths.project_config_user_path(project_dir)
    system_config = config.load_project_system_config(system_path)
    if not system_config:
        return
    user_config = (
        config.load_project_user_config(user_path) or config.default_user_config()
    )
    system_updates: dict[str, object] = {}
    if version is not None:
        system_updates["version"] = version
    if system_updates:
        atelier_section = system_config.atelier.model_copy(update=system_updates)
        system_config = system_config.model_copy(update={"atelier": atelier_section})
        config.write_project_system_config(system_path, system_config)
    if upgrade is not None:
        atelier_section = user_config.atelier.model_copy(update={"upgrade": upgrade})
        user_config = user_config.model_copy(update={"atelier": atelier_section})
        config.write_project_user_config(user_path, user_config)


def update_workspace_atelier(
    workspace_dir: Path, *, version: str | None = None, upgrade: str | None = None
) -> None:
    system_path = paths.workspace_config_sys_path(workspace_dir)
    user_path = paths.workspace_config_user_path(workspace_dir)
    system_config = config.load_workspace_system_config(system_path)
    if not system_config:
        return
    user_config = (
        config.load_workspace_user_config(user_path) or config.WorkspaceUserConfig()
    )
    system_updates: dict[str, object] = {}
    if version is not None:
        system_updates["version"] = version
    if system_updates:
        atelier_section = system_config.atelier.model_copy(update=system_updates)
        system_config = system_config.model_copy(update={"atelier": atelier_section})
        config.write_workspace_system_config(system_path, system_config)
    if upgrade is not None:
        atelier_section = user_config.atelier.model_copy(update={"upgrade": upgrade})
        user_config = user_config.model_copy(update={"atelier": atelier_section})
        config.write_workspace_user_config(user_path, user_config)


def collect_project_template_updates(
    project_dir: Path, project_config: config.ProjectConfig
) -> list[ManagedTemplateUpdate]:
    managed = project_config.atelier.managed_files
    templates_root = project_dir / paths.TEMPLATES_DIRNAME
    project_label_text = project_dir.name

    agents_text = templates.agents_template(prefer_installed=True)
    template_agents_path = templates_root / "AGENTS.md"
    template_agents_key = f"{paths.TEMPLATES_DIRNAME}/AGENTS.md"

    def update_template_agents_hash(value: str) -> None:
        config.update_project_managed_files(project_dir, {template_agents_key: value})

    def create_template_agents() -> None:
        paths.ensure_dir(template_agents_path.parent)
        template_agents_path.write_text(agents_text, encoding="utf-8")

    updates: list[ManagedTemplateUpdate] = [
        build_managed_template_update(
            description=f"Project templates/AGENTS.md ({project_label_text})",
            path=template_agents_path,
            new_text=agents_text,
            stored_hash=managed.get(template_agents_key),
            update_hash=update_template_agents_hash,
            create=create_template_agents,
            write_text=lambda text: template_agents_path.write_text(
                text, encoding="utf-8"
            ),
        )
    ]

    success_text = templates.success_md_template(prefer_installed=True)
    template_success_path = templates_root / "SUCCESS.md"
    template_success_key = f"{paths.TEMPLATES_DIRNAME}/SUCCESS.md"

    def update_success_hash(value: str) -> None:
        config.update_project_managed_files(project_dir, {template_success_key: value})

    def create_success_template() -> None:
        paths.ensure_dir(template_success_path.parent)
        template_success_path.write_text(success_text, encoding="utf-8")

    updates.append(
        build_managed_template_update(
            description=f"Project templates/SUCCESS.md ({project_label_text})",
            path=template_success_path,
            new_text=success_text,
            stored_hash=managed.get(template_success_key),
            update_hash=update_success_hash,
            create=create_success_template,
            write_text=lambda text: template_success_path.write_text(
                text, encoding="utf-8"
            ),
        )
    )
    return updates


def collect_workspace_template_updates(
    workspace_dir: Path,
    workspace_config: config.WorkspaceConfig,
    project_dir: Path,
) -> list[ManagedTemplateUpdate]:
    managed = workspace_config.atelier.managed_files
    workspace_label_text = workspace_config.workspace.branch
    project_template_path = project_dir / paths.TEMPLATES_DIRNAME / "AGENTS.md"
    if project_template_path.exists():
        source_text = project_template_path.read_text(encoding="utf-8")
    else:
        source_text = templates.workspace_agents_template(prefer_installed=True)

    agents_path = workspace_dir / "AGENTS.md"
    agents_key = "AGENTS.md"

    def update_agents_hash(value: str) -> None:
        config.update_workspace_managed_files(workspace_dir, {agents_key: value})

    def create_agents() -> None:
        if project_template_path.exists():
            link_or_copy(project_template_path, agents_path)
        else:
            agents_path.write_text(source_text, encoding="utf-8")

    return [
        build_managed_template_update(
            description=f"Workspace AGENTS.md ({workspace_label_text})",
            path=agents_path,
            new_text=source_text,
            stored_hash=managed.get(agents_key),
            update_hash=update_agents_hash,
            create=create_agents,
            write_text=lambda text: agents_path.write_text(text, encoding="utf-8"),
        )
    ]


def open_workspace(args: object) -> None:
    """Create or open a workspace and launch the agent session.

    Args:
        args: CLI argument object with fields like ``workspace_name``, ``raw``,
            ``branch_pr``, and ``branch_history``.

    Returns:
        None.

    Example:
        $ atelier open feat/new-search
    """
    cwd = Path.cwd()
    repo_root, enlistment_path, origin_raw, origin = git.resolve_repo_enlistment(cwd)

    project_dir = paths.project_dir_for_enlistment(enlistment_path, origin)
    config_path = paths.project_config_path(project_dir)
    config_payload = config.load_project_config(config_path)
    if not config_payload:
        config_payload = config.build_project_config(
            {}, enlistment_path, origin, origin_raw, None
        )
        project.ensure_project_dirs(project_dir)
        config.write_project_config(config_path, config_payload)
    else:
        project.ensure_project_dirs(project_dir)

    project_section = config_payload.project
    project_enlistment = project_section.enlistment
    project_origin = project_section.origin
    project_repo_url = project_section.repo_url
    updates: dict[str, object] = {}

    if not project_enlistment:
        updates["enlistment"] = enlistment_path
        project_enlistment = enlistment_path
    elif project_enlistment != enlistment_path:
        die("project enlistment does not match current repo path")

    if origin is not None and project_origin != origin:
        updates["origin"] = origin
        project_origin = origin
    if origin_raw is not None and project_repo_url != origin_raw:
        updates["repo_url"] = origin_raw
        project_repo_url = origin_raw

    if updates:
        project_section = project_section.model_copy(update=updates)
        config_payload = config_payload.model_copy(update={"project": project_section})
        config.write_project_config(config_path, config_payload)

    project_upgrade_policy = config.resolve_upgrade_policy(
        config_payload.atelier.upgrade
    )
    project_version = config_payload.atelier.version
    project_version_mismatch = (
        project_version is not None and project_version != __version__
    )
    if project_upgrade_policy != "manual" and project_version_mismatch:
        say(
            "Checking project templates for upgrades "
            f"({project_upgrade_policy} policy)."
        )
        project_updates = collect_project_template_updates(project_dir, config_payload)
        apply_upgrade_policy(
            policy=project_upgrade_policy,
            items=project_updates,
            skip_command="atelier upgrade --installed",
        )
        update_project_atelier(
            project_dir, version=__version__, upgrade=project_upgrade_policy
        )

    branch_config = config_payload.branch
    branch_pr = branch_config.pr
    branch_history = branch_config.history
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

    branch_prefix = branch_config.prefix
    workspace_branch, workspace_dir, workspace_config_exists = (
        workspace.resolve_workspace_target(
            project_dir,
            project_enlistment,
            workspace_name_input,
            branch_prefix,
            raw_branch,
        )
    )
    if not workspace_branch:
        die("workspace branch is required")

    agents_path = workspace_dir / "AGENTS.md"
    persist_path = workspace_dir / "PERSIST.md"
    background_path = workspace_dir / "BACKGROUND.md"
    workspace_config_file = paths.workspace_config_path(workspace_dir)
    workspace_config_exists = workspace_config_file.exists()
    is_new_workspace = not workspace_config_exists
    workspace_config: config.WorkspaceConfig | None = None
    if workspace_config_exists:
        workspace_config = config.load_workspace_config(workspace_config_file)
        if not workspace_config:
            die("failed to load workspace config")
        if branch_pr_override is not None or branch_history_override is not None:
            stored_pr = workspace_config.workspace.branch_pr
            stored_history = workspace_config.workspace.branch_history
            if branch_pr_override is not None:
                if stored_pr != branch_pr_override:
                    die(
                        "specified branch.pr does not match workspace config "
                        f"({branch_pr_override} != {stored_pr})"
                    )
            if branch_history_override is not None:
                if stored_history != branch_history_override:
                    die(
                        "specified branch.history does not match workspace config "
                        f"({branch_history_override} != {stored_history})"
                    )
        stored_branch = workspace_config.workspace.branch
        if stored_branch != workspace_branch:
            die("workspace branch does not match configured workspace branch")
    if is_new_workspace:
        project.ensure_project_scaffold(project_dir)
        config.update_project_managed_files(
            project_dir, config.managed_project_agents_updates(project_dir)
        )
        paths.ensure_dir(workspace_dir)
        workspace.ensure_workspace_metadata(
            workspace_dir=workspace_dir,
            agents_path=agents_path,
            persist_path=persist_path,
            workspace_config_file=workspace_config_file,
            project_root=project_dir,
            project_enlistment=project_enlistment,
            workspace_branch=workspace_branch,
            branch_pr=effective_branch_pr,
            branch_history=effective_branch_history,
            upgrade_policy=project_upgrade_policy,
        )
        config.update_workspace_managed_files(
            workspace_dir, config.managed_workspace_agents_updates(workspace_dir)
        )
        success_policy_template = project_dir / paths.TEMPLATES_DIRNAME / "SUCCESS.md"
        legacy_policy_template = project_dir / paths.TEMPLATES_DIRNAME / "WORKSPACE.md"
        if success_policy_template.exists():
            workspace_policy_template = success_policy_template
            workspace_policy_target = workspace_dir / "SUCCESS.md"
        elif legacy_policy_template.exists():
            workspace_policy_template = legacy_policy_template
            workspace_policy_target = workspace_dir / "WORKSPACE.md"
        else:
            workspace_policy_template = None
            workspace_policy_target = None
        if (
            workspace_policy_template is not None
            and workspace_policy_target is not None
            and not workspace_policy_target.exists()
        ):
            shutil.copyfile(workspace_policy_template, workspace_policy_target)

    if workspace_config is not None:
        workspace_upgrade_policy = project_upgrade_policy
        if workspace_config.atelier.upgrade is not None:
            workspace_upgrade_policy = config.resolve_upgrade_policy(
                workspace_config.atelier.upgrade
            )
        workspace_version = workspace_config.atelier.version
        workspace_version_mismatch = (
            workspace_version is not None and workspace_version != __version__
        )
        if workspace_upgrade_policy != "manual" and workspace_version_mismatch:
            say(
                "Checking workspace templates for upgrades "
                f"({workspace_upgrade_policy} policy)."
            )
            workspace_updates = collect_workspace_template_updates(
                workspace_dir, workspace_config, project_dir
            )
            apply_upgrade_policy(
                policy=workspace_upgrade_policy,
                items=workspace_updates,
                skip_command=(
                    f"atelier upgrade {workspace_config.workspace.branch} --installed"
                ),
            )
            update_workspace_atelier(
                workspace_dir, version=__version__, upgrade=workspace_upgrade_policy
            )

    workspace_policy_path: Path | None = None
    success_policy_path = workspace_dir / "SUCCESS.md"
    legacy_policy_path = workspace_dir / "WORKSPACE.md"
    if success_policy_path.exists():
        workspace_policy_path = success_policy_path
    elif legacy_policy_path.exists():
        workspace_policy_path = legacy_policy_path

    repo_dir = workspace_dir / "repo"
    project_repo_url = origin_raw or enlistment_path

    should_open_editor = False
    editor_cmd: list[str] | None = None
    if not repo_dir.exists():
        should_open_editor = True
        exec.run_command(["git", "clone", project_repo_url, str(repo_dir)])
    else:
        if not git.git_is_repo(repo_dir):
            die("repo exists but is not a git repository")
        if origin_raw is not None:
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

    if repo_dir.exists():
        finalization_tag = workspace.finalization_tag_name(workspace_branch)
        if git.git_tag_exists(repo_dir, finalization_tag):
            if confirm_remove_finalization_tag(workspace_branch, finalization_tag):
                result = exec.try_run_command(
                    ["git", "-C", str(repo_dir), "tag", "-d", finalization_tag]
                )
                if result is None or result.returncode != 0:
                    warn("failed to delete finalization tag; continuing with open")

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

    agent_default = config_payload.agent.default
    agent_spec = agents.get_agent(agent_default)
    if agent_spec is None:
        die(f"unsupported agent {agent_default!r}")

    agent_options = config_payload.agent.options.get(agent_spec.name, [])

    if is_new_workspace and existing_branch:
        workspace.write_background_snapshot(
            background_path, repo_dir, default_branch, workspace_branch
        )

    if should_open_editor and workspace_policy_path is not None:
        if editor_cmd is None:
            editor_cmd = editor.resolve_editor_command(config_payload, role="edit")
        try:
            workspace_target = workspace_policy_path.relative_to(workspace_dir)
        except ValueError:
            workspace_target = workspace_policy_path
        exec.run_command([*editor_cmd, str(workspace_target)], cwd=workspace_dir)

    session_id = agents.find_resume_session(
        agent_spec, project_enlistment, workspace_branch
    )
    resume_command = agent_spec.build_resume_command(
        workspace_dir, agent_options, session_id
    )
    resume_reason: str | None = None
    if agent_spec.name == "aider":
        if agents.aider_chat_history_path(workspace_dir) is None:
            resume_command = None
            resume_reason = "Aider chat history not found"
    if resume_command is not None:
        resume_cmd, resume_cwd = resume_command
        if session_id:
            say(f"Resuming {agent_spec.display_name} session {session_id}")
        else:
            say(f"Resuming {agent_spec.display_name} session")
        result = exec.run_command_status(resume_cmd, cwd=resume_cwd)
        if result is not None and result.returncode == 0:
            return
        if result is None:
            warn(
                f"failed to resume {agent_spec.display_name} session; "
                "command not found; starting new session"
            )
        else:
            warn(
                f"failed to resume {agent_spec.display_name} session "
                f"(exit code {result.returncode}); starting new session"
            )
    elif resume_reason is not None:
        warn(f"{resume_reason}; starting new session")

    opening_prompt = workspace.workspace_identifier(
        project_enlistment, workspace_branch
    )
    if agent_spec.name != "codex":
        opening_prompt = ""
    say(f"Starting new {agent_spec.display_name} session")
    start_cmd, start_cwd = agent_spec.build_start_command(
        workspace_dir, agent_options, opening_prompt
    )
    exec.run_command(start_cmd, cwd=start_cwd)


def resolve_implicit_workspace_name(repo_root: Path, _config_payload: object) -> str:
    """Resolve the current branch for implicit ``atelier open`` calls.

    The branch is accepted only when it is non-default, clean, and fully pushed
    to its upstream.

    Args:
        repo_root: Path to the git repository root.
        _config_payload: Reserved for future use; currently ignored.

    Returns:
        The current branch name when it meets the implicit-open criteria.

    Example:
        >>> from pathlib import Path
        >>> isinstance(repo_root := Path("."), Path)
        True
    """
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

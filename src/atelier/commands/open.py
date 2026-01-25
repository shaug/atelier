"""Implementation for the ``atelier open`` command.

``atelier open`` resolves or creates a workspace, ensures the repo checkout,
handles template upgrades, and launches or resumes the agent session.
"""

import difflib
import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .. import (
    __version__,
    agents,
    codex,
    config,
    editor,
    exec,
    git,
    paths,
    project,
    templates,
    term,
    workspace,
)
from ..io import confirm, die, link_or_copy, prompt, say, warn


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


def normalize_ticket_refs(values: list[str] | None) -> list[str]:
    """Normalize ticket references, splitting comma-delimited inputs."""
    if not values:
        return []
    refs: list[str] = []
    seen: set[str] = set()
    for raw in values:
        if raw is None:
            continue
        for part in str(raw).split(","):
            ref = part.strip()
            if not ref:
                continue
            normalized = ref.casefold()
            if normalized in seen:
                continue
            seen.add(normalized)
            refs.append(ref)
    return refs


def merge_ticket_refs(existing: list[str], new: list[str]) -> list[str]:
    """Merge ticket references, preserving order and deduping by case."""
    merged: list[str] = []
    seen: set[str] = set()
    for ref in [*existing, *new]:
        normalized = ref.casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        merged.append(ref)
    return merged


def append_ticket_section(path: Path, refs: list[str]) -> None:
    """Append a Tickets section to the SUCCESS.md file."""
    if not path.exists():
        warn(f"SUCCESS.md not found for tickets at {path}")
        return
    content = path.read_text(encoding="utf-8")
    if content and not content.endswith("\n"):
        content += "\n"
    lines = ["", "## Tickets", "", *[f"- {ref}" for ref in refs]]
    updated = content + "\n".join(lines).rstrip() + "\n"
    path.write_text(updated, encoding="utf-8")


TICKET_TITLE_WORD_LIMIT = 4


def normalize_ticket_slug(value: str) -> str:
    """Normalize a ticket slug component."""
    lowered = value.strip().lower()
    if not lowered:
        return ""
    cleaned = re.sub(r"[^a-z0-9]+", "-", lowered)
    collapsed = re.sub(r"-{2,}", "-", cleaned).strip("-")
    return collapsed


def limit_ticket_title_words(value: str, limit: int = TICKET_TITLE_WORD_LIMIT) -> str:
    """Limit ticket title text to a fixed number of words."""
    words = value.strip().split()
    if not words:
        return ""
    return " ".join(words[:limit])


def ticket_id_likely(value: str) -> bool:
    """Return true when a token resembles a ticket identifier."""
    return any(char.isdigit() for char in value)


def split_ticket_reference(value: str) -> tuple[str, str | None]:
    """Split a ticket reference into id and optional title."""
    raw = value.strip()
    if not raw:
        return "", None
    match = re.match(r"^(?P<id>\S+?)(?:\s*:\s*|\s+-\s+|\s+)(?P<title>.+)$", raw)
    if match and ticket_id_likely(match.group("id")):
        title = match.group("title").strip()
        return match.group("id"), title or None
    return raw, None


def format_ticket_workspace_name(ticket_id: str, title: str | None) -> str:
    """Render a workspace name from a ticket id and optional title."""
    normalized_id = normalize_ticket_slug(ticket_id)
    if not normalized_id:
        return ""
    normalized_title = ""
    if title:
        limited = limit_ticket_title_words(title)
        normalized_title = normalize_ticket_slug(limited)
    if normalized_title:
        return f"{normalized_id}-{normalized_title}"
    return normalized_id


def github_repo_from_origin(origin: str | None) -> str | None:
    """Extract the GitHub owner/repo from a normalized origin string."""
    if not origin:
        return None
    marker = "github.com/"
    if marker not in origin:
        return None
    return origin.split(marker, 1)[1] or None


def parse_github_issue_ref(
    value: str, default_repo: str | None
) -> tuple[str | None, str] | None:
    """Parse GitHub issue reference into repo + issue number."""
    raw = value.strip()
    if not raw:
        return None
    url_match = re.search(
        r"github\.com/(?P<owner>[^/\s]+)/(?P<repo>[^/\s]+)/issues/(?P<number>\d+)",
        raw,
    )
    if url_match:
        repo = f"{url_match.group('owner')}/{url_match.group('repo')}"
        return repo, url_match.group("number")
    repo_match = re.match(r"(?P<repo>[^#\s]+)#(?P<number>\d+)$", raw)
    if repo_match and "/" in repo_match.group("repo"):
        return repo_match.group("repo"), repo_match.group("number")
    number_match = re.match(r"#?(?P<number>\d+)$", raw)
    if number_match:
        return default_repo, number_match.group("number")
    return None


def resolve_ticket_title(
    ticket_ref: str,
    *,
    ticket_provider: str,
    default_project: str | None,
    project_origin: str | None,
    repo_root: Path,
) -> str | None:
    """Best-effort lookup of ticket titles for workspace naming."""
    if ticket_provider != "github" or not git.gh_available():
        return None
    default_repo = default_project or github_repo_from_origin(project_origin)
    parsed = parse_github_issue_ref(ticket_ref, default_repo)
    if not parsed:
        return None
    repo, number = parsed
    cmd = ["gh", "issue", "view", number, "--json", "title"]
    if repo:
        cmd.extend(["--repo", repo])
    result = exec.try_run_command(cmd, cwd=repo_root)
    if result is None or result.returncode != 0:
        return None
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return None
    title = payload.get("title")
    if not title:
        return None
    return str(title)


def render_ticket_success_template(
    text: str,
    *,
    ticket_provider: str,
    ticket_id: str,
    project_name: str,
) -> str:
    return (
        text.replace("${ticket-provider}", ticket_provider)
        .replace("${ticket-id}", ticket_id)
        .replace("${project-name}", project_name)
    )


def project_success_is_custom(project_dir: Path) -> bool:
    """Return true when the project SUCCESS.md template is customized."""
    success_path = project_dir / paths.TEMPLATES_DIRNAME / "SUCCESS.md"
    if not success_path.exists():
        return False
    success_content = success_path.read_text(encoding="utf-8")
    canonical = templates.success_md_template(prefer_installed=True)
    return success_content != canonical


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


def persist_codex_session(
    workspace_dir: Path, result: codex.CodexRunResult | None
) -> None:
    """Persist captured Codex session metadata when available."""
    if result is None:
        return
    if not result.session_id and not result.resume_command:
        return
    config.update_workspace_session(
        workspace_dir,
        agent="codex",
        session_id=result.session_id,
        resume_command=result.resume_command,
    )


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

    updates = [
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

    persist_path = workspace_dir / "PERSIST.md"
    persist_key = "PERSIST.md"
    persist_text = templates.render_persist(
        workspace_config.workspace.branch_pr,
        workspace_config.workspace.branch_history,
    )

    def update_persist_hash(value: str) -> None:
        config.update_workspace_managed_files(workspace_dir, {persist_key: value})

    updates.append(
        build_managed_template_update(
            description=f"Workspace PERSIST.md ({workspace_label_text})",
            path=persist_path,
            new_text=persist_text,
            stored_hash=managed.get(persist_key),
            update_hash=update_persist_hash,
            write_text=lambda text: persist_path.write_text(text, encoding="utf-8"),
        )
    )
    return updates


def backfill_missing_workspace_files(
    *,
    workspace_dir: Path,
    workspace_config: config.WorkspaceConfig,
    project_dir: Path,
) -> None:
    workspace_label_text = workspace_config.workspace.branch
    agents_path = workspace_dir / "AGENTS.md"
    persist_path = workspace_dir / "PERSIST.md"
    project_template_path = project_dir / paths.TEMPLATES_DIRNAME / "AGENTS.md"
    canonical_agents = templates.workspace_agents_template(prefer_installed=True)

    if not agents_path.exists():
        if agents_path.is_symlink():
            agents_path.unlink()
        warn(
            f"workspace {workspace_label_text} is missing AGENTS.md; "
            "restoring managed file"
        )
        if project_template_path.exists():
            link_or_copy(project_template_path, agents_path)
            source_text = project_template_path.read_text(encoding="utf-8")
        else:
            source_text = canonical_agents
            agents_path.write_text(source_text, encoding="utf-8")
        if source_text == canonical_agents:
            config.update_workspace_managed_files(
                workspace_dir, {"AGENTS.md": config.hash_text(source_text)}
            )

    if not persist_path.exists():
        if persist_path.is_symlink():
            persist_path.unlink()
        warn(
            f"workspace {workspace_label_text} is missing PERSIST.md; "
            "restoring managed file"
        )
        persist_text = templates.render_persist(
            workspace_config.workspace.branch_pr,
            workspace_config.workspace.branch_history,
        )
        persist_path.write_text(persist_text, encoding="utf-8")


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

    git_path = config.resolve_git_path(config_payload)

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
    ticket_refs = normalize_ticket_refs(getattr(args, "ticket", None))

    if not workspace_name_input:
        if ticket_refs:
            ticket_name = ticket_refs[0]
            ticket_id, ticket_title = split_ticket_reference(ticket_name)
            if not ticket_id:
                die("ticket name did not produce a valid workspace name")
            if not ticket_title:
                ticket_title = resolve_ticket_title(
                    ticket_name,
                    ticket_provider=config_payload.tickets.provider or "none",
                    default_project=config_payload.tickets.default_project,
                    project_origin=project_origin,
                    repo_root=repo_root,
                )
            if ticket_title is None:
                ticket_title = prompt("Ticket title (optional)", allow_empty=True)
                if ticket_title == "":
                    ticket_title = None
            normalized_ticket = format_ticket_workspace_name(ticket_id, ticket_title)
            if not normalized_ticket:
                die("ticket name did not produce a valid workspace name")
            workspace_name_input = normalized_ticket
        else:
            if raw_branch:
                die("workspace branch is required when using --raw")
            workspace_name_input = resolve_implicit_workspace_name(
                repo_root, config_payload, git_path=git_path
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
            git_path,
        )
    )
    if not workspace_branch:
        die("workspace branch is required")

    term.apply_workspace_identity(project_enlistment, workspace_branch)
    say(f"Workspace {workspace_branch} at {workspace_dir}")
    workspace_env = workspace.workspace_environment(
        project_enlistment,
        workspace_branch,
        workspace_dir,
    )

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
        workspace_managed_updates = config.managed_workspace_agents_updates(
            workspace_dir
        )
        workspace_managed_updates.update(
            config.managed_workspace_persist_updates(workspace_dir)
        )
        config.update_workspace_managed_files(workspace_dir, workspace_managed_updates)
        workspace_policy_target = workspace_dir / "SUCCESS.md"
        if not workspace_policy_target.exists():
            ticket_template_path = (
                project_dir / paths.TEMPLATES_DIRNAME / "SUCCESS.ticket.md"
            )
            success_template_path = project_dir / paths.TEMPLATES_DIRNAME / "SUCCESS.md"
            workspace_policy_text: str | None = None
            workspace_policy_template: Path | None = None

            if ticket_refs:
                if ticket_template_path.exists():
                    workspace_policy_text = ticket_template_path.read_text(
                        encoding="utf-8"
                    )
                elif not project_success_is_custom(project_dir):
                    workspace_policy_text = templates.ticket_success_md_template(
                        prefer_installed=True
                    )
                else:
                    workspace_policy_template = (
                        success_template_path
                        if success_template_path.exists()
                        else None
                    )
            else:
                workspace_policy_template = (
                    success_template_path if success_template_path.exists() else None
                )

            if workspace_policy_text is not None:
                ticket_config = config_payload.tickets
                ticket_provider = ticket_config.provider or "ticket"
                if ticket_provider == "none":
                    ticket_provider = "ticket"
                ticket_id = ticket_refs[0] if ticket_refs else "unknown"
                project_name = (
                    ticket_config.default_project
                    or project_section.origin
                    or project_section.repo_url
                    or project_dir.name
                )
                rendered = render_ticket_success_template(
                    workspace_policy_text,
                    ticket_provider=ticket_provider,
                    ticket_id=ticket_id,
                    project_name=project_name,
                )
                workspace_policy_target.write_text(rendered, encoding="utf-8")
            elif workspace_policy_template is not None:
                shutil.copyfile(workspace_policy_template, workspace_policy_target)
        workspace_config = config.load_workspace_config(workspace_config_file)
        if not workspace_config:
            die("failed to load workspace config")

    if ticket_refs:
        if not is_new_workspace:
            warn("tickets were provided for an existing workspace; skipping")
        else:
            user_path = paths.workspace_config_user_path(workspace_dir)
            user_config = (
                config.load_workspace_user_config(user_path)
                or config.WorkspaceUserConfig()
            )
            merged_refs = merge_ticket_refs(user_config.tickets.refs, ticket_refs)
            tickets_section = user_config.tickets.model_copy(
                update={"refs": merged_refs}
            )
            user_config = user_config.model_copy(update={"tickets": tickets_section})
            config.write_workspace_user_config(user_path, user_config)
            append_ticket_section(workspace_dir / "SUCCESS.md", merged_refs)

    if workspace_config is not None:
        backfill_missing_workspace_files(
            workspace_dir=workspace_dir,
            workspace_config=workspace_config,
            project_dir=project_dir,
        )
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

    edit_override = getattr(args, "edit", None)
    if edit_override is None:
        should_open_editor = is_new_workspace
    else:
        should_open_editor = bool(edit_override)
    editor_cmd: list[str] | None = None
    if not repo_dir.exists():
        exec.run_command(
            git.git_command(
                ["clone", project_repo_url, str(repo_dir)], git_path=git_path
            )
        )
    else:
        if not git.git_is_repo(repo_dir, git_path=git_path):
            die("repo exists but is not a git repository")
        if origin_raw is not None:
            remote_check = subprocess.run(
                git.git_command(
                    ["-C", str(repo_dir), "remote", "get-url", "origin"],
                    git_path=git_path,
                ),
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
        tag_locations: list[tuple[str, Path]] = []
        if git.git_tag_exists(repo_dir, finalization_tag, git_path=git_path):
            tag_locations.append(("workspace repo", repo_dir))
        if project_enlistment:
            main_repo_dir = Path(project_enlistment)
            if main_repo_dir != repo_dir and git.git_tag_exists(
                main_repo_dir, finalization_tag, git_path=git_path
            ):
                tag_locations.append(("main enlistment repo", main_repo_dir))
        if tag_locations and confirm_remove_finalization_tag(
            workspace_branch, finalization_tag
        ):
            for label, tag_repo in tag_locations:
                result = exec.try_run_command(
                    git.git_command(
                        ["-C", str(tag_repo), "tag", "-d", finalization_tag],
                        git_path=git_path,
                    )
                )
                if result is None or result.returncode != 0:
                    warn(
                        f"failed to delete finalization tag in {label}; "
                        "continuing with open"
                    )

    current_branch = git.git_current_branch(repo_dir, git_path=git_path)
    if current_branch is None:
        die("failed to determine repo branch")
    repo_clean = git.git_is_clean(repo_dir, git_path=git_path)
    if repo_clean is None:
        die("failed to determine repo status")

    default_branch = git.git_default_branch(repo_dir, git_path=git_path)
    if not default_branch:
        die("failed to determine default branch from repo")
    allow_mainline = config_payload.project.allow_mainline_workspace
    if workspace_branch == default_branch and not allow_mainline:
        die(
            "workspace branch is the default branch; "
            "use `atelier new` to create a mainline workspace"
        )

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
        exec.run_command(
            git.git_command(
                ["-C", str(repo_dir), "checkout", default_branch], git_path=git_path
            )
        )

    local_branch = git.git_ref_exists(
        repo_dir, f"refs/heads/{workspace_branch}", git_path=git_path
    )
    remote_branch = git.git_ref_exists(
        repo_dir, f"refs/remotes/origin/{workspace_branch}", git_path=git_path
    )
    if not remote_branch:
        remote_branch = (
            git.git_has_remote_branch(repo_dir, workspace_branch, git_path=git_path)
            is True
        )
        if remote_branch:
            exec.run_command(
                git.git_command(
                    ["-C", str(repo_dir), "fetch", "origin", workspace_branch],
                    git_path=git_path,
                )
            )
    existing_branch = local_branch or remote_branch

    if skip_workspace_checkout:
        pass
    elif local_branch:
        exec.run_command(
            git.git_command(
                ["-C", str(repo_dir), "checkout", workspace_branch], git_path=git_path
            )
        )
    elif remote_branch:
        exec.run_command(
            git.git_command(
                [
                    "-C",
                    str(repo_dir),
                    "checkout",
                    "-b",
                    workspace_branch,
                    "--track",
                    f"origin/{workspace_branch}",
                ],
                git_path=git_path,
            )
        )
    else:
        exec.run_command(
            git.git_command(
                ["-C", str(repo_dir), "checkout", "-b", workspace_branch],
                git_path=git_path,
            )
        )

    agent_default = config_payload.agent.default
    agent_spec = agents.get_agent(agent_default)
    if agent_spec is None:
        die(f"unsupported agent {agent_default!r}")

    agent_options = list(config_payload.agent.options.get(agent_spec.name, []))
    if bool(getattr(args, "yolo", False)):
        agent_options = agents.apply_yolo_options(agent_spec, agent_options)

    if is_new_workspace and existing_branch:
        workspace.write_background_snapshot(
            background_path,
            repo_dir,
            default_branch,
            workspace_branch,
            git_path=git_path,
            provider=config_payload.project.provider,
        )

    if should_open_editor and workspace_policy_path is not None:
        if editor_cmd is None:
            editor_cmd = editor.resolve_editor_command(config_payload, role="edit")
        try:
            workspace_target = workspace_policy_path.relative_to(workspace_dir)
        except ValueError:
            workspace_target = workspace_policy_path
        exec.run_command(
            [*editor_cmd, str(workspace_target)],
            cwd=workspace_dir,
            env=workspace_env,
        )

    workspace_uid: str | None = None
    if workspace_config is not None:
        workspace_uid = workspace_config.workspace.uid

    session_id: str | None = None
    if agent_spec.name == "codex" and workspace_config is not None:
        stored_session = workspace_config.workspace.session
        if stored_session and stored_session.agent == agent_spec.name:
            session_id = stored_session.id
            if not session_id and stored_session.resume_command:
                session_id, _ = codex.parse_codex_resume_line(
                    stored_session.resume_command
                )
    if session_id is None:
        session_id = agents.find_resume_session(
            agent_spec, project_enlistment, workspace_branch, workspace_uid
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
        if agent_spec.name == "codex":
            result = codex.run_codex_command(
                resume_cmd,
                cwd=resume_cwd,
                allow_missing=True,
                env=workspace_env,
            )
            persist_codex_session(workspace_dir, result)
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
        else:
            result = exec.run_command_status(
                resume_cmd,
                cwd=resume_cwd,
                env=workspace_env,
            )
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

    opening_prompt = workspace.workspace_session_identifier(
        project_enlistment, workspace_branch, workspace_uid
    )
    if agent_spec.name != "codex":
        opening_prompt = ""
    say(f"Starting new {agent_spec.display_name} session")
    start_cmd, start_cwd = agent_spec.build_start_command(
        workspace_dir, agent_options, opening_prompt
    )
    if agent_spec.name == "codex":
        result = codex.run_codex_command(start_cmd, cwd=start_cwd, env=workspace_env)
        persist_codex_session(workspace_dir, result)
        if result is None:
            die(f"missing required command: {start_cmd[0]}")
        if result.returncode != 0:
            die(f"command failed: {' '.join(start_cmd)}")
    else:
        exec.run_command(start_cmd, cwd=start_cwd, env=workspace_env)


def resolve_implicit_workspace_name(
    repo_root: Path,
    config_payload: object,
    *,
    git_path: str | None = None,
) -> str:
    """Resolve the current branch for implicit ``atelier open`` calls.

    The branch is accepted only when it is non-default (or explicitly allowed),
    clean, and fully pushed to its upstream.

    Args:
        repo_root: Path to the git repository root.
        config_payload: Config payload used to check default-branch allowances.

    Returns:
        The current branch name when it meets the implicit-open criteria.

    Example:
        >>> from pathlib import Path
        >>> isinstance(repo_root := Path("."), Path)
        True
    """
    default_branch = git.git_default_branch(repo_root, git_path=git_path)
    if not default_branch:
        die("failed to determine default branch from repo")

    current_branch = git.git_current_branch(repo_root, git_path=git_path)
    if not current_branch:
        die("failed to determine current branch")
    allow_mainline = False
    project_section = getattr(config_payload, "project", None)
    if project_section is not None:
        allow_mainline = bool(
            getattr(project_section, "allow_mainline_workspace", False)
        )
    if current_branch == default_branch:
        if allow_mainline:
            return current_branch
        die(
            "implicit open requires a non-default branch; "
            f"current branch is {default_branch!r}"
        )

    clean = git.git_is_clean(repo_root, git_path=git_path)
    if clean is not True:
        die("implicit open requires a clean working tree")

    fully_pushed = git.git_branch_fully_pushed(repo_root, git_path=git_path)
    if fully_pushed is None:
        die("implicit open requires the branch to be pushed to its upstream")
    if fully_pushed is False:
        die("implicit open requires the branch to be fully pushed to its upstream")

    return current_branch

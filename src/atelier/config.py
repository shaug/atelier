"""Configuration helpers for Atelier projects and workspaces.

This module reads and writes ``config.json`` files, validates them with
Pydantic models, and normalizes CLI overrides.

Example:
    >>> from atelier.config import utc_now
    >>> utc_now().endswith("Z")
    True
"""

import datetime as dt
import hashlib
import json
import shlex
import shutil
from pathlib import Path

from pydantic import BaseModel, ValidationError

from . import __version__, paths, templates
from .editor import system_editor_default
from .io import die, prompt, select
from .models import (
    BRANCH_HISTORY_VALUES,
    UPGRADE_POLICY_VALUES,
    AgentConfig,
    AtelierSection,
    BranchConfig,
    EditorConfig,
    ProjectConfig,
    ProjectSection,
    WorkspaceConfig,
)
from .paths import workspace_config_path


def utc_now() -> str:
    """Return the current UTC timestamp in ISO-8601 format.

    Returns:
        UTC timestamp like ``2026-01-18T12:34:56Z``.

    Example:
        >>> timestamp = utc_now()
        >>> timestamp.endswith("Z")
        True
    """
    now = dt.datetime.now(tz=dt.timezone.utc).replace(microsecond=0)
    return now.isoformat().replace("+00:00", "Z")


def hash_text(text: str) -> str:
    """Return the SHA-256 hex digest for text content."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def hash_file(path: Path) -> str:
    """Return the SHA-256 hex digest for a file's contents."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict | None:
    """Load a JSON file if it exists.

    Args:
        path: Path to the JSON file.

    Returns:
        Parsed payload as a dict, or ``None`` if the file does not exist.

    Example:
        >>> from pathlib import Path
        >>> load_json(Path("missing.json")) is None
        True
    """
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path: Path, payload: dict | BaseModel) -> None:
    """Write a JSON payload to disk.

    Args:
        path: Path to the JSON file to write.
        payload: Dict or Pydantic model to serialize.

    Returns:
        None.

    Example:
        >>> from pathlib import Path
        >>> write_json(Path("/tmp/atelier-example.json"), {"ok": True})
    """
    if isinstance(payload, BaseModel):
        payload = payload.model_dump()
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
        fh.write("\n")


def update_project_managed_files(project_dir: Path, updates: dict[str, str]) -> None:
    """Update managed file hashes in a project config."""
    if not updates:
        return
    config_path = paths.project_config_path(project_dir)
    config_payload = load_project_config(config_path)
    if not config_payload:
        die("no Atelier project config found for managed file updates")
    atelier_section = config_payload.atelier
    managed = dict(atelier_section.managed_files)
    managed.update(updates)
    atelier_section = atelier_section.model_copy(update={"managed_files": managed})
    config_payload = config_payload.model_copy(update={"atelier": atelier_section})
    write_json(config_path, config_payload)


def update_workspace_managed_files(
    workspace_dir: Path, updates: dict[str, str]
) -> None:
    """Update managed file hashes in a workspace config."""
    if not updates:
        return
    config_path = workspace_config_path(workspace_dir)
    workspace_config = load_workspace_config(config_path)
    if not workspace_config:
        die("no workspace config found for managed file updates")
    atelier_section = workspace_config.atelier
    managed = dict(atelier_section.managed_files)
    managed.update(updates)
    atelier_section = atelier_section.model_copy(update={"managed_files": managed})
    workspace_config = workspace_config.model_copy(update={"atelier": atelier_section})
    write_json(config_path, workspace_config)


def managed_project_agents_updates(project_dir: Path) -> dict[str, str]:
    """Return managed hashes for project AGENTS files when canonical."""
    canonical = templates.project_agents_template(prefer_installed=True)
    updates: dict[str, str] = {}
    candidates = [
        ("AGENTS.md", project_dir / "AGENTS.md"),
        (
            f"{paths.TEMPLATES_DIRNAME}/AGENTS.md",
            project_dir / paths.TEMPLATES_DIRNAME / "AGENTS.md",
        ),
    ]
    for rel_path, path in candidates:
        if not path.exists():
            continue
        content = path.read_text(encoding="utf-8")
        if content == canonical:
            updates[rel_path] = hash_text(content)
    success_path = project_dir / paths.TEMPLATES_DIRNAME / "SUCCESS.md"
    if success_path.exists():
        success_content = success_path.read_text(encoding="utf-8")
        success_canonical = templates.success_md_template(prefer_installed=True)
        if success_content == success_canonical:
            updates[f"{paths.TEMPLATES_DIRNAME}/SUCCESS.md"] = hash_text(
                success_content
            )
    return updates


def managed_workspace_agents_updates(workspace_dir: Path) -> dict[str, str]:
    """Return managed hashes for workspace AGENTS files when canonical."""
    agents_path = workspace_dir / "AGENTS.md"
    if not agents_path.exists():
        return {}
    content = agents_path.read_text(encoding="utf-8")
    canonical = templates.workspace_agents_template(prefer_installed=True)
    if content != canonical:
        return {}
    return {"AGENTS.md": hash_text(content)}


def parse_project_config(
    payload: dict, source: Path | str | None = None
) -> ProjectConfig:
    """Validate a project config payload.

    Args:
        payload: Raw config payload.
        source: Optional path or label for error messages.

    Returns:
        Parsed ``ProjectConfig``.

    Example:
        >>> parse_project_config({"project": {"origin": "example.com/repo"}})
        ProjectConfig(...)
    """
    try:
        return ProjectConfig.model_validate(payload)
    except ValidationError as exc:
        location = f" at {source}" if source else ""
        die(f"invalid project config{location}:\n{exc}")


def load_project_config(path: Path) -> ProjectConfig | None:
    """Load and validate a project config from disk.

    Args:
        path: Path to ``config.json`` in the project directory.

    Returns:
        Parsed ``ProjectConfig`` or ``None`` when missing/empty.

    Example:
        >>> from pathlib import Path
        >>> load_project_config(Path("missing.json")) is None
        True
    """
    payload = load_json(path)
    if not payload:
        return None
    return parse_project_config(payload, path)


def parse_workspace_config(
    payload: dict, source: Path | str | None = None
) -> WorkspaceConfig:
    """Validate a workspace config payload.

    Args:
        payload: Raw config payload.
        source: Optional path or label for error messages.

    Returns:
        Parsed ``WorkspaceConfig``.

    Example:
        >>> parse_workspace_config({"workspace": {"branch": "feat/demo"}})
        WorkspaceConfig(...)
    """
    try:
        return WorkspaceConfig.model_validate(payload)
    except ValidationError as exc:
        location = f" at {source}" if source else ""
        die(f"invalid workspace config{location}:\n{exc}")


def load_workspace_config(path: Path) -> WorkspaceConfig | None:
    """Load and validate a workspace config from disk.

    Args:
        path: Path to ``config.json`` in the workspace directory.

    Returns:
        Parsed ``WorkspaceConfig`` or ``None`` when missing/empty.

    Example:
        >>> from pathlib import Path
        >>> load_workspace_config(Path("missing.json")) is None
        True
    """
    payload = load_json(path)
    if not payload:
        return None
    return parse_workspace_config(payload, path)


def resolve_branch_config(config: ProjectConfig | dict) -> BranchConfig:
    """Resolve a ``BranchConfig`` from a project config or raw dict.

    Args:
        config: ``ProjectConfig`` instance or raw payload dict.

    Returns:
        ``BranchConfig`` instance.

    Example:
        >>> resolve_branch_config({"branch": {"prefix": "scott/"}})
        BranchConfig(...)
    """
    if isinstance(config, ProjectConfig):
        return config.branch
    branch = config.get("branch") if isinstance(config, dict) else None
    try:
        return BranchConfig.model_validate(branch or {})
    except ValidationError as exc:
        die(f"invalid branch config:\n{exc}")


def resolve_branch_pr(branch_config: BranchConfig) -> bool:
    """Return whether pull requests are expected for the branch config.

    Args:
        branch_config: Branch configuration to read from.

    Returns:
        ``True`` when pull requests are expected.

    Example:
        >>> resolve_branch_pr(BranchConfig())
        True
    """
    return branch_config.pr


def normalize_branch_history(value: object, source: str) -> str:
    """Normalize a branch history string or fail with a helpful error.

    Args:
        value: Raw history value (string).
        source: Label to include in error messages.

    Returns:
        Normalized history string (``manual``, ``squash``, ``merge``, ``rebase``).

    Example:
        >>> normalize_branch_history("squash", "branch.history")
        'squash'
    """
    if not isinstance(value, str):
        die(f"{source} must be one of: " + ", ".join(BRANCH_HISTORY_VALUES))
    normalized = value.strip().lower()
    if normalized not in BRANCH_HISTORY_VALUES:
        die(f"{source} must be one of: " + ", ".join(BRANCH_HISTORY_VALUES))
    return normalized


def resolve_branch_history(branch_config: BranchConfig) -> str:
    """Return the branch history policy string.

    Args:
        branch_config: Branch configuration to read from.

    Returns:
        One of ``manual``, ``squash``, ``merge``, ``rebase``.

    Example:
        >>> resolve_branch_history(BranchConfig())
        'manual'
    """
    return branch_config.history


def normalize_upgrade_policy(value: object, source: str) -> str:
    """Normalize an upgrade policy string or fail with a helpful error.

    Args:
        value: Raw policy value (string).
        source: Label to include in error messages.

    Returns:
        Normalized policy string (``always``, ``ask``, ``manual``).
    """
    if not isinstance(value, str):
        die(f"{source} must be one of: " + ", ".join(UPGRADE_POLICY_VALUES))
    normalized = value.strip().lower()
    if normalized not in UPGRADE_POLICY_VALUES:
        die(f"{source} must be one of: " + ", ".join(UPGRADE_POLICY_VALUES))
    return normalized


def resolve_upgrade_policy(
    value: object | None, source: str = "atelier.upgrade"
) -> str:
    """Resolve an upgrade policy value, defaulting to ``ask`` when missing."""
    if value is None:
        return "ask"
    return normalize_upgrade_policy(value, source)


def parse_branch_pr_override(value: object) -> bool:
    """Parse a ``--branch-pr`` value into a boolean.

    Args:
        value: Raw override (bool or string).

    Returns:
        Parsed boolean.

    Example:
        >>> parse_branch_pr_override("true")
        True
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "1"}:
            return True
        if normalized in {"false", "no", "0"}:
            return False
    die("--branch-pr must be true or false")


def resolve_branch_overrides(
    args: object,
) -> tuple[bool | None, str | None]:
    """Resolve CLI overrides for branch settings.

    Args:
        args: CLI argument object with ``branch_pr`` and ``branch_history``.

    Returns:
        Tuple of ``(branch_pr_override, branch_history_override)`` where each
        value is ``None`` when unset.

    Example:
        >>> resolve_branch_overrides(type("Args", (), {"branch_pr": None, "branch_history": None})())
        (None, None)
    """
    branch_pr_override = getattr(args, "branch_pr", None)
    branch_history_override = getattr(args, "branch_history", None)
    resolved_pr = None
    resolved_history = None
    if branch_pr_override is not None:
        resolved_pr = parse_branch_pr_override(branch_pr_override)
    if branch_history_override is not None:
        resolved_history = normalize_branch_history(
            branch_history_override, "--branch-history"
        )
    return resolved_pr, resolved_history


def read_workspace_branch_settings(
    workspace_dir: Path,
) -> tuple[bool | None, str | None]:
    """Read branch settings from a workspace config.

    Args:
        workspace_dir: Path to the workspace directory.

    Returns:
        Tuple of ``(branch_pr, branch_history)`` or ``(None, None)`` when missing.

    Example:
        >>> from pathlib import Path
        >>> read_workspace_branch_settings(Path("missing"))
        (None, None)
    """
    config_path = workspace_config_path(workspace_dir)
    workspace_config = load_workspace_config(config_path)
    if not workspace_config:
        return None, None
    return (
        workspace_config.workspace.branch_pr,
        workspace_config.workspace.branch_history,
    )


def read_arg(args: object | None, name: str) -> object | None:
    """Safely read an attribute from an args object.

    Args:
        args: CLI argument object or ``None``.
        name: Attribute name to look up.

    Returns:
        Attribute value or ``None`` when missing.

    Example:
        >>> read_arg(None, "branch_prefix") is None
        True
    """
    if args is None:
        return None
    return getattr(args, name, None)


def _path_has_value(payload: dict | None, *path: str) -> bool:
    if not isinstance(payload, dict):
        return False
    current: object = payload
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return False
        current = current[key]
    return current is not None


def user_config_missing_fields(payload: dict | None) -> list[str]:
    """Return user-editable config fields missing from a payload."""
    missing: list[str] = []
    fields = [
        ("branch", "prefix"),
        ("branch", "pr"),
        ("branch", "history"),
        ("agent", "default"),
        ("editor", "default"),
    ]
    for path in fields:
        if not _path_has_value(payload, *path):
            missing.append(".".join(path))
    return missing


def user_config_payload(config: ProjectConfig) -> dict:
    """Return user-editable config sections as a dict."""
    return {
        "branch": config.branch.model_dump(),
        "agent": config.agent.model_dump(),
        "editor": config.editor.model_dump(),
    }


def _default_editor_command(config_payload: ProjectConfig) -> str:
    editor_prompt_default = None
    editor_default_default = config_payload.editor.default
    if editor_default_default:
        editor_options_default = config_payload.editor.options.get(
            editor_default_default, []
        )
        if editor_options_default:
            editor_prompt_default = shlex.join(
                [editor_default_default, *editor_options_default]
            )
        else:
            editor_prompt_default = editor_default_default
    if not editor_prompt_default:
        if shutil.which("cursor"):
            editor_prompt_default = "cursor"
        else:
            editor_prompt_default = system_editor_default()
    return editor_prompt_default


def default_user_config() -> ProjectConfig:
    """Return default user-editable config values."""
    base = ProjectConfig()
    editor_prompt_default = _default_editor_command(base)
    editor_parts = shlex.split(editor_prompt_default) if editor_prompt_default else []
    editor_default = editor_parts[0] if editor_parts else None
    editor_options: dict[str, list[str]] = {}
    if editor_default:
        editor_options[editor_default] = editor_parts[1:]
    agent_options = {"codex": []}
    return base.model_copy(
        update={
            "branch": base.branch,
            "agent": AgentConfig(default="codex", options=agent_options),
            "editor": EditorConfig(default=editor_default, options=editor_options),
        }
    )


def load_installed_defaults(path: Path | None = None) -> ProjectConfig:
    """Load installed defaults for user-editable config values."""
    defaults_path = path or paths.installed_config_path()
    payload = load_json(defaults_path)
    default_config = default_user_config()
    if not payload:
        return default_config
    parsed = parse_project_config(payload, defaults_path)
    branch = parsed.branch
    if not _path_has_value(payload, "branch", "prefix"):
        branch = branch.model_copy(update={"prefix": default_config.branch.prefix})
    if not _path_has_value(payload, "branch", "pr"):
        branch = branch.model_copy(update={"pr": default_config.branch.pr})
    if not _path_has_value(payload, "branch", "history"):
        branch = branch.model_copy(update={"history": default_config.branch.history})

    agent = parsed.agent
    if not _path_has_value(payload, "agent", "default"):
        agent = agent.model_copy(update={"default": default_config.agent.default})
    agent_options = dict(agent.options)
    agent_options.setdefault("codex", [])
    agent = agent.model_copy(update={"options": agent_options})

    editor_config = parsed.editor
    if not _path_has_value(payload, "editor", "default"):
        editor_config = editor_config.model_copy(
            update={"default": default_config.editor.default}
        )
    if editor_config.default:
        options = dict(editor_config.options)
        if editor_config.default not in options:
            options.update(default_config.editor.options)
        editor_config = editor_config.model_copy(update={"options": options})

    parsed = parsed.model_copy(
        update={"branch": branch, "agent": agent, "editor": editor_config}
    )
    return parsed


def write_installed_defaults(
    config_payload: ProjectConfig, path: Path | None = None
) -> None:
    """Write installed defaults for user-editable config values."""
    defaults_path = path or paths.installed_config_path()
    paths.ensure_dir(defaults_path.parent)
    write_json(defaults_path, user_config_payload(config_payload))


def build_project_config(
    existing: ProjectConfig | dict,
    enlistment_path: str,
    origin: str | None,
    origin_raw: str | None,
    args: object | None,
    *,
    prompt_missing_only: bool = False,
    raw_existing: dict | None = None,
    allow_editor_empty: bool = False,
) -> ProjectConfig:
    """Build a new project config, prompting when necessary.

    Args:
        existing: Existing config payload or ``ProjectConfig``.
        enlistment_path: Resolved local enlistment path.
        origin: Normalized repo origin (e.g., ``github.com/org/repo``) or ``None``.
        origin_raw: Raw origin URL from Git or ``None``.
        args: CLI argument object for overrides, or ``None`` to prompt.
        prompt_missing_only: When true, prompt only for missing user fields.
        raw_existing: Raw payload used to detect missing fields.
        allow_editor_empty: When true, allow clearing the editor command.

    Returns:
        ``ProjectConfig`` with updated project, branch, agent, editor, and
        atelier metadata.

    Example:
        >>> build_project_config({}, "/repo", "example.com/repo", "https://example.com/repo", None)
        ProjectConfig(...)
    """
    existing_config = (
        existing
        if isinstance(existing, ProjectConfig)
        else parse_project_config(existing)
    )
    raw_payload = existing if isinstance(existing, dict) else raw_existing

    def should_prompt(*path: str) -> bool:
        if not prompt_missing_only:
            return True
        return not _path_has_value(raw_payload, *path)

    branch_config = existing_config.branch
    branch_prefix_default = branch_config.prefix or ""
    branch_prefix_arg = read_arg(args, "branch_prefix")
    if branch_prefix_arg is not None:
        branch_prefix = str(branch_prefix_arg)
    elif should_prompt("branch", "prefix"):
        branch_prefix = prompt("Branch prefix (optional)", branch_prefix_default)
    else:
        branch_prefix = branch_config.prefix

    branch_pr_default = branch_config.pr
    branch_history_default = branch_config.history

    branch_pr_arg = read_arg(args, "branch_pr")
    if branch_pr_arg is not None:
        branch_pr = parse_branch_pr_override(branch_pr_arg)
    elif should_prompt("branch", "pr"):
        branch_pr_prompt_default = "true" if branch_pr_default else "false"
        branch_pr_input = select(
            "Expect pull requests for workspace branches",
            ("true", "false"),
            branch_pr_prompt_default,
        )
        branch_pr = parse_branch_pr_override(branch_pr_input)
    else:
        branch_pr = branch_pr_default

    branch_history_arg = read_arg(args, "branch_history")
    if branch_history_arg is not None:
        branch_history = normalize_branch_history(
            branch_history_arg, "--branch-history"
        )
    elif should_prompt("branch", "history"):
        branch_history_input = select(
            "Branch history policy",
            BRANCH_HISTORY_VALUES,
            branch_history_default,
        )
        branch_history = normalize_branch_history(
            branch_history_input, "branch.history"
        )
    else:
        branch_history = branch_history_default

    agent_default_default = existing_config.agent.default or "codex"
    agent_arg = read_arg(args, "agent")
    if agent_arg is not None:
        agent_default = str(agent_arg)
    elif should_prompt("agent", "default"):
        agent_default = select("Agent", ("codex",), agent_default_default)
    else:
        agent_default = agent_default_default
    if agent_default != "codex":
        die("only 'codex' is supported as the agent in v2")

    editor_prompt_default = _default_editor_command(existing_config)
    editor_arg = read_arg(args, "editor")
    editor_input = None
    if editor_arg is not None:
        editor_input = str(editor_arg)
    elif should_prompt("editor", "default"):
        editor_input = prompt(
            "Editor command",
            editor_prompt_default,
            required=not allow_editor_empty,
            allow_empty=allow_editor_empty,
        )
    editor_default = existing_config.editor.default
    editor_input_options: list[str] = []
    if editor_input is not None:
        editor_parts = shlex.split(editor_input)
        if editor_parts:
            editor_default = editor_parts[0]
            editor_input_options = editor_parts[1:]
        else:
            editor_default = None
            editor_input_options = []

    atelier_created_at = existing_config.atelier.created_at or utc_now()
    atelier_version = existing_config.atelier.version or __version__
    atelier_upgrade = resolve_upgrade_policy(existing_config.atelier.upgrade)
    atelier_managed_files = dict(existing_config.atelier.managed_files)

    agent_options = dict(existing_config.agent.options)
    agent_options.setdefault("codex", [])

    editor_options = dict(existing_config.editor.options)
    if editor_input_options and editor_default:
        editor_options = {**editor_options, editor_default: editor_input_options}

    project_origin = origin or existing_config.project.origin
    project_repo_url = origin_raw or existing_config.project.repo_url

    return ProjectConfig(
        project=ProjectSection(
            enlistment=enlistment_path,
            origin=project_origin,
            repo_url=project_repo_url,
        ),
        branch=BranchConfig(prefix=branch_prefix, pr=branch_pr, history=branch_history),
        agent=AgentConfig(default=agent_default, options=agent_options),
        editor=EditorConfig(default=editor_default, options=editor_options),
        atelier=AtelierSection(
            version=atelier_version,
            created_at=atelier_created_at,
            upgrade=atelier_upgrade,
            managed_files=atelier_managed_files,
        ),
    )

"""Configuration helpers for Atelier projects.

This module reads and writes ``config.sys.json``/``config.user.json`` files,
validates them with Pydantic models, and normalizes CLI overrides.

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

from . import __version__, agents, paths, pr_strategy
from . import command as command_util
from .editor import system_editor_default
from .io import die, prompt, select
from .models import (
    BRANCH_HISTORY_VALUES,
    BRANCH_SQUASH_MESSAGE_VALUES,
    UPGRADE_POLICY_VALUES,
    AgentConfig,
    AtelierSection,
    AtelierUserSection,
    BranchConfig,
    EditorConfig,
    ProjectConfig,
    ProjectSection,
    ProjectSystemConfig,
    ProjectUserConfig,
)


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


def _backup_legacy_config(path: Path) -> None:
    backup_path = path.with_suffix(".json.bak")
    if backup_path.exists():
        return
    shutil.move(path, backup_path)


def _split_project_payload(payload: dict) -> tuple[dict, dict]:
    user_payload: dict = {}
    for key in ("branch", "agent", "editor", "git"):
        if key in payload:
            user_payload[key] = payload.get(key)
    project_payload = payload.get("project")
    if isinstance(project_payload, dict):
        project_user: dict = {}
        for key in ("provider", "provider_url", "owner"):
            if key in project_payload:
                project_user[key] = project_payload.get(key)
        if project_user:
            user_payload["project"] = project_user
    atelier_payload = dict(payload.get("atelier", {}) or {})
    upgrade = atelier_payload.pop("upgrade", None)
    if "atelier" in payload and "upgrade" in payload.get("atelier", {}):
        user_payload["atelier"] = {"upgrade": upgrade}
    system_payload = dict(payload)
    for key in ("branch", "agent", "editor", "git"):
        system_payload.pop(key, None)
    project_system = dict(system_payload.get("project", {}) or {})
    for key in ("provider", "provider_url", "owner"):
        project_system.pop(key, None)
    if "project" in system_payload:
        system_payload["project"] = project_system
    system_payload["atelier"] = atelier_payload
    return system_payload, user_payload


def parse_project_system_config(
    payload: dict, source: Path | str | None = None
) -> ProjectSystemConfig:
    """Validate a project system config payload."""
    try:
        return ProjectSystemConfig.model_validate(payload)
    except ValidationError as exc:
        location = f" at {source}" if source else ""
        die(f"invalid project system config{location}:\n{exc}")


def parse_project_user_config(
    payload: dict, source: Path | str | None = None
) -> ProjectUserConfig:
    """Validate a project user config payload."""
    try:
        return ProjectUserConfig.model_validate(payload)
    except ValidationError as exc:
        location = f" at {source}" if source else ""
        die(f"invalid project user config{location}:\n{exc}")


def _migrate_legacy_project_config(project_dir: Path) -> None:
    sys_path = paths.project_config_sys_path(project_dir)
    user_path = paths.project_config_user_path(project_dir)
    if sys_path.exists() or user_path.exists():
        return
    legacy_path = paths.project_config_legacy_path(project_dir)
    payload = load_json(legacy_path)
    if not payload:
        return
    system_payload, user_payload = _split_project_payload(payload)
    system_config = parse_project_system_config(system_payload, legacy_path)
    user_config = parse_project_user_config(user_payload, legacy_path)
    write_json(sys_path, system_config)
    write_json(user_path, user_config)
    _backup_legacy_config(legacy_path)


def _migrate_legacy_installed_config() -> None:
    user_path = paths.installed_config_path()
    if user_path.exists():
        return
    legacy_path = paths.installed_legacy_config_path()
    payload = load_json(legacy_path)
    if not payload:
        return
    user_config = parse_project_user_config(payload, legacy_path)
    paths.ensure_dir(user_path.parent)
    write_json(user_path, user_config)
    _backup_legacy_config(legacy_path)


def load_project_system_config(path: Path) -> ProjectSystemConfig | None:
    """Load and validate a project system config from disk."""
    project_dir = path.parent
    _migrate_legacy_project_config(project_dir)
    payload = load_json(path)
    if not payload:
        return None
    return parse_project_system_config(payload, path)


def load_project_user_config(path: Path) -> ProjectUserConfig | None:
    """Load and validate a project user config from disk."""
    project_dir = path.parent
    _migrate_legacy_project_config(project_dir)
    payload = load_json(path)
    if not payload:
        return None
    return parse_project_user_config(payload, path)


def merge_project_configs(
    system_config: ProjectSystemConfig, user_config: ProjectUserConfig | None
) -> ProjectConfig:
    """Merge system and user project configs into a full config."""
    system_payload = system_config.model_dump()
    user_payload = (user_config or ProjectUserConfig()).model_dump()
    merged = dict(system_payload)
    for key in ("branch", "agent", "editor", "git"):
        merged[key] = user_payload.get(key, {})
    system_project = system_payload.get("project", {}) if system_payload else {}
    user_project = user_payload.get("project", {}) if user_payload else {}
    if isinstance(system_project, dict):
        project_payload = dict(system_project)
    else:
        project_payload = {}
    if isinstance(user_project, dict):
        for key in ("provider", "provider_url", "owner"):
            value = user_project.get(key)
            if value is not None:
                project_payload[key] = value
    if project_payload:
        merged["project"] = project_payload
    system_atelier = system_payload.get("atelier", {}) if system_payload else {}
    user_atelier = user_payload.get("atelier", {}) if user_payload else {}
    merged_atelier = dict(system_atelier)
    if "upgrade" in user_atelier:
        merged_atelier["upgrade"] = user_atelier.get("upgrade")
    merged["atelier"] = merged_atelier
    for key, value in user_payload.items():
        if key not in merged:
            merged[key] = value
    return parse_project_config(merged)


def split_project_config(
    config_payload: ProjectConfig,
) -> tuple[ProjectSystemConfig, ProjectUserConfig]:
    """Split a project config into system and user configs."""
    payload = config_payload.model_dump()
    system_payload, user_payload = _split_project_payload(payload)
    system_config = parse_project_system_config(system_payload)
    user_config = parse_project_user_config(user_payload)
    return system_config, user_config


def write_project_system_config(path: Path, payload: ProjectSystemConfig) -> None:
    """Write a project system config to disk."""
    write_json(path, payload)


def write_project_user_config(path: Path, payload: ProjectUserConfig) -> None:
    """Write a project user config to disk."""
    write_json(path, payload)


def write_project_config(path: Path, payload: ProjectConfig) -> None:
    """Write a merged project config to system/user files."""
    project_dir = path.parent
    system_config, user_config = split_project_config(payload)
    write_project_system_config(
        paths.project_config_sys_path(project_dir), system_config
    )
    write_project_user_config(paths.project_config_user_path(project_dir), user_config)


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
        path: Path to ``config.sys.json`` in the project directory.

    Returns:
        Parsed ``ProjectConfig`` or ``None`` when missing/empty.

    Example:
        >>> from pathlib import Path
        >>> load_project_config(Path("missing.json")) is None
        True
    """
    project_dir = path.parent
    system_path = paths.project_config_sys_path(project_dir)
    user_path = paths.project_config_user_path(project_dir)
    system_config = load_project_system_config(system_path)
    if not system_config:
        return None
    user_config = load_project_user_config(user_path)
    merged = merge_project_configs(system_config, user_config)
    ensure_agent_available(merged.agent.default, label="project")
    return merged


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


def normalize_pr_strategy(value: object, source: str) -> str:
    """Normalize a PR strategy string or fail with a helpful error."""
    try:
        return pr_strategy.normalize_pr_strategy(value)
    except ValueError:
        die(f"{source} must be one of: " + ", ".join(pr_strategy.PR_STRATEGY_VALUES))


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


def resolve_git_path(
    config_payload: ProjectConfig | ProjectUserConfig | dict | None = None,
) -> str:
    """Resolve the git executable path from config payloads."""
    if config_payload is None:
        return "git"
    if isinstance(config_payload, (ProjectConfig, ProjectUserConfig)):
        path = config_payload.git.path
        return path or "git"
    if isinstance(config_payload, dict):
        git_payload = config_payload.get("git")
        if isinstance(git_payload, dict):
            value = git_payload.get("path")
            if isinstance(value, str):
                value = value.strip()
            return value or "git"
    return "git"


def resolve_project_data_dir(project_root: Path, project_config: ProjectConfig) -> Path:
    """Resolve the data directory for a project."""
    data_dir = project_config.atelier.data_dir
    if data_dir:
        return Path(data_dir)
    return project_root


def detect_beads_location(repo_root: Path) -> str:
    """Return the Atelier Beads location.

    Atelier planning always uses the project-scoped Beads store. Repository
    Beads stores are treated as external sources.
    """
    _ = repo_root
    return "project"


def resolve_beads_root(project_dir: Path, repo_root: Path) -> Path:
    """Resolve the Beads root directory for Atelier planning."""
    _ = repo_root
    return paths.project_beads_dir(project_dir)


def is_github_provider(value: str | None) -> bool:
    """Return whether the provider string identifies GitHub."""
    if not value:
        return False
    return value.strip().lower() == "github"


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
        ("branch", "squash_message"),
        ("branch", "pr_strategy"),
        ("agent", "default"),
        ("editor", "edit"),
        ("editor", "work"),
    ]
    for path in fields:
        if not _path_has_value(payload, *path):
            missing.append(".".join(path))
    return missing


def user_config_payload(config: ProjectConfig | ProjectUserConfig) -> dict:
    """Return user-editable config sections as a dict."""
    if isinstance(config, ProjectUserConfig):
        project = config.project
        git_config = config.git
        branch = config.branch
        agent = config.agent
        editor_config = config.editor
        upgrade = config.atelier.upgrade
    else:
        project = config.project
        git_config = config.git
        branch = config.branch
        agent = config.agent
        editor_config = config.editor
        upgrade = config.atelier.upgrade
    project_payload = {
        key: value
        for key in ("provider", "provider_url", "owner")
        if (value := getattr(project, key, None)) is not None
    }
    payload = {
        "branch": branch.model_dump(),
        "git": git_config.model_dump(),
        "agent": agent.model_dump(),
        "editor": editor_config.model_dump(),
    }
    if project_payload:
        payload["project"] = project_payload
    if upgrade is not None:
        payload["atelier"] = {"upgrade": upgrade}
    return payload


def ensure_agent_available(
    agent_name: str,
    *,
    available: tuple[str, ...] | None = None,
    label: str | None = None,
) -> tuple[str, ...]:
    """Ensure at least one agent CLI is available and the configured agent exists."""
    resolved = available or agents.available_agent_names()
    if not resolved:
        die(
            "no supported agent CLIs found on PATH; "
            "install at least one agent to use Atelier"
        )
    if agent_name not in resolved:
        prefix = f"{label} " if label else ""
        die(f"{prefix}configured agent {agent_name!r} is not available on PATH")
    return resolved


_WAIT_FLAGS = {"-w", "--wait", "--blocking", "--block"}


def _strip_wait_flags(command: list[str]) -> list[str]:
    return [part for part in command if part not in _WAIT_FLAGS]


def _legacy_editor_command(default: object, options: object) -> list[str]:
    command = command_util.normalize_command(default) or []
    option_key: str | None = command[0].strip() if command else None

    extra: list[str] = []
    if isinstance(options, dict) and option_key:
        candidate_keys = [option_key, option_key.lower()]
        for key in candidate_keys:
            if key in options and isinstance(options[key], list):
                extra = [str(item) for item in options[key]]
                break
    return command + extra


def migrate_legacy_editor_payload(payload: dict) -> tuple[dict, bool]:
    """Convert legacy editor config (default/options) into edit/work commands."""
    if not isinstance(payload, dict):
        return payload, False
    editor_payload = payload.get("editor")
    if not isinstance(editor_payload, dict):
        return payload, False
    legacy_keys = {"default", "options"}
    if not (legacy_keys & set(editor_payload.keys())):
        return payload, False

    updated = dict(payload)
    editor_updated = dict(editor_payload)
    default = editor_payload.get("default")
    options = editor_payload.get("options")
    editor_updated.pop("default", None)
    editor_updated.pop("options", None)

    if "edit" not in editor_updated or "work" not in editor_updated:
        command = _legacy_editor_command(default, options)
        if command:
            if "edit" not in editor_updated:
                editor_updated["edit"] = command
            if "work" not in editor_updated:
                stripped = _strip_wait_flags(command)
                editor_updated["work"] = stripped or command

    updated["editor"] = editor_updated
    return updated, True


def _default_edit_command(
    config_payload: ProjectConfig | ProjectUserConfig,
) -> list[str]:
    if config_payload.editor.edit:
        return list(config_payload.editor.edit)
    if shutil.which("cursor"):
        return ["cursor", "-w"]
    if shutil.which("code"):
        return ["code", "-w"]
    default = system_editor_default()
    parts = command_util.normalize_command(default) or []
    return parts or ["vi"]


def _default_work_command(
    config_payload: ProjectConfig | ProjectUserConfig, edit_command: list[str]
) -> list[str]:
    if config_payload.editor.work:
        return list(config_payload.editor.work)
    if shutil.which("cursor"):
        return ["cursor"]
    if shutil.which("code"):
        return ["code"]
    if edit_command:
        stripped = _strip_wait_flags(edit_command)
        return stripped or edit_command
    default = system_editor_default()
    parts = command_util.normalize_command(default) or []
    return parts or ["vi"]


def default_user_config() -> ProjectUserConfig:
    """Return default user-editable config values."""
    base = ProjectUserConfig()
    editor_edit_default = _default_edit_command(base)
    editor_work_default = _default_work_command(base, editor_edit_default)
    agent_options = {agents.DEFAULT_AGENT: []}
    return base.model_copy(
        update={
            "git": base.git,
            "branch": base.branch,
            "agent": AgentConfig(default=agents.DEFAULT_AGENT, options=agent_options),
            "editor": EditorConfig(
                edit=editor_edit_default,
                work=editor_work_default,
            ),
            "atelier": AtelierUserSection(upgrade="ask"),
        }
    )


def load_installed_defaults(path: Path | None = None) -> ProjectConfig:
    """Load installed defaults for user-editable config values."""
    _migrate_legacy_installed_config()
    defaults_path = path or paths.installed_config_path()
    payload = load_json(defaults_path)
    default_config = default_user_config()
    if not payload:
        return merge_project_configs(ProjectSystemConfig(), default_config)
    parsed = parse_project_user_config(payload, defaults_path)
    branch = parsed.branch
    if not _path_has_value(payload, "branch", "prefix"):
        branch = branch.model_copy(update={"prefix": default_config.branch.prefix})
    if not _path_has_value(payload, "branch", "pr"):
        branch = branch.model_copy(update={"pr": default_config.branch.pr})
    if not _path_has_value(payload, "branch", "history"):
        branch = branch.model_copy(update={"history": default_config.branch.history})
    if not _path_has_value(payload, "branch", "squash_message"):
        branch = branch.model_copy(
            update={"squash_message": default_config.branch.squash_message}
        )
    if not _path_has_value(payload, "branch", "pr_strategy"):
        branch = branch.model_copy(
            update={"pr_strategy": default_config.branch.pr_strategy}
        )

    agent = parsed.agent
    if not _path_has_value(payload, "agent", "default"):
        agent = agent.model_copy(update={"default": default_config.agent.default})
    agent_options = dict(agent.options)
    if agent.default:
        agent_options.setdefault(agent.default, [])
    agent = agent.model_copy(update={"options": agent_options})

    editor_config = parsed.editor
    if not _path_has_value(payload, "editor", "edit"):
        editor_config = editor_config.model_copy(
            update={"edit": default_config.editor.edit}
        )
    if not _path_has_value(payload, "editor", "work"):
        editor_config = editor_config.model_copy(
            update={"work": default_config.editor.work}
        )

    git_config = parsed.git
    if not _path_has_value(payload, "git", "path"):
        git_config = git_config.model_copy(update={"path": default_config.git.path})

    atelier_section = parsed.atelier
    if not _path_has_value(payload, "atelier", "upgrade"):
        atelier_section = atelier_section.model_copy(
            update={"upgrade": default_config.atelier.upgrade}
        )

    parsed = parsed.model_copy(
        update={
            "branch": branch,
            "agent": agent,
            "editor": editor_config,
            "git": git_config,
            "atelier": atelier_section,
        }
    )
    merged = merge_project_configs(ProjectSystemConfig(), parsed)
    ensure_agent_available(merged.agent.default, label="installed defaults")
    return merged


def write_installed_defaults(
    config_payload: ProjectConfig | ProjectUserConfig, path: Path | None = None
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
    branch_squash_message_default = branch_config.squash_message

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

    branch_squash_message_arg = read_arg(args, "branch_squash_message")
    if branch_squash_message_arg is not None:
        try:
            branch_squash_message = BranchConfig.model_validate(
                {"squash_message": branch_squash_message_arg}
            ).squash_message
        except ValidationError:
            die(
                "branch.squash_message must be one of: "
                + ", ".join(BRANCH_SQUASH_MESSAGE_VALUES)
            )
    else:
        branch_squash_message = branch_squash_message_default

    branch_pr_strategy_default = branch_config.pr_strategy
    branch_pr_strategy_arg = read_arg(args, "branch_pr_strategy")
    if branch_pr_strategy_arg is not None:
        branch_pr_strategy = normalize_pr_strategy(
            branch_pr_strategy_arg, "--branch-pr-strategy"
        )
    elif should_prompt("branch", "pr_strategy"):
        branch_pr_strategy_input = select(
            "PR strategy",
            pr_strategy.PR_STRATEGY_VALUES,
            branch_pr_strategy_default,
        )
        branch_pr_strategy = normalize_pr_strategy(
            branch_pr_strategy_input, "branch.pr_strategy"
        )
    else:
        branch_pr_strategy = branch_pr_strategy_default

    available_agents = agents.available_agent_names()
    if not available_agents:
        die(
            "no supported agent CLIs found on PATH; "
            "install at least one agent to use Atelier"
        )
    agent_default_default = existing_config.agent.default or agents.DEFAULT_AGENT
    if not agents.is_supported_agent(agent_default_default):
        agent_default_default = agents.DEFAULT_AGENT
    agent_arg = read_arg(args, "agent")
    if agent_arg is not None:
        agent_default = agents.normalize_agent_name(str(agent_arg))
    elif should_prompt("agent", "default"):
        unique_agent = agents.unique_available_agent(available_agents)
        if unique_agent is not None:
            agent_default = unique_agent
        else:
            default_choice = (
                agent_default_default
                if agent_default_default in available_agents
                else available_agents[0]
            )
            agent_default = select("Agent", available_agents, default_choice)
    else:
        agent_default = agents.normalize_agent_name(agent_default_default)
    if not agents.is_supported_agent(agent_default):
        die(f"unsupported agent {agent_default!r}")
    ensure_agent_available(agent_default, available=available_agents)

    editor_edit_default = _default_edit_command(existing_config)
    editor_work_default = _default_work_command(existing_config, editor_edit_default)
    editor_edit_prompt_default = shlex.join(editor_edit_default)
    editor_work_prompt_default = shlex.join(editor_work_default)

    editor_edit_arg = read_arg(args, "editor_edit")
    legacy_editor_arg = None
    if editor_edit_arg is None:
        legacy_editor_arg = read_arg(args, "editor")
    if editor_edit_arg is not None:
        editor_edit_input = str(editor_edit_arg)
    elif legacy_editor_arg is not None:
        editor_edit_input = str(legacy_editor_arg)
    elif should_prompt("editor", "edit"):
        editor_edit_input = prompt(
            "Editor command (edit)",
            editor_edit_prompt_default,
            required=not allow_editor_empty,
            allow_empty=allow_editor_empty,
        )
    else:
        editor_edit_input = None

    editor_work_arg = read_arg(args, "editor_work")
    if editor_work_arg is not None:
        editor_work_input = str(editor_work_arg)
    elif should_prompt("editor", "work"):
        editor_work_input = prompt(
            "Editor command (work)",
            editor_work_prompt_default,
            required=not allow_editor_empty,
            allow_empty=allow_editor_empty,
        )
    else:
        editor_work_input = None

    editor_edit = existing_config.editor.edit
    if editor_edit_input is not None:
        editor_parts = command_util.normalize_command(editor_edit_input)
        editor_edit = editor_parts or None

    editor_work = existing_config.editor.work
    if editor_work_input is not None:
        editor_parts = command_util.normalize_command(editor_work_input)
        editor_work = editor_parts or None

    atelier_created_at = existing_config.atelier.created_at or utc_now()
    atelier_version = existing_config.atelier.version or __version__
    atelier_upgrade = resolve_upgrade_policy(existing_config.atelier.upgrade)
    atelier_managed_files = dict(existing_config.atelier.managed_files)
    atelier_data_dir = existing_config.atelier.data_dir
    if not atelier_data_dir:
        atelier_data_dir = str(
            paths.project_dir_for_enlistment(enlistment_path, origin)
        )

    agent_options = dict(existing_config.agent.options)
    agent_options.setdefault(agent_default, [])

    project_origin = origin or existing_config.project.origin
    project_repo_url = origin_raw or existing_config.project.repo_url
    project_allow_mainline = existing_config.project.allow_mainline_workspace
    project_provider = existing_config.project.provider
    project_provider_url = existing_config.project.provider_url
    project_owner = existing_config.project.owner

    beads_location = "project"
    beads_section = existing_config.beads.model_copy(
        update={"location": beads_location}
    )

    return ProjectConfig(
        project=ProjectSection(
            enlistment=enlistment_path,
            origin=project_origin,
            repo_url=project_repo_url,
            allow_mainline_workspace=project_allow_mainline,
            provider=project_provider,
            provider_url=project_provider_url,
            owner=project_owner,
        ),
        git=existing_config.git,
        branch=BranchConfig(
            prefix=branch_prefix,
            pr=branch_pr,
            history=branch_history,
            squash_message=branch_squash_message,
            pr_strategy=branch_pr_strategy,
        ),
        agent=AgentConfig(default=agent_default, options=agent_options),
        editor=EditorConfig(edit=editor_edit, work=editor_work),
        beads=beads_section,
        atelier=AtelierSection(
            version=atelier_version,
            created_at=atelier_created_at,
            data_dir=atelier_data_dir,
            upgrade=atelier_upgrade,
            managed_files=atelier_managed_files,
        ),
    )

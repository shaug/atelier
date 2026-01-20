"""Configuration helpers for Atelier projects and workspaces.

This module reads and writes ``config.json`` files, validates them with
Pydantic models, and normalizes CLI overrides.

Example:
    >>> from atelier.config import utc_now
    >>> utc_now().endswith("Z")
    True
"""

import datetime as dt
import json
import shlex
import shutil
from pathlib import Path

from pydantic import BaseModel, ValidationError

from . import __version__
from .editor import system_editor_default
from .io import die, prompt
from .models import (
    BRANCH_HISTORY_VALUES,
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
    normalized = value.strip()
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


def build_project_config(
    existing: ProjectConfig | dict,
    enlistment_path: str,
    origin: str | None,
    origin_raw: str | None,
    args: object | None,
) -> ProjectConfig:
    """Build a new project config, prompting when necessary.

    Args:
        existing: Existing config payload or ``ProjectConfig``.
        enlistment_path: Resolved local enlistment path.
        origin: Normalized repo origin (e.g., ``github.com/org/repo``) or ``None``.
        origin_raw: Raw origin URL from Git or ``None``.
        args: CLI argument object for overrides, or ``None`` to prompt.

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
    branch_config = existing_config.branch
    branch_prefix_default = branch_config.prefix or ""
    branch_prefix_arg = read_arg(args, "branch_prefix")
    if branch_prefix_arg is not None:
        branch_prefix = str(branch_prefix_arg)
    else:
        branch_prefix = prompt("Branch prefix (optional)", branch_prefix_default)

    branch_pr_default = branch_config.pr
    branch_history_default = branch_config.history

    branch_pr_arg = read_arg(args, "branch_pr")
    if branch_pr_arg is not None:
        branch_pr = parse_branch_pr_override(branch_pr_arg)
    else:
        branch_pr_prompt_default = "true" if branch_pr_default else "false"
        branch_pr_input = prompt(
            "Expect pull requests for workspace branches (true/false)",
            branch_pr_prompt_default,
            required=True,
        )
        branch_pr = parse_branch_pr_override(branch_pr_input)

    branch_history_arg = read_arg(args, "branch_history")
    if branch_history_arg is not None:
        branch_history = normalize_branch_history(
            branch_history_arg, "--branch-history"
        )
    else:
        branch_history_input = prompt(
            "Branch history policy (manual|squash|merge|rebase)",
            branch_history_default,
            required=True,
        )
        branch_history = normalize_branch_history(
            branch_history_input, "branch.history"
        )

    agent_default_default = existing_config.agent.default or "codex"
    agent_arg = read_arg(args, "agent")
    if agent_arg is not None:
        agent_default = str(agent_arg)
    else:
        agent_default = prompt("Agent (codex)", agent_default_default, required=True)
    if agent_default != "codex":
        die("only 'codex' is supported as the agent in v2")

    editor_prompt_default = None
    editor_default_default = existing_config.editor.default
    if editor_default_default:
        editor_options_default = existing_config.editor.options.get(
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

    editor_arg = read_arg(args, "editor")
    if editor_arg is not None:
        editor_input = str(editor_arg)
    else:
        editor_input = prompt("Editor command", editor_prompt_default, required=True)
    editor_parts = shlex.split(editor_input)
    editor_default = editor_parts[0]
    editor_input_options = editor_parts[1:]

    atelier_created_at = existing_config.atelier.created_at or utc_now()
    atelier_version = existing_config.atelier.version or __version__

    agent_options = dict(existing_config.agent.options)
    agent_options.setdefault("codex", [])

    editor_options = dict(existing_config.editor.options)
    if editor_input_options:
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
        atelier=AtelierSection(version=atelier_version, created_at=atelier_created_at),
    )

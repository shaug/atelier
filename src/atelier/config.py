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
    now = dt.datetime.now(tz=dt.timezone.utc).replace(microsecond=0)
    return now.isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path: Path, payload: dict | BaseModel) -> None:
    if isinstance(payload, BaseModel):
        payload = payload.model_dump()
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
        fh.write("\n")


def parse_project_config(
    payload: dict, source: Path | str | None = None
) -> ProjectConfig:
    try:
        return ProjectConfig.model_validate(payload)
    except ValidationError as exc:
        location = f" at {source}" if source else ""
        die(f"invalid project config{location}:\n{exc}")


def load_project_config(path: Path) -> ProjectConfig | None:
    payload = load_json(path)
    if not payload:
        return None
    return parse_project_config(payload, path)


def parse_workspace_config(
    payload: dict, source: Path | str | None = None
) -> WorkspaceConfig:
    try:
        return WorkspaceConfig.model_validate(payload)
    except ValidationError as exc:
        location = f" at {source}" if source else ""
        die(f"invalid workspace config{location}:\n{exc}")


def load_workspace_config(path: Path) -> WorkspaceConfig | None:
    payload = load_json(path)
    if not payload:
        return None
    return parse_workspace_config(payload, path)


def resolve_branch_config(config: ProjectConfig | dict) -> BranchConfig:
    if isinstance(config, ProjectConfig):
        return config.branch
    branch = config.get("branch") if isinstance(config, dict) else None
    try:
        return BranchConfig.model_validate(branch or {})
    except ValidationError as exc:
        die(f"invalid branch config:\n{exc}")


def resolve_branch_pr(branch_config: BranchConfig) -> bool:
    return branch_config.pr


def normalize_branch_history(value: object, source: str) -> str:
    if not isinstance(value, str):
        die(f"{source} must be one of: " + ", ".join(BRANCH_HISTORY_VALUES))
    normalized = value.strip()
    if normalized not in BRANCH_HISTORY_VALUES:
        die(f"{source} must be one of: " + ", ".join(BRANCH_HISTORY_VALUES))
    return normalized


def resolve_branch_history(branch_config: BranchConfig) -> str:
    return branch_config.history


def parse_branch_pr_override(value: object) -> bool:
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
    config_path = workspace_config_path(workspace_dir)
    workspace_config = load_workspace_config(config_path)
    if not workspace_config:
        return None, None
    return (
        workspace_config.workspace.branch_pr,
        workspace_config.workspace.branch_history,
    )


def read_arg(args: object | None, name: str) -> object | None:
    if args is None:
        return None
    return getattr(args, name, None)


def build_project_config(
    existing: ProjectConfig | dict,
    origin: str,
    origin_raw: str,
    args: object | None,
) -> ProjectConfig:
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

    return ProjectConfig(
        project=ProjectSection(origin=origin, repo_url=origin_raw),
        branch=BranchConfig(prefix=branch_prefix, pr=branch_pr, history=branch_history),
        agent=AgentConfig(default=agent_default, options=agent_options),
        editor=EditorConfig(default=editor_default, options=editor_options),
        atelier=AtelierSection(version=atelier_version, created_at=atelier_created_at),
    )

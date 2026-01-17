import datetime as dt
import json
import shlex
import shutil
from pathlib import Path

from . import __version__
from .editor import system_editor_default
from .io import die, prompt
from .paths import workspace_config_path

BRANCH_HISTORY_VALUES = ("manual", "squash", "merge", "rebase")


def utc_now() -> str:
    now = dt.datetime.now(tz=dt.timezone.utc).replace(microsecond=0)
    return now.isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path: Path, payload: dict) -> None:
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
        fh.write("\n")


def resolve_branch_config(config: dict) -> dict:
    branch = config.get("branch")
    if isinstance(branch, dict):
        return branch
    return {}


def resolve_branch_pr(branch_config: dict) -> bool:
    if "pr" not in branch_config:
        return True
    value = branch_config.get("pr")
    if isinstance(value, bool):
        return value
    die("branch.pr must be a boolean")


def normalize_branch_history(value: object, source: str) -> str:
    if not isinstance(value, str):
        die(f"{source} must be one of: " + ", ".join(BRANCH_HISTORY_VALUES))
    normalized = value.strip()
    if normalized not in BRANCH_HISTORY_VALUES:
        die(f"{source} must be one of: " + ", ".join(BRANCH_HISTORY_VALUES))
    return normalized


def resolve_branch_history(branch_config: dict) -> str:
    if "history" not in branch_config:
        return "manual"
    value = branch_config.get("history")
    return normalize_branch_history(value, "branch.history")


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
    workspace_config = load_json(workspace_config_path(workspace_dir)) or {}
    workspace_section = workspace_config.get("workspace", {})
    branch_pr = workspace_section.get("branch_pr")
    branch_history = workspace_section.get("branch_history")
    return branch_pr, branch_history


def read_arg(args: object | None, name: str) -> object | None:
    if args is None:
        return None
    return getattr(args, name, None)


def build_project_config(
    existing: dict,
    origin: str,
    origin_raw: str,
    args: object | None,
) -> dict:
    branch_config = resolve_branch_config(existing)
    branch_prefix_default = branch_config.get("prefix")
    if branch_prefix_default is None:
        branch_prefix_default = ""
    branch_prefix_arg = read_arg(args, "branch_prefix")
    if branch_prefix_arg is not None:
        branch_prefix = str(branch_prefix_arg)
    else:
        branch_prefix = prompt("Branch prefix (optional)", branch_prefix_default)

    branch_pr_default = resolve_branch_pr(branch_config)
    branch_history_default = resolve_branch_history(branch_config)

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

    agent_default_default = (
        existing.get("agent", {}).get("default")
        if isinstance(existing.get("agent"), dict)
        else None
    )
    if not agent_default_default:
        agent_default_default = "codex"
    agent_arg = read_arg(args, "agent")
    if agent_arg is not None:
        agent_default = str(agent_arg)
    else:
        agent_default = prompt("Agent (codex)", agent_default_default, required=True)
    if agent_default != "codex":
        die("only 'codex' is supported as the agent in v2")

    editor_prompt_default = None
    if isinstance(existing.get("editor"), dict):
        editor_default_default = existing.get("editor", {}).get("default")
        if editor_default_default:
            editor_options_default = (
                existing.get("editor", {})
                .get("options", {})
                .get(editor_default_default, [])
            )
            if isinstance(editor_options_default, list) and editor_options_default:
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

    atelier_section = (
        existing.get("atelier") if isinstance(existing.get("atelier"), dict) else {}
    )
    atelier_created_at = atelier_section.get("created_at") or utc_now()
    atelier_version = atelier_section.get("version") or __version__

    agent_options = {}
    if isinstance(existing.get("agent"), dict):
        existing_options = existing.get("agent", {}).get("options")
        if isinstance(existing_options, dict):
            agent_options = existing_options
    if "codex" not in agent_options:
        agent_options["codex"] = []

    editor_options = {}
    if isinstance(existing.get("editor"), dict):
        existing_editor_options = existing.get("editor", {}).get("options")
        if isinstance(existing_editor_options, dict):
            editor_options = existing_editor_options
    if editor_input_options:
        editor_options = {**editor_options, editor_default: editor_input_options}

    return {
        "project": {
            "origin": origin,
            "repo_url": origin_raw,
        },
        "branch": {
            "prefix": branch_prefix,
            "pr": branch_pr,
            "history": branch_history,
        },
        "agent": {
            "default": agent_default,
            "options": agent_options,
        },
        "editor": {
            "default": editor_default,
            "options": editor_options,
        },
        "atelier": {
            "version": atelier_version,
            "created_at": atelier_created_at,
        },
    }

import argparse
import concurrent.futures
import datetime as dt
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

from platformdirs import user_data_dir

from . import __version__

BRANCH_HISTORY_VALUES = ("manual", "squash", "merge", "rebase")
ATELIER_APP_NAME = "atelier"
PROJECTS_DIRNAME = "projects"
WORKSPACES_DIRNAME = "workspaces"
TEMPLATES_DIRNAME = "templates"
PROJECT_CONFIG_FILENAME = "config.json"
WORKSPACE_CONFIG_FILENAME = "config.json"

PROJECT_AGENTS_TEMPLATE = """# Atelier Project Overlay

This project is managed using **Atelier**, a workspace-based workflow for
agent-assisted development.

## How Work Is Organized

- Development work is performed in isolated **workspaces**
- Workspaces live under the Atelier project directory managed in the local data dir
- Each workspace represents **one unit of work**
- Each workspace has its own `AGENTS.md` defining intent and scope

## Authority

- This file describes only the **Atelier workflow overlay**
- Workspace `AGENTS.md` files define execution expectations
- Repository-specific coding conventions are defined elsewhere
  (e.g. a repository-level `AGENTS.md`, if present)

## Additional Policy Context

If a `PROJECT.md` file exists at the project root (the Atelier project
directory), read it and apply the rules defined there in addition to this file.

If a `WORKSPACE.md` file exists in a workspace, read it and apply the rules
defined there as well.

In case of conflict:
- `WORKSPACE.md` rules take precedence over `PROJECT.md`
- `PROJECT.md` rules take precedence over this file

- Atelier project metadata lives in the local data directory (not in the repo).
"""

WORKSPACE_AGENTS_TEMPLATE = """<!-- atelier:{workspace_id} -->

# Atelier Workspace

This directory is an **Atelier workspace**.

## Workspace Model

- This workspace represents **one unit of work**
- All code changes for this work should be made under `repo/`
- The code in `repo/` is a real git repository and should be treated normally
- This workspace maps to **one git branch**
- Integration expectations are defined below

## Execution Expectations

- Complete the work described in this file **to completion**
- Do not expand scope beyond what is written here
- Prefer small, reviewable changes over large refactors
- Avoid unrelated cleanup unless explicitly required

## Agent Context

When operating in this workspace:

- Treat this workspace as the **entire world**
- Do not reference or modify other workspaces
- Read the remainder of this file carefully before beginning work

## Additional Policy Context

If a `PROJECT.md` file exists at the project root (the Atelier project
directory), read it and apply the rules defined there in addition to this file.

If a `WORKSPACE.md` file exists in this workspace, read it and apply the rules
defined there as well.

In case of conflict:
- `WORKSPACE.md` rules take precedence over `PROJECT.md`
- `PROJECT.md` rules take precedence over this file

{integration_strategy}

After reading this file, proceed with the work described below.

---

## Goal

<!-- Describe what this workspace is meant to accomplish. -->

## Context

<!-- Relevant background, links, tickets, or prior discussion. -->

## Constraints / Considerations

<!-- Technical, organizational, or temporal constraints. -->

## What "Done" Looks Like

<!-- Describe how to know when this workspace is complete. -->

## Notes

<!-- Optional execution notes or reminders. -->
"""

PROJECT_MD_TEMPLATE = """<!--
PROJECT.md

Use this file to define project-level agent policies for this Atelier project.
It is optional and fully user-owned.

If a WORKSPACE.md file exists inside a workspace, its rules take precedence.
This PROJECT.md file takes precedence over project-level AGENTS.md.

Atelier does not parse or modify this file.
-->
"""

WORKSPACE_MD_TEMPLATE = """<!--
WORKSPACE.md

Use this file to define workspace-specific agent policies.
It is optional and fully user-owned.

WORKSPACE.md overrides PROJECT.md and AGENTS.md when rules conflict.

Atelier does not parse or modify this file.
-->
"""


def say(message: str) -> None:
    print(message)


def warn(message: str) -> None:
    print(f"warning: {message}", file=sys.stderr)


def die(message: str, code: int = 1) -> None:
    print(f"error: {message}", file=sys.stderr)
    sys.exit(code)


def prompt(text: str, default: str | None = None, required: bool = False) -> str:
    while True:
        if default is not None and default != "":
            value = input(f"{text} [{default}]: ").strip()
            if value == "":
                value = default
        else:
            value = input(f"{text}: ").strip()
        if required and value == "":
            continue
        return value


def system_editor_default() -> str:
    env_editor = os.environ.get("EDITOR", "").strip()
    if env_editor:
        return env_editor
    return "vi"


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


def atelier_data_dir() -> Path:
    return Path(user_data_dir(ATELIER_APP_NAME))


def projects_root() -> Path:
    return atelier_data_dir() / PROJECTS_DIRNAME


def project_key(origin: str) -> str:
    return hashlib.sha256(origin.encode("utf-8")).hexdigest()


def workspace_key(branch: str) -> str:
    return hashlib.sha256(branch.encode("utf-8")).hexdigest()


def project_dir_for_origin(origin: str) -> Path:
    return projects_root() / project_key(origin)


def project_config_path(project_dir: Path) -> Path:
    return project_dir / PROJECT_CONFIG_FILENAME


def workspaces_root_for_project(project_dir: Path) -> Path:
    return project_dir / WORKSPACES_DIRNAME


def workspace_dir_for_branch(project_dir: Path, branch: str) -> Path:
    return workspaces_root_for_project(project_dir) / workspace_key(branch)


def workspace_config_path(workspace_dir: Path) -> Path:
    return workspace_dir / WORKSPACE_CONFIG_FILENAME


def strip_git_suffix(path: str) -> str:
    normalized = path.strip().rstrip("/")
    if normalized.lower().endswith(".git"):
        return normalized[: -len(".git")]
    return normalized


def normalize_origin_url(value: str) -> str:
    raw = value.strip()
    if not raw:
        return ""

    scp_match = re.match(r"^(?P<user>[^@]+)@(?P<host>[^:]+):(?P<path>.+)$", raw)
    if scp_match:
        host = scp_match.group("host").lower()
        path = strip_git_suffix(scp_match.group("path").lstrip("/"))
        return f"{host}/{path}"

    if "://" in raw:
        parsed = urlparse(raw)
        scheme = (parsed.scheme or "").lower()
        host = (parsed.hostname or "").lower()
        path = strip_git_suffix((parsed.path or "").lstrip("/"))
        if scheme in {"http", "https", "ssh", "git"} and host:
            return f"{host}/{path}"
        if scheme == "file":
            local_path = Path(parsed.path).expanduser().resolve()
            return local_path.as_posix()

    if "/" in raw and " " not in raw:
        head, tail = raw.split("/", 1)
        if "." in head:
            host = head.lower()
            path = strip_git_suffix(tail)
            return f"{host}/{path}"

    local_path = Path(raw).expanduser()
    if not local_path.is_absolute():
        local_path = local_path.resolve()
    return local_path.as_posix()


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def git_repo_root(start: Path) -> Path | None:
    result = run_git_command(["git", "-C", str(start), "rev-parse", "--show-toplevel"])
    if result.returncode != 0:
        return None
    resolved = result.stdout.strip()
    if not resolved:
        return None
    return Path(resolved)


def git_origin_url(repo_dir: Path) -> str | None:
    result = run_git_command(
        ["git", "-C", str(repo_dir), "remote", "get-url", "origin"]
    )
    if result.returncode != 0:
        return None
    origin = result.stdout.strip()
    return origin or None


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


def resolve_branch_history(branch_config: dict) -> str:
    if "history" not in branch_config:
        return "manual"
    value = branch_config.get("history")
    return normalize_branch_history(value, "branch.history")


def normalize_branch_history(value: object, source: str) -> str:
    if not isinstance(value, str):
        die(f"{source} must be one of: " + ", ".join(BRANCH_HISTORY_VALUES))
    normalized = value.strip()
    if normalized not in BRANCH_HISTORY_VALUES:
        die(f"{source} must be one of: " + ", ".join(BRANCH_HISTORY_VALUES))
    return normalized


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
    args: argparse.Namespace,
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


def render_integration_strategy(branch_pr: bool, branch_history: str) -> str:
    pr_label = "yes" if branch_pr else "no"
    lines = [
        "## Integration Strategy",
        "",
        "This section describes expected coordination and history semantics.",
        "Atelier does not automate integration.",
        "",
        f"- Pull requests expected: {pr_label}",
        f"- History policy: {branch_history}",
        "",
        "When this workspace's success criteria are met:",
    ]
    if branch_pr:
        lines.extend(
            [
                "- The workspace branch is expected to be pushed to the remote.",
                "- A pull request against the default branch is the expected "
                "integration mechanism.",
                "- Manual review is assumed; integration should not happen "
                "automatically.",
            ]
        )
        if branch_history == "manual":
            lines.append(
                "- The intended merge style is manual (no specific history "
                "behavior is implied)."
            )
        else:
            lines.append(
                f"- The intended merge style is {branch_history}, but review "
                "and human control remain authoritative."
            )
        lines.append(
            "- Integration should wait for an explicit instruction in the thread."
        )
    else:
        lines.append(
            "- Integration is expected to happen directly without a pull request."
        )
        if branch_history == "manual":
            lines.append(
                "- No specific history behavior is implied; use human judgment "
                "for how changes land on the default branch."
            )
        elif branch_history == "squash":
            lines.append(
                "- Workspace changes are expected to be collapsed into a single "
                "commit on the default branch."
            )
        elif branch_history == "merge":
            lines.append(
                "- Workspace changes are expected to be merged with a merge "
                "commit, preserving workspace history."
            )
        elif branch_history == "rebase":
            lines.append(
                "- Workspace commits are expected to be replayed linearly onto "
                "the default branch."
            )
        lines.append(
            "- After integration, the default branch is expected to be pushed."
        )
    return "\n".join(lines)


def ensure_workspace_metadata(
    workspace_dir: Path,
    agents_path: Path,
    workspace_config_path: Path,
    project_root: Path,
    project_origin: str,
    workspace_branch: str,
    branch_pr: bool,
    branch_history: str,
) -> None:
    workspace_config_exists = workspace_config_path.exists()
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
                "created_at": utc_now(),
            },
        }
        write_json(workspace_config_path, workspace_config)

    if agents_path.exists():
        return

    if workspace_config_exists:
        stored_pr, stored_history = read_workspace_branch_settings(workspace_dir)
        if stored_pr is None or not isinstance(stored_pr, bool):
            die("workspace missing branch.pr setting")
        if stored_history is None or not isinstance(stored_history, str):
            die("workspace missing branch.history setting")
        stored_history = normalize_branch_history(
            stored_history, "workspace branch.history"
        )
        integration_pr = stored_pr
        integration_history = stored_history
    else:
        integration_pr = branch_pr
        integration_history = branch_history

    integration_strategy = render_integration_strategy(
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
            WORKSPACE_AGENTS_TEMPLATE.format(
                workspace_id=workspace_id,
                integration_strategy=integration_strategy,
            ),
            encoding="utf-8",
        )


def read_first_user_message(path: Path) -> str | None:
    try:
        if path.suffix == ".jsonl":
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        return None
                    if isinstance(data, dict) and data.get("type") == "session_meta":
                        payload = data.get("payload")
                        if isinstance(payload, dict):
                            instructions = payload.get("instructions")
                            if instructions:
                                return str(instructions)
                    return extract_first_user_from_obj(data)
            return None
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    content = raw.lstrip()
    if content == "":
        return None
    if content[0] == "{":
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return extract_first_user_from_obj(data)
    if content[0] == "[":
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return extract_first_user_from_obj(data)
    # JSONL is handled above.
    return None


def read_session_id(path: Path) -> str | None:
    if path.suffix == ".jsonl":
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        return None
                    if isinstance(data, dict) and data.get("type") == "session_meta":
                        payload = data.get("payload")
                        if isinstance(payload, dict):
                            session_id = payload.get("id")
                            if session_id:
                                return str(session_id)
                    return None
        except OSError:
            return None
    return None


def extract_first_user_from_obj(data: object) -> str | None:
    if isinstance(data, dict):
        if "messages" in data and isinstance(data["messages"], list):
            return extract_first_user_from_list(data["messages"])
        if "history" in data and isinstance(data["history"], list):
            return extract_first_user_from_list(data["history"])
    if isinstance(data, list):
        return extract_first_user_from_list(data)
    return None


def extract_first_user_from_list(messages: list) -> str | None:
    for item in messages:
        if not isinstance(item, dict):
            continue
        role = item.get("role") or item.get("type")
        if role != "user":
            continue
        content = item.get("content") or item.get("text")
        if content is None:
            continue
        if isinstance(content, list):
            chunks: list[str] = []
            for part in content:
                if isinstance(part, dict):
                    text = part.get("text")
                    if text:
                        chunks.append(str(text))
                elif isinstance(part, str):
                    chunks.append(part)
            return "".join(chunks) if chunks else None
        return str(content)
    return None


def find_codex_session(project_origin: str, workspace_branch: str) -> str | None:
    sessions_root = Path.home() / ".codex" / "sessions"
    if not sessions_root.exists():
        return None
    target = workspace_identifier(project_origin, workspace_branch)
    matches: list[tuple[float, Path, str | None]] = []
    for path in sessions_root.rglob("*"):
        if path.suffix not in {".json", ".jsonl"}:
            continue
        message = read_first_user_message(path)
        if not message:
            continue
        if target not in message:
            continue
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        session_id = read_session_id(path)
        matches.append((mtime, path, session_id))
    if not matches:
        return None
    matches.sort(key=lambda item: item[0], reverse=True)
    _, path, session_id = matches[0]
    return session_id or path.stem


def run_command(cmd: list[str], cwd: Path | None = None) -> None:
    try:
        subprocess.run(cmd, cwd=cwd, check=True)
    except FileNotFoundError:
        die(f"missing required command: {cmd[0]}")
    except subprocess.CalledProcessError:
        die(f"command failed: {' '.join(cmd)}")


def run_git_command(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        die("missing required command: git")


def try_run_command(
    cmd: list[str], cwd: Path | None = None
) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return None


def read_arg(args: argparse.Namespace | None, name: str) -> object | None:
    if args is None:
        return None
    return getattr(args, name, None)


def build_project_config(
    existing: dict,
    origin: str,
    origin_raw: str,
    args: argparse.Namespace | None,
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


def ensure_project_dirs(project_dir: Path) -> None:
    ensure_dir(project_dir)
    ensure_dir(workspaces_root_for_project(project_dir))


def ensure_project_scaffold(project_dir: Path, create_workspace_template: bool) -> None:
    ensure_project_dirs(project_dir)

    agents_path = project_dir / "AGENTS.md"
    if not agents_path.exists():
        agents_path.write_text(PROJECT_AGENTS_TEMPLATE, encoding="utf-8")
        say("Created AGENTS.md")

    project_md_path = project_dir / "PROJECT.md"
    if not project_md_path.exists():
        project_md_path.write_text(PROJECT_MD_TEMPLATE, encoding="utf-8")
        say("Created PROJECT.md")

    if create_workspace_template:
        workspace_template_path = project_dir / TEMPLATES_DIRNAME / "WORKSPACE.md"
        if not workspace_template_path.exists():
            ensure_dir(workspace_template_path.parent)
            workspace_template_path.write_text(WORKSPACE_MD_TEMPLATE, encoding="utf-8")
            say("Created templates/WORKSPACE.md")


def resolve_repo_origin(start: Path) -> tuple[Path, str, str]:
    repo_root = git_repo_root(start)
    if not repo_root:
        die("command must be run inside a git repository")
    origin_raw = git_origin_url(repo_root)
    if not origin_raw:
        die("repo missing origin remote")
    origin = normalize_origin_url(origin_raw)
    if not origin:
        die("failed to normalize origin URL")
    return repo_root, origin_raw, origin


def init_project(args: argparse.Namespace) -> None:
    cwd = Path.cwd()
    repo_root = git_repo_root(cwd)
    if not repo_root:
        die("atelier init must be run inside a git repository")

    origin_raw = git_origin_url(repo_root)
    if not origin_raw:
        die("repo missing origin remote")
    origin = normalize_origin_url(origin_raw)
    if not origin:
        die("failed to normalize origin URL")

    project_dir = project_dir_for_origin(origin)
    config_path = project_config_path(project_dir)
    config = load_json(config_path) or {}
    payload = build_project_config(config, origin, origin_raw, args)
    ensure_project_dirs(project_dir)
    write_json(config_path, payload)
    ensure_project_scaffold(project_dir, bool(read_arg(args, "workspace_template")))

    say("Initialized Atelier project")


def open_workspace(args: argparse.Namespace) -> None:
    cwd = Path.cwd()
    repo_root = git_repo_root(cwd)
    if not repo_root:
        die("atelier open must be run inside a git repository")

    origin_raw = git_origin_url(repo_root)
    if not origin_raw:
        die("repo missing origin remote")
    origin = normalize_origin_url(origin_raw)
    if not origin:
        die("failed to normalize origin URL")

    project_dir = project_dir_for_origin(origin)
    config_path = project_config_path(project_dir)
    config = load_json(config_path) or {}
    if not config:
        config = build_project_config({}, origin, origin_raw, None)
        ensure_project_dirs(project_dir)
        write_json(config_path, config)
        ensure_project_scaffold(project_dir, False)
    else:
        ensure_project_dirs(project_dir)

    project_section = (
        config.get("project") if isinstance(config.get("project"), dict) else {}
    )
    project_origin = project_section.get("origin")
    if not project_origin:
        project_section["origin"] = origin
        project_section.setdefault("repo_url", origin_raw)
        config["project"] = project_section
        write_json(config_path, config)
        project_origin = origin
    if project_origin != origin:
        die("project origin does not match current repo origin")

    branch_config = resolve_branch_config(config)
    branch_pr = resolve_branch_pr(branch_config)
    branch_history = resolve_branch_history(branch_config)
    branch_pr_override, branch_history_override = resolve_branch_overrides(args)
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
        workspace_name_input = resolve_implicit_workspace_name(repo_root, config)
        raw_branch = True

    workspace_name_input = normalize_workspace_name(str(workspace_name_input))
    if not workspace_name_input:
        die("workspace branch is required")

    branch_prefix = branch_config.get("prefix", "")
    workspace_branch, workspace_dir, workspace_config_exists = resolve_workspace_target(
        project_dir,
        workspace_name_input,
        branch_prefix,
        raw_branch,
    )
    if not workspace_branch:
        die("workspace branch is required")

    agents_path = workspace_dir / "AGENTS.md"
    workspace_config_file = workspace_config_path(workspace_dir)
    is_new_workspace = not workspace_config_exists
    if workspace_config_exists:
        if branch_pr_override is not None or branch_history_override is not None:
            stored_pr, stored_history = read_workspace_branch_settings(workspace_dir)
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
                stored_history = normalize_branch_history(
                    stored_history, "workspace branch.history"
                )
                if stored_history != branch_history_override:
                    die(
                        "specified branch.history does not match workspace config "
                        f"({branch_history_override} != {stored_history})"
                    )
        stored_branch = workspace_branch_for_dir(workspace_dir)
        if stored_branch != workspace_branch:
            die("workspace branch does not match configured workspace branch")
    ensure_dir(workspace_dir)
    ensure_workspace_metadata(
        workspace_dir=workspace_dir,
        agents_path=agents_path,
        workspace_config_path=workspace_config_file,
        project_root=project_dir,
        project_origin=project_origin,
        workspace_branch=workspace_branch,
        branch_pr=effective_branch_pr,
        branch_history=effective_branch_history,
    )
    workspace_policy_template = project_dir / TEMPLATES_DIRNAME / "WORKSPACE.md"
    workspace_policy_path = workspace_dir / "WORKSPACE.md"
    if workspace_policy_template.exists() and not workspace_policy_path.exists():
        shutil.copyfile(workspace_policy_template, workspace_policy_path)

    repo_dir = workspace_dir / "repo"
    project_repo_url = origin_raw

    should_open_editor = False
    editor_cmd: list[str] | None = None
    if not repo_dir.exists():
        should_open_editor = True
        run_command(["git", "clone", project_repo_url, str(repo_dir)])
    else:
        if not git_is_repo(repo_dir):
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

    current_branch = git_current_branch(repo_dir)
    if current_branch is None:
        die("failed to determine repo branch")
    repo_clean = git_is_clean(repo_dir)
    if repo_clean is None:
        die("failed to determine repo status")

    default_branch = git_default_branch(repo_dir)
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
        run_command(["git", "-C", str(repo_dir), "checkout", default_branch])

    local_branch = git_ref_exists(repo_dir, f"refs/heads/{workspace_branch}")
    remote_branch = git_ref_exists(repo_dir, f"refs/remotes/origin/{workspace_branch}")
    if not remote_branch:
        remote_branch = git_has_remote_branch(repo_dir, workspace_branch) is True
        if remote_branch:
            run_command(
                ["git", "-C", str(repo_dir), "fetch", "origin", workspace_branch]
            )
    existing_branch = local_branch or remote_branch

    if skip_workspace_checkout:
        pass
    elif local_branch:
        run_command(["git", "-C", str(repo_dir), "checkout", workspace_branch])
    elif remote_branch:
        run_command(
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
        run_command(["git", "-C", str(repo_dir), "checkout", "-b", workspace_branch])

    agent_default = config.get("agent", {}).get("default", "codex")
    if agent_default != "codex":
        die("only 'codex' is supported as the agent in v2")

    agent_options = config.get("agent", {}).get("options", {}).get("codex", [])
    if not isinstance(agent_options, list):
        agent_options = []
    agent_options = [str(opt) for opt in agent_options]

    if is_new_workspace and existing_branch:
        append_workspace_branch_summary(
            agents_path, repo_dir, default_branch, workspace_branch
        )

    if should_open_editor:
        if editor_cmd is None:
            editor_cmd = resolve_editor_command(config)
        run_command([*editor_cmd, str(agents_path)], cwd=project_dir)

    session_id = find_codex_session(project_origin, workspace_branch)
    if session_id:
        say(f"Resuming Codex session {session_id}")
        run_command(
            ["codex", "--cd", str(workspace_dir), *agent_options, "resume", session_id]
        )
    else:
        opening_prompt = workspace_identifier(project_origin, workspace_branch)
        say("Starting new Codex session")
        run_command(
            ["codex", "--cd", str(workspace_dir), *agent_options, opening_prompt]
        )


def resolve_implicit_workspace_name(repo_root: Path, config: dict) -> str:
    default_branch = git_default_branch(repo_root)
    if not default_branch:
        die("failed to determine default branch from repo")

    current_branch = git_current_branch(repo_root)
    if not current_branch:
        die("failed to determine current branch")
    if current_branch == default_branch:
        die(
            "implicit open requires a non-default branch; "
            f"current branch is {default_branch!r}"
        )

    clean = git_is_clean(repo_root)
    if clean is not True:
        die("implicit open requires a clean working tree")

    fully_pushed = git_branch_fully_pushed(repo_root)
    if fully_pushed is None:
        die("implicit open requires the branch to be pushed to its upstream")
    if fully_pushed is False:
        die("implicit open requires the branch to be fully pushed to its upstream")

    return current_branch


def resolve_editor_command(config: dict) -> list[str]:
    editor_default = config.get("editor", {}).get("default")
    if editor_default:
        options = config.get("editor", {}).get("options", {}).get(editor_default, [])
        if not isinstance(options, list):
            options = []
        return [editor_default, *options]

    return shlex.split(system_editor_default())


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
    config = load_json(config_path)
    if not config:
        die("failed to load workspace config")
    stored_branch = require_workspace_branch(config_path, config)
    if stored_branch != branch:
        die("workspace branch does not match hashed directory")
    return workspace_dir, config


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
        config = load_json(config_path) or {}
        stored_branch = require_workspace_branch(config_path, config)
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
    workspace_config = load_json(config_path) or {}
    branch = require_workspace_branch(config_path, workspace_config)
    return branch


def git_current_branch(repo_dir: Path) -> str | None:
    result = run_git_command(
        ["git", "-C", str(repo_dir), "rev-parse", "--abbrev-ref", "HEAD"]
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def git_default_branch(repo_dir: Path) -> str | None:
    result = run_git_command(
        ["git", "-C", str(repo_dir), "symbolic-ref", "refs/remotes/origin/HEAD"]
    )
    if result.returncode == 0:
        ref = result.stdout.strip()
        prefix = "refs/remotes/origin/"
        if ref.startswith(prefix):
            branch = ref[len(prefix) :].strip()
            if branch:
                return branch

    result = run_git_command(["git", "-C", str(repo_dir), "remote", "show", "origin"])
    if result.returncode == 0:
        for line in result.stdout.splitlines():
            if "HEAD branch:" not in line:
                continue
            _, value = line.split(":", 1)
            branch = value.strip()
            if branch:
                return branch

    if git_ref_exists(repo_dir, "refs/heads/main"):
        return "main"
    if git_ref_exists(repo_dir, "refs/heads/master"):
        return "master"

    return git_current_branch(repo_dir)


def git_is_clean(repo_dir: Path) -> bool | None:
    result = run_git_command(["git", "-C", str(repo_dir), "status", "--porcelain"])
    if result.returncode != 0:
        return None
    return result.stdout.strip() == ""


def git_upstream_branch(repo_dir: Path) -> str | None:
    result = run_git_command(
        [
            "git",
            "-C",
            str(repo_dir),
            "rev-parse",
            "--abbrev-ref",
            "--symbolic-full-name",
            "@{u}",
        ]
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def git_branch_fully_pushed(repo_dir: Path) -> bool | None:
    upstream = git_upstream_branch(repo_dir)
    if not upstream:
        return None
    head = git_rev_parse(repo_dir, "HEAD")
    upstream_head = git_rev_parse(repo_dir, upstream)
    if not head or not upstream_head:
        return None
    return head == upstream_head


def git_has_remote_branch(repo_dir: Path, branch: str) -> bool | None:
    result = run_git_command(
        ["git", "-C", str(repo_dir), "ls-remote", "--heads", "origin", branch]
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() != ""


def git_ref_exists(repo_dir: Path, ref: str) -> bool:
    result = run_git_command(
        ["git", "-C", str(repo_dir), "show-ref", "--verify", "--quiet", ref]
    )
    return result.returncode == 0


def git_rev_parse(repo_dir: Path, ref: str) -> str | None:
    result = run_git_command(["git", "-C", str(repo_dir), "rev-parse", ref])
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def git_is_repo(repo_dir: Path) -> bool:
    result = run_git_command(
        ["git", "-C", str(repo_dir), "rev-parse", "--is-inside-work-tree"]
    )
    return result.returncode == 0


def git_commits_ahead(repo_dir: Path, base: str, branch: str) -> int | None:
    result = run_git_command(
        ["git", "-C", str(repo_dir), "rev-list", "--count", f"{base}..{branch}"]
    )
    if result.returncode != 0:
        return None
    try:
        return int(result.stdout.strip())
    except ValueError:
        return None


def git_commit_messages(repo_dir: Path, base: str, branch: str) -> list[str]:
    result = run_git_command(
        ["git", "-C", str(repo_dir), "log", "--format=%B%x1f", f"{base}..{branch}"]
    )
    if result.returncode != 0:
        return []
    raw = result.stdout.strip()
    if not raw:
        return []
    return [msg.strip() for msg in raw.split("\x1f") if msg.strip()]


def git_diff_name_status(repo_dir: Path, base: str, branch: str) -> list[str]:
    result = run_git_command(
        ["git", "-C", str(repo_dir), "diff", "--name-status", f"{base}..{branch}"]
    )
    if result.returncode != 0:
        return []
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    return lines


def git_diff_stat(repo_dir: Path, base: str, branch: str) -> list[str]:
    result = run_git_command(
        ["git", "-C", str(repo_dir), "diff", "--stat", f"{base}..{branch}"]
    )
    if result.returncode != 0:
        return []
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    return lines


def git_head_matches_remote(repo_dir: Path, branch: str) -> bool | None:
    remote_ref = f"origin/{branch}"
    if not git_ref_exists(repo_dir, f"refs/remotes/{remote_ref}"):
        return None
    head = git_rev_parse(repo_dir, "HEAD")
    remote = git_rev_parse(repo_dir, remote_ref)
    if not head or not remote:
        return None
    return head == remote


def workspace_up_to_date(
    checked_out: bool | None, clean: bool | None, remote_equal: bool | None
) -> str:
    if checked_out is False or clean is False or remote_equal is False:
        return "no"
    if checked_out is None or clean is None or remote_equal is None:
        return "unknown"
    return "yes"


def gh_pr_message(repo_dir: Path) -> dict | None:
    result = try_run_command(
        ["gh", "pr", "view", "--json", "title,body,number"], cwd=repo_dir
    )
    if result is None or result.returncode != 0:
        return None
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return None
    title = payload.get("title")
    if not title:
        return None
    return {
        "title": title,
        "body": payload.get("body") or "",
        "number": payload.get("number"),
    }


def append_workspace_branch_summary(
    agents_path: Path,
    repo_dir: Path,
    mainline_branch: str,
    workspace_branch: str,
) -> None:
    if not agents_path.exists():
        return
    if not repo_dir.exists() or not git_is_repo(repo_dir):
        warn("could not append branch summary to AGENTS.md (repo unavailable)")
        return

    pr_message = gh_pr_message(repo_dir)
    commit_messages = []
    if not pr_message:
        commit_messages = git_commit_messages(
            repo_dir, mainline_branch, workspace_branch
        )

    commits_ahead = git_commits_ahead(repo_dir, mainline_branch, workspace_branch)
    diff_names = git_diff_name_status(repo_dir, mainline_branch, workspace_branch)
    diff_stat = git_diff_stat(repo_dir, mainline_branch, workspace_branch)

    checked_out = None
    current_branch = git_current_branch(repo_dir)
    if current_branch:
        checked_out = current_branch == workspace_branch
    clean = git_is_clean(repo_dir)
    remote_equal = git_head_matches_remote(repo_dir, workspace_branch)
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


def format_status(value: bool | None) -> str:
    if value is None:
        return "unknown"
    return "yes" if value else "no"


def collect_workspaces(
    project_root: Path, config: dict, with_status: bool = True
) -> list[dict]:
    branch_config = resolve_branch_config(config)
    resolve_branch_pr(branch_config)
    resolve_branch_history(branch_config)
    workspaces_root = workspaces_root_for_project(project_root)
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
        config = load_json(config_path)
        if not config:
            warn(f"failed to load workspace config at {config_path}")
            return None
        branch = require_workspace_branch(config_path, config)
        workspace_name = branch
        repo_dir = workspace_dir / "repo"
        checked_out: bool | None = None
        clean: bool | None = None
        pushed: bool | None = None
        if with_status and repo_dir.exists():
            current_branch = git_current_branch(repo_dir)
            checked_out = current_branch == branch if current_branch else None
            if current_branch and current_branch == branch:
                clean = git_is_clean(repo_dir)
            else:
                clean = None
            pushed = git_has_remote_branch(repo_dir, branch)
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


def list_workspaces(args: argparse.Namespace) -> None:
    cwd = Path.cwd()
    _, _, origin = resolve_repo_origin(cwd)
    project_root = project_dir_for_origin(origin)
    config_path = project_config_path(project_root)
    config = load_json(config_path)
    if not config:
        die("no Atelier project config found for this repo; run 'atelier init'")

    workspaces = collect_workspaces(
        project_root, config, with_status=getattr(args, "status", False)
    )
    if not workspaces:
        say("No workspaces found.")
        return

    if not getattr(args, "status", False):
        for workspace in workspaces:
            say(workspace["name"])
        return

    rows = [("workspace", "checked_out", "clean", "pushed")]
    for workspace in workspaces:
        rows.append(
            (
                workspace["name"],
                format_status(workspace["checked_out"]),
                format_status(workspace["clean"]),
                format_status(workspace["pushed"]),
            )
        )

    widths = [max(len(row[index]) for row in rows) for index in range(len(rows[0]))]
    for row in rows:
        say(
            "  ".join(
                value.ljust(widths[index]) for index, value in enumerate(row)
            ).rstrip()
        )


def confirm_delete(workspace_name: str) -> bool:
    response = input(f"Delete workspace {workspace_name}? [y/N]: ").strip().lower()
    return response in {"y", "yes"}


def delete_workspace_branch(
    repo_dir: Path, workspace_branch: str, default_branch: str
) -> None:
    if not repo_dir.exists():
        return
    if not git_is_repo(repo_dir):
        return

    current_branch = git_current_branch(repo_dir)
    if current_branch == workspace_branch:
        result = try_run_command(
            ["git", "-C", str(repo_dir), "checkout", default_branch]
        )
        if result is None or result.returncode != 0:
            warn(
                f"failed to checkout {default_branch} before deleting {workspace_branch}"
            )
            return

    if git_ref_exists(repo_dir, f"refs/heads/{workspace_branch}"):
        result = try_run_command(
            ["git", "-C", str(repo_dir), "branch", "-D", workspace_branch]
        )
        if result is None or result.returncode != 0:
            warn(f"failed to delete local branch {workspace_branch}")

    remote_exists = git_has_remote_branch(repo_dir, workspace_branch)
    if remote_exists is False:
        return
    result = try_run_command(
        ["git", "-C", str(repo_dir), "push", "origin", "--delete", workspace_branch]
    )
    if result is None or result.returncode != 0:
        warn(f"failed to delete remote branch {workspace_branch}")


def clean_workspaces(args: argparse.Namespace) -> None:
    cwd = Path.cwd()
    _, _, origin = resolve_repo_origin(cwd)
    project_root = project_dir_for_origin(origin)
    config_path = project_config_path(project_root)
    config = load_json(config_path)
    if not config:
        die("no Atelier project config found for this repo; run 'atelier init'")

    branch_prefix = config.get("branch", {}).get("prefix", "")

    requested = []
    for name in args.workspace_names or []:
        if not name.strip():
            continue
        normalized = normalize_workspace_name(name)
        if not normalized:
            continue
        branch, _, exists = resolve_workspace_target(
            project_root, normalized, branch_prefix, False
        )
        if not exists:
            warn(f"workspace not found: {normalized}")
            continue
        requested.append(branch)

    workspaces = collect_workspaces(
        project_root, config, with_status=not (args.all or requested)
    )
    if not workspaces:
        say("No workspaces found.")
        return

    workspaces_by_name = {workspace["name"]: workspace for workspace in workspaces}
    if args.all and requested:
        die("cannot combine --all with workspace branches")

    if args.all:
        targets = list(workspaces)
    elif requested:
        targets = []
        for name in requested:
            workspace = workspaces_by_name.get(name)
            if not workspace:
                warn(f"workspace not found: {name}")
                continue
            targets.append(workspace)
    else:
        targets = [
            workspace
            for workspace in workspaces
            if workspace["clean"] is True and workspace["pushed"] is True
        ]

    if not targets:
        say("No workspaces to clean.")
        return

    for workspace in targets:
        name = workspace["name"]
        if not args.force and not confirm_delete(name):
            say(f"Skipped workspace {name}")
            continue
        if not getattr(args, "no_branch", False):
            default_branch = git_default_branch(workspace["repo_dir"])
            if not default_branch:
                warn(
                    "failed to determine default branch for "
                    f"{workspace['branch']}; skipping branch deletion"
                )
            else:
                delete_workspace_branch(
                    workspace["repo_dir"], workspace["branch"], default_branch
                )
        try:
            shutil.rmtree(workspace["path"])
        except OSError as exc:
            warn(f"failed to delete workspace {name}: {exc}")
            continue
        say(f"Deleted workspace {name}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="atelier")
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="initialize a project")
    init_parser.add_argument(
        "--branch-prefix", dest="branch_prefix", help="prefix for workspace branches"
    )
    init_parser.add_argument(
        "--branch-pr",
        dest="branch_pr",
        help="expect pull requests for workspace branches (true/false)",
    )
    init_parser.add_argument(
        "--branch-history",
        dest="branch_history",
        help="branch history policy (manual|squash|merge|rebase)",
    )
    init_parser.add_argument("--agent", dest="agent", help="agent name")
    init_parser.add_argument("--editor", dest="editor", help="editor command")
    init_parser.add_argument(
        "--workspace-template",
        action="store_true",
        help="create templates/WORKSPACE.md",
    )
    init_parser.set_defaults(func=init_project)

    open_parser = subparsers.add_parser("open", help="open or create a workspace")
    open_parser.add_argument(
        "workspace_name",
        nargs="?",
        help="workspace branch (defaults to current branch when criteria are met)",
    )
    open_parser.add_argument(
        "--raw",
        action="store_true",
        help="treat the argument as the full branch name",
    )
    open_parser.add_argument(
        "--branch-pr",
        dest="branch_pr",
        help="override pull request expectation (true/false)",
    )
    open_parser.add_argument(
        "--branch-history",
        dest="branch_history",
        help="override history policy (manual|squash|merge|rebase)",
    )
    open_parser.set_defaults(func=open_workspace)

    list_parser = subparsers.add_parser("list", help="list workspaces")
    list_parser.add_argument(
        "--status",
        action="store_true",
        help="include workspace status columns",
    )
    list_parser.set_defaults(func=list_workspaces)

    clean_parser = subparsers.add_parser("clean", help="clean workspaces")
    clean_parser.add_argument(
        "-A",
        "--all",
        action="store_true",
        help="delete all workspaces regardless of state",
    )
    clean_parser.add_argument(
        "-F",
        "--force",
        action="store_true",
        help="delete without confirmation",
    )
    clean_parser.add_argument(
        "--no-branch",
        action="store_true",
        help="do not delete workspace branches",
    )
    clean_parser.add_argument(
        "workspace_names", nargs="*", help="workspace branches to delete"
    )
    clean_parser.set_defaults(func=clean_workspaces)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

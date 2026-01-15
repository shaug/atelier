import argparse
import datetime as dt
import json
import os
import secrets
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from . import __version__

ULID_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

PROJECT_AGENTS_TEMPLATE = """# Atelier Project Overlay

This project is managed using **Atelier**, a workspace-based workflow for
agent-assisted development.

## How Work Is Organized

- Development work is performed in isolated **workspaces**
- Workspaces live under the directory configured for this project
- Each workspace represents **one unit of work**
- Each workspace has its own `AGENTS.md` defining intent and scope

## Authority

- This file describes only the **Atelier workflow overlay**
- Workspace `AGENTS.md` files define execution expectations
- Repository-specific coding conventions are defined elsewhere
  (e.g. a repository-level `AGENTS.md`, if present)

- See `.atelier.json` for the current project configuration used by Atelier.
"""

WORKSPACE_AGENTS_TEMPLATE = """<!-- atelier:{atelier_id}:{workspace_name} -->

# Atelier Workspace

This directory is an **Atelier workspace**.

## Workspace Model

- This workspace represents **one unit of work**
- All code changes for this work should be made under `repo/`
- The code in `repo/` is a real git repository and should be treated normally
- This workspace maps to **one git branch** and **one eventual pull request**

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


def ulid_now() -> str:
    timestamp_ms = int(dt.datetime.now(tz=dt.timezone.utc).timestamp() * 1000)
    randomness = int.from_bytes(secrets.token_bytes(10), "big")
    value = (timestamp_ms << 80) | randomness
    chars: list[str] = []
    for _ in range(26):
        chars.append(ULID_ALPHABET[value & 0x1F])
        value >>= 5
    return "".join(reversed(chars))


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


def find_project_root(start: Path) -> Path | None:
    current = start.resolve()
    for parent in [current] + list(current.parents):
        if (parent / ".atelier.json").exists():
            return parent
    return None


def is_absolute_path(path_value: str) -> bool:
    if path_value.startswith("/") or path_value.startswith("\\"):
        return True
    return os.path.isabs(path_value)


def normalize_repo_url(value: str) -> str:
    raw = value.strip()
    if raw.startswith("git@") or "://" in raw:
        return raw
    if raw.startswith("github.com/"):
        raw = raw[len("github.com/") :]
    if raw.count("/") == 1:
        return f"git@github.com:{raw}.git"
    return value


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


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


def find_codex_session(atelier_id: str, workspace_name: str) -> str | None:
    sessions_root = Path.home() / ".codex" / "sessions"
    if not sessions_root.exists():
        return None
    target = f"atelier:{atelier_id}:{workspace_name}"
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


def init_project(args: argparse.Namespace) -> None:
    cwd = Path.cwd()
    existing_root = find_project_root(cwd)
    if existing_root and existing_root != cwd:
        die(f"existing Atelier project found at {existing_root}; run init there")

    config_path = cwd / ".atelier.json"
    config = load_json(config_path) or {}

    project_name_default = (
        config.get("project", {}).get("name")
        if isinstance(config.get("project"), dict)
        else None
    )
    if not project_name_default:
        project_name_default = cwd.name

    project_name_flag = getattr(args, "project_name_flag", None)
    project_name_arg = getattr(args, "project_name", None)
    if project_name_flag is not None:
        project_name = project_name_flag
    elif project_name_arg is not None:
        project_name = project_name_arg
    else:
        project_name = prompt("Project name", project_name_default, required=True)

    repo_url_default = (
        config.get("project", {}).get("repo_url")
        if isinstance(config.get("project"), dict)
        else ""
    )
    repo_url_arg = getattr(args, "repo_url", None)
    if repo_url_arg is not None:
        repo_url = repo_url_arg
    else:
        repo_url = prompt(
            "Repo URL (owner/name or full URL)", repo_url_default, required=True
        )
    repo_url = normalize_repo_url(repo_url)

    branch_default_default = (
        config.get("branch", {}).get("default")
        if isinstance(config.get("branch"), dict)
        else None
    )
    if not branch_default_default:
        branch_default_default = "main"
    branch_default_arg = getattr(args, "branch_default", None)
    if branch_default_arg is not None:
        branch_default = branch_default_arg
    else:
        branch_default = prompt("Default branch", branch_default_default, required=True)

    branch_prefix_default = (
        config.get("branch", {}).get("prefix")
        if isinstance(config.get("branch"), dict)
        else None
    )
    if branch_prefix_default is None:
        branch_prefix_default = ""
    branch_prefix_arg = getattr(args, "branch_prefix", None)
    if branch_prefix_arg is not None:
        branch_prefix = branch_prefix_arg
    else:
        branch_prefix = prompt("Branch prefix (optional)", branch_prefix_default)

    agent_default_default = (
        config.get("agent", {}).get("default")
        if isinstance(config.get("agent"), dict)
        else None
    )
    if not agent_default_default:
        agent_default_default = "codex"
    agent_arg = getattr(args, "agent", None)
    if agent_arg is not None:
        agent_default = agent_arg
    else:
        agent_default = prompt("Agent (codex)", agent_default_default, required=True)
    if agent_default != "codex":
        die("only 'codex' is supported as the agent in v2")

    editor_default_default = (
        config.get("editor", {}).get("default")
        if isinstance(config.get("editor"), dict)
        else None
    )
    if editor_default_default:
        editor_prompt_default = editor_default_default
    elif shutil.which("cursor"):
        editor_prompt_default = "cursor"
    else:
        editor_prompt_default = system_editor_default()

    editor_arg = getattr(args, "editor", None)
    if editor_arg is not None:
        editor_input = editor_arg
    else:
        editor_input = prompt("Editor command", editor_prompt_default, required=True)
    editor_parts = shlex.split(editor_input)
    editor_default = editor_parts[0]
    editor_input_options = editor_parts[1:]

    workspaces_root_default = (
        config.get("workspaces", {}).get("root")
        if isinstance(config.get("workspaces"), dict)
        else None
    )
    if not workspaces_root_default:
        workspaces_root_default = "workspaces"
    workspaces_root_arg = getattr(args, "workspaces_root", None)
    if workspaces_root_arg is not None:
        workspaces_root = workspaces_root_arg
    else:
        workspaces_root = prompt(
            "Workspaces root", workspaces_root_default, required=True
        )

    atelier_section = (
        config.get("atelier") if isinstance(config.get("atelier"), dict) else {}
    )
    atelier_id = atelier_section.get("id") or ulid_now()
    atelier_created_at = atelier_section.get("created_at") or utc_now()
    atelier_version = atelier_section.get("version") or __version__

    agent_options = {}
    if isinstance(config.get("agent"), dict):
        existing_options = config.get("agent", {}).get("options")
        if isinstance(existing_options, dict):
            agent_options = existing_options
    if "codex" not in agent_options:
        agent_options["codex"] = []

    editor_options = {}
    if isinstance(config.get("editor"), dict):
        existing_editor_options = config.get("editor", {}).get("options")
        if isinstance(existing_editor_options, dict):
            editor_options = existing_editor_options
    if editor_input_options:
        editor_options = {**editor_options, editor_default: editor_input_options}

    payload: dict = {
        "project": {
            "name": project_name,
            "repo_url": repo_url,
        },
        "branch": {
            "default": branch_default,
            "prefix": branch_prefix,
        },
        "agent": {
            "default": agent_default,
            "options": agent_options,
        },
        "editor": {
            "default": editor_default,
            "options": editor_options,
        },
        "workspaces": {
            "root": workspaces_root,
        },
        "atelier": {
            "id": atelier_id,
            "version": atelier_version,
            "created_at": atelier_created_at,
        },
    }

    write_json(config_path, payload)

    agents_path = cwd / "AGENTS.md"
    if not agents_path.exists():
        agents_path.write_text(PROJECT_AGENTS_TEMPLATE, encoding="utf-8")
        say("Created AGENTS.md")

    workspace_root_path = (
        Path(workspaces_root)
        if is_absolute_path(workspaces_root)
        else cwd / workspaces_root
    )
    ensure_dir(workspace_root_path)

    say("Initialized Atelier project")


def open_workspace(args: argparse.Namespace) -> None:
    cwd = Path.cwd()
    project_root = find_project_root(cwd)
    if not project_root:
        die("no .atelier.json found; run 'atelier init' in a project root")

    config_path = project_root / ".atelier.json"
    config = load_json(config_path)
    if not config:
        die("failed to load .atelier.json")

    workspace_name = args.workspace_name.strip()
    if not workspace_name:
        die("workspace name is required")
    branch_override = getattr(args, "branch", None)
    if branch_override is not None:
        branch_override = str(branch_override).strip() or None

    atelier_id = config.get("atelier", {}).get("id")
    if not atelier_id:
        die(".atelier.json missing atelier.id")

    workspaces_root = config.get("workspaces", {}).get("root")
    if not workspaces_root:
        die(".atelier.json missing workspaces.root")

    workspace_root = (
        Path(workspaces_root)
        if is_absolute_path(workspaces_root)
        else project_root / workspaces_root
    )

    workspace_dir = workspace_root / workspace_name
    agents_path = workspace_dir / "AGENTS.md"
    is_new_workspace = not workspace_dir.exists()
    branch_prefix = config.get("branch", {}).get("prefix", "")
    if is_new_workspace:
        workspace_branch = branch_override or f"{branch_prefix}{workspace_name}"
    else:
        workspace_branch = workspace_branch_for_dir(
            workspace_dir, workspace_name, config
        )
        if branch_override and branch_override != workspace_branch:
            die(
                "specified branch does not match configured workspace branch "
                f"({branch_override} != {workspace_branch})"
            )
        if branch_override:
            workspace_branch = branch_override
    if is_new_workspace:
        ensure_dir(workspace_dir)

        workspace_config = {
            "workspace": {
                "name": workspace_name,
                "branch": workspace_branch,
                "id": f"atelier:{atelier_id}:{workspace_name}",
            },
            "atelier": {
                "version": __version__,
                "created_at": utc_now(),
            },
        }
        write_json(workspace_dir / ".atelier.workspace.json", workspace_config)

        template_override = project_root / "templates" / "AGENTS.md"
        if template_override.exists():
            agents_path.write_text(
                template_override.read_text(encoding="utf-8"), encoding="utf-8"
            )
        else:
            agents_path.write_text(
                WORKSPACE_AGENTS_TEMPLATE.format(
                    atelier_id=atelier_id,
                    workspace_name=workspace_name,
                ),
                encoding="utf-8",
            )

    repo_dir = workspace_dir / "repo"
    project_repo_url = config.get("project", {}).get("repo_url")
    if not project_repo_url:
        die(".atelier.json missing project.repo_url")

    default_branch = config.get("branch", {}).get("default")
    if not default_branch:
        die(".atelier.json missing branch.default")

    if not repo_dir.exists():
        ensure_dir(workspace_dir)
        run_command(["git", "clone", project_repo_url, str(repo_dir)])
    else:
        remote_check = subprocess.run(
            ["git", "-C", str(repo_dir), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            check=False,
        )
        if remote_check.returncode == 0:
            current_remote = remote_check.stdout.strip()
            if current_remote and current_remote != project_repo_url:
                warn("repo remote differs from project.repo_url; using existing repo")

    run_command(["git", "-C", str(repo_dir), "checkout", default_branch])

    local_branch = git_ref_exists(repo_dir, f"refs/heads/{workspace_branch}")
    remote_branch = git_ref_exists(repo_dir, f"refs/remotes/origin/{workspace_branch}")
    if not remote_branch:
        remote_branch = git_has_remote_branch(repo_dir, workspace_branch) is True
        if remote_branch:
            run_command(
                ["git", "-C", str(repo_dir), "fetch", "origin", workspace_branch]
            )

    if local_branch:
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

    if is_new_workspace:
        append_workspace_branch_summary(
            agents_path, repo_dir, default_branch, workspace_branch
        )
        editor_cmd = resolve_editor_command(config)
        run_command([*editor_cmd, str(agents_path)], cwd=project_root)

    session_id = find_codex_session(atelier_id, workspace_name)
    if session_id:
        say(f"Resuming Codex session {session_id}")
        run_command(
            ["codex", "--cd", str(workspace_dir), *agent_options, "resume", session_id]
        )
    else:
        opening_prompt = f"atelier:{atelier_id}:{workspace_name}"
        say("Starting new Codex session")
        run_command(
            ["codex", "--cd", str(workspace_dir), *agent_options, opening_prompt]
        )


def resolve_editor_command(config: dict) -> list[str]:
    editor_default = config.get("editor", {}).get("default")
    if editor_default:
        options = config.get("editor", {}).get("options", {}).get(editor_default, [])
        if not isinstance(options, list):
            options = []
        return [editor_default, *options]

    return shlex.split(system_editor_default())


def workspace_root_for_config(project_root: Path, config: dict) -> Path:
    workspaces_root = config.get("workspaces", {}).get("root")
    if not workspaces_root:
        die(".atelier.json missing workspaces.root")
    if is_absolute_path(str(workspaces_root)):
        return Path(workspaces_root)
    return project_root / str(workspaces_root)


def workspace_branch_for_dir(
    workspace_dir: Path, workspace_name: str, config: dict
) -> str:
    workspace_config = load_json(workspace_dir / ".atelier.workspace.json") or {}
    branch = workspace_config.get("workspace", {}).get("branch")
    if branch:
        return str(branch)
    prefix = config.get("branch", {}).get("prefix", "")
    return f"{prefix}{workspace_name}"


def git_current_branch(repo_dir: Path) -> str | None:
    result = run_git_command(
        ["git", "-C", str(repo_dir), "rev-parse", "--abbrev-ref", "HEAD"]
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def git_is_clean(repo_dir: Path) -> bool | None:
    result = run_git_command(["git", "-C", str(repo_dir), "status", "--porcelain"])
    if result.returncode != 0:
        return None
    return result.stdout.strip() == ""


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


def collect_workspaces(project_root: Path, config: dict) -> list[dict]:
    workspaces_root = workspace_root_for_config(project_root, config)
    if not workspaces_root.exists():
        return []
    workspaces: list[dict] = []
    for workspace_dir in sorted(workspaces_root.iterdir(), key=lambda item: item.name):
        if not workspace_dir.is_dir():
            continue
        workspace_name = workspace_dir.name
        repo_dir = workspace_dir / "repo"
        branch = workspace_branch_for_dir(workspace_dir, workspace_name, config)
        checked_out: bool | None = None
        clean: bool | None = None
        pushed: bool | None = None
        if repo_dir.exists():
            current_branch = git_current_branch(repo_dir)
            checked_out = current_branch == branch if current_branch else None
            if current_branch and current_branch == branch:
                clean = git_is_clean(repo_dir)
            else:
                clean = None
            pushed = git_has_remote_branch(repo_dir, branch)
        workspaces.append(
            {
                "name": workspace_name,
                "path": workspace_dir,
                "repo_dir": repo_dir,
                "branch": branch,
                "checked_out": checked_out,
                "clean": clean,
                "pushed": pushed,
            }
        )
    return workspaces


def list_workspaces(args: argparse.Namespace) -> None:
    cwd = Path.cwd()
    project_root = find_project_root(cwd)
    if not project_root:
        die("no .atelier.json found; run 'atelier init' in a project root")

    config_path = project_root / ".atelier.json"
    config = load_json(config_path)
    if not config:
        die("failed to load .atelier.json")

    workspaces = collect_workspaces(project_root, config)
    if not workspaces:
        say("No workspaces found.")
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


def clean_workspaces(args: argparse.Namespace) -> None:
    cwd = Path.cwd()
    project_root = find_project_root(cwd)
    if not project_root:
        die("no .atelier.json found; run 'atelier init' in a project root")

    config_path = project_root / ".atelier.json"
    config = load_json(config_path)
    if not config:
        die("failed to load .atelier.json")

    workspaces = collect_workspaces(project_root, config)
    if not workspaces:
        say("No workspaces found.")
        return

    workspaces_by_name = {workspace["name"]: workspace for workspace in workspaces}

    requested = [name.strip() for name in args.workspace_names or [] if name.strip()]
    if args.all and requested:
        die("cannot combine --all with workspace names")

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
    init_parser.add_argument("project_name", nargs="?", help="project name")
    init_parser.add_argument(
        "--project-name",
        dest="project_name_flag",
        help="project name (overrides positional)",
    )
    init_parser.add_argument(
        "--repo-url", dest="repo_url", help="project repo URL or owner/name"
    )
    init_parser.add_argument(
        "--default-branch", dest="branch_default", help="default branch name"
    )
    init_parser.add_argument(
        "--branch-prefix", dest="branch_prefix", help="prefix for workspace branches"
    )
    init_parser.add_argument("--agent", dest="agent", help="agent name")
    init_parser.add_argument("--editor", dest="editor", help="editor command")
    init_parser.add_argument(
        "--workspaces-root",
        dest="workspaces_root",
        help="directory for workspace roots",
    )
    init_parser.set_defaults(func=init_project)

    open_parser = subparsers.add_parser("open", help="open or create a workspace")
    open_parser.add_argument("workspace_name", help="workspace name")
    open_parser.add_argument(
        "-B", "--branch", dest="branch", help="explicit branch name for the workspace"
    )
    open_parser.set_defaults(func=open_workspace)

    list_parser = subparsers.add_parser("list", help="list workspaces")
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
    clean_parser.add_argument("workspace_names", nargs="*", help="workspaces to delete")
    clean_parser.set_defaults(func=clean_workspaces)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

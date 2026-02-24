"""Agent home directory helpers."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import paths, templates
from .io import die, warn
from .models import ProjectConfig

AGENT_METADATA_FILENAME = "agent.json"
AGENT_INSTRUCTIONS_FILENAME = "AGENTS.md"
CLAUDE_INSTRUCTIONS_FILENAME = "CLAUDE.md"
CLAUDE_DIRNAME = ".claude"
CLAUDE_SETTINGS_FILENAME = "settings.json"
CLAUDE_HOOKS_DIRNAME = "hooks"
CLAUDE_HOOK_SCRIPT = "append_agentsmd_context.sh"
BEADS_PRIME_BLOCK_START = "<!-- ATELIER_BEADS_PRIME_START -->"
BEADS_PRIME_BLOCK_END = "<!-- ATELIER_BEADS_PRIME_END -->"


@dataclass(frozen=True)
class AgentHome:
    name: str
    agent_id: str
    role: str
    path: Path
    session_key: str | None = None


SESSION_ENV_VAR = "ATELIER_AGENT_SESSION"
_SESSION_START_GRACE_NS = 5_000_000_000


def _normalize_agent_name(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        die("agent name must not be empty")
    normalized = normalized.replace("/", "-").replace("\\", "-")
    return normalized


def _derive_agent_name(agent_id: str) -> str:
    parts = [part for part in agent_id.split("/") if part]
    if not parts:
        return _normalize_agent_name(agent_id)
    if len(parts) >= 4 and parts[0] == "atelier":
        return _normalize_agent_name(parts[2])
    return _normalize_agent_name(parts[-1])


def _derive_agent_id(role: str, agent_name: str, *, session_key: str | None = None) -> str:
    normalized_role = role.strip().lower()
    if not normalized_role:
        die("agent role must not be empty")
    base = f"atelier/{normalized_role}/{agent_name}"
    if not session_key:
        return base
    return f"{base}/{session_key}"


def _normalize_session_key(value: str | None) -> str | None:
    if value is None:
        return None
    raw = value.strip()
    if not raw:
        return None
    normalized = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in raw)
    normalized = normalized.strip("-_")
    if not normalized:
        die("agent session key must include alphanumeric characters")
    return normalized


def generate_session_key() -> str:
    """Generate a process-scoped session key for agent-home isolation."""
    return f"p{os.getpid()}-t{time.time_ns()}"


def parse_agent_identity(agent_id: str) -> tuple[str | None, str | None, str | None]:
    """Parse atelier agent identity into role/name/session components."""
    parts = [part for part in str(agent_id).split("/") if part]
    if len(parts) < 3 or parts[0] != "atelier":
        return None, None, None
    role = parts[1]
    name = parts[2]
    session_key = parts[3] if len(parts) >= 4 else None
    return role, name, session_key


def _enforce_role_consistent_agent_id(*, role: str, agent_id: str, source: str) -> None:
    expected_role = role.strip().lower()
    actual_role, _name, _session_key = parse_agent_identity(agent_id)
    if actual_role is None or actual_role.strip().lower() == expected_role:
        return
    die(
        f"{source} role mismatch: expected atelier/{expected_role}/<name> for this session, "
        f"got {agent_id!r}. Unset {source} or set a matching agent identity."
    )


def session_pid_from_agent_id(agent_id: str) -> int | None:
    """Extract the session PID from an agent id when present."""
    _role, _name, session_key = parse_agent_identity(agent_id)
    if not session_key or not session_key.startswith("p"):
        return None
    pid_part = session_key[1:].split("-", 1)[0]
    if not pid_part.isdigit():
        return None
    return int(pid_part)


def session_started_ns_from_agent_id(agent_id: str) -> int | None:
    """Extract the session start timestamp from an agent id, when present."""
    _role, _name, session_key = parse_agent_identity(agent_id)
    if not session_key:
        return None
    marker = "-t"
    if marker not in session_key:
        return None
    _prefix, _sep, raw_ns = session_key.partition(marker)
    if not raw_ns.isdigit():
        return None
    return int(raw_ns)


def _pid_started_ns(pid: int) -> int | None:
    if pid <= 0:
        return None
    result = subprocess.run(
        ["ps", "-o", "lstart=", "-p", str(pid)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    value = (result.stdout or "").strip()
    if not value:
        return None
    try:
        started = datetime.strptime(value, "%a %b %d %H:%M:%S %Y")
    except ValueError:
        return None
    local_tz = datetime.now().astimezone().tzinfo
    if local_tz is not None:
        started = started.replace(tzinfo=local_tz)
    return int(started.timestamp() * 1_000_000_000)


def is_session_agent_active(agent_id: str) -> bool:
    """Return whether a session-scoped agent appears alive."""
    pid = session_pid_from_agent_id(agent_id)
    if pid is None:
        return False
    if pid == os.getpid():
        return True
    try:
        os.kill(pid, 0)
        process_exists = True
    except ProcessLookupError:
        return False
    except PermissionError:
        process_exists = True
    if not process_exists:
        return False
    session_started_ns = session_started_ns_from_agent_id(agent_id)
    if session_started_ns is None:
        return True
    pid_started_ns = _pid_started_ns(pid)
    if pid_started_ns is None:
        return True
    return pid_started_ns <= session_started_ns + _SESSION_START_GRACE_NS


def _agent_home_path(
    project_dir: Path, *, role: str, agent_name: str, session_key: str | None = None
) -> Path:
    base = (
        paths.project_agents_dir(project_dir)
        / _normalize_agent_name(role)
        / _normalize_agent_name(agent_name)
    )
    if not session_key:
        return base
    return base / session_key


def _prune_empty_agent_parents(path: Path, *, stop: Path) -> None:
    current = path
    while True:
        if current == stop:
            break
        try:
            current.rmdir()
        except OSError:
            break
        parent = current.parent
        if parent == current:
            break
        current = parent


def cleanup_agent_home(agent: AgentHome, *, project_dir: Path) -> bool:
    """Remove a session-scoped agent home and prune empty parent directories."""
    if not agent.session_key:
        return False
    target = agent.path
    if not target.exists():
        return False
    expected = _agent_home_path(
        project_dir,
        role=agent.role,
        agent_name=agent.name,
        session_key=agent.session_key,
    )
    if target != expected:
        warn(f"refusing to remove unexpected agent path: {target}")
        return False
    try:
        shutil.rmtree(target, ignore_errors=False)
    except OSError:
        warn(f"failed to remove agent home: {target}")
        return False
    _prune_empty_agent_parents(target.parent, stop=paths.project_agents_dir(project_dir))
    return True


def cleanup_agent_home_by_id(project_dir: Path, agent_id: str) -> bool:
    """Remove session-scoped agent home for an agent identity."""
    home_path = session_home_path_for_agent_id(project_dir, agent_id)
    if home_path is None:
        return False
    role, name, session_key = parse_agent_identity(agent_id)
    if not role or not name or not session_key:
        return False
    normalized = _normalize_session_key(session_key)
    if not normalized:
        return False
    agent = AgentHome(
        name=_normalize_agent_name(name),
        agent_id=agent_id,
        role=_normalize_agent_name(role),
        path=home_path,
        session_key=normalized,
    )
    return cleanup_agent_home(agent, project_dir=project_dir)


def session_home_path_for_agent_id(project_dir: Path, agent_id: str) -> Path | None:
    """Return the session home path for a session-scoped agent id."""
    role, name, session_key = parse_agent_identity(agent_id)
    if not role or not name or not session_key:
        return None
    normalized = _normalize_session_key(session_key)
    if not normalized:
        return None
    return _agent_home_path(
        project_dir,
        role=role,
        agent_name=name,
        session_key=normalized,
    )


def _metadata_path(home_dir: Path) -> Path:
    return home_dir / AGENT_METADATA_FILENAME


def _load_metadata(home_dir: Path) -> AgentHome | None:
    path = _metadata_path(home_dir)
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return None
    agent_id = payload.get("id")
    name = payload.get("name")
    role = payload.get("role")
    session_key = payload.get("session_key")
    if not isinstance(agent_id, str) or not agent_id:
        return None
    if not isinstance(name, str) or not name:
        return None
    if not isinstance(role, str) or not role:
        return None
    if session_key is not None and not isinstance(session_key, str):
        return None
    return AgentHome(
        name=name,
        agent_id=agent_id,
        role=role,
        path=home_dir,
        session_key=_normalize_session_key(session_key),
    )


def _write_metadata(home_dir: Path, agent: AgentHome) -> None:
    payload = {
        "id": agent.agent_id,
        "name": agent.name,
        "role": agent.role,
        "session_key": agent.session_key,
    }
    _metadata_path(home_dir).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def ensure_agent_home(
    project_dir: Path,
    *,
    role: str,
    agent_name: str,
    agent_id: str,
    session_key: str | None = None,
) -> AgentHome:
    """Ensure the agent home directory exists and return its metadata."""
    normalized_session = _normalize_session_key(session_key)
    home_dir = _agent_home_path(
        project_dir,
        role=role,
        agent_name=agent_name,
        session_key=normalized_session,
    )
    paths.ensure_dir(home_dir)

    agents_path = home_dir / AGENT_INSTRUCTIONS_FILENAME
    if not agents_path.exists():
        agents_path.write_text(
            templates.agent_home_template(prefer_installed_if_modified=True),
            encoding="utf-8",
        )

    stored = _load_metadata(home_dir)
    if (
        stored is None
        or stored.agent_id != agent_id
        or stored.role != role
        or stored.session_key != normalized_session
    ):
        stored = AgentHome(
            name=agent_name,
            agent_id=agent_id,
            role=role,
            path=home_dir,
            session_key=normalized_session,
        )
        _write_metadata(home_dir, stored)
    return stored


def resolve_agent_home(
    project_dir: Path,
    project_config: ProjectConfig,
    *,
    role: str,
    session_key: str | None = None,
) -> AgentHome:
    """Resolve the agent identity and ensure the home directory exists."""
    env_agent_id = os.environ.get("ATELIER_AGENT_ID")
    config_agent_id = project_config.agent.identity
    resolved_session = _normalize_session_key(session_key or os.environ.get(SESSION_ENV_VAR))
    if env_agent_id:
        agent_id = env_agent_id.strip()
        if not agent_id:
            die("ATELIER_AGENT_ID must not be empty")
        _enforce_role_consistent_agent_id(
            role=role,
            agent_id=agent_id,
            source="ATELIER_AGENT_ID",
        )
        agent_name = _derive_agent_name(agent_id)
    elif config_agent_id:
        agent_id = config_agent_id
        agent_name = _derive_agent_name(agent_id)
    else:
        agent_name = _normalize_agent_name(project_config.agent.default)
        agent_id = _derive_agent_id(role, agent_name, session_key=resolved_session)
    return ensure_agent_home(
        project_dir,
        role=role,
        agent_name=agent_name,
        agent_id=agent_id,
        session_key=resolved_session,
    )


def _ensure_dir_link(dest: Path, target: Path) -> None:
    if dest.is_symlink():
        try:
            if dest.resolve() == target.resolve():
                return
        except OSError:
            pass
        dest.unlink()
    elif dest.exists():
        return
    try:
        dest.symlink_to(target, target_is_directory=True)
    except OSError:
        warn(f"failed to link {dest} -> {target}")
        path_marker = dest.with_suffix(".path")
        try:
            path_marker.write_text(str(target), encoding="utf-8")
        except OSError:
            return


def ensure_agent_links(
    agent: AgentHome,
    *,
    worktree_path: Path,
    beads_root: Path,
    skills_dir: Path,
    project_skill_lookup_paths: tuple[str, ...] = (),
) -> None:
    """Ensure the agent home exposes links to worktree, skills, and beads."""
    root = agent.path
    if not root.exists():
        return
    _ensure_dir_link(root / "worktree", worktree_path)
    _ensure_dir_link(root / "skills", skills_dir)
    for lookup in project_skill_lookup_paths:
        relative = str(lookup).strip().strip("/")
        if not relative or relative == "skills":
            continue
        alias_path = root / relative
        alias_path.parent.mkdir(parents=True, exist_ok=True)
        _ensure_dir_link(alias_path, skills_dir)
    _ensure_dir_link(root / "beads", beads_root)


def ensure_claude_compat(agent_path: Path, agents_content: str) -> None:
    """Ensure CLAUDE.md and hooks exist for Claude Code compatibility."""
    if not agent_path.exists():
        return
    preface = (
        "This project uses AGENTS.md as the authoritative behavioral contract.\n"
        "Claude must follow the rules below.\n"
    )
    content = preface.rstrip("\n") + "\n\n---\n\n" + agents_content.rstrip("\n") + "\n"
    claude_path = agent_path / CLAUDE_INSTRUCTIONS_FILENAME
    if not claude_path.exists() or claude_path.read_text(encoding="utf-8") != content:
        claude_path.write_text(content, encoding="utf-8")

    claude_dir = agent_path / CLAUDE_DIRNAME
    hooks_dir = claude_dir / CLAUDE_HOOKS_DIRNAME
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hook_path = hooks_dir / CLAUDE_HOOK_SCRIPT
    hook_body = """#!/bin/bash
set -euo pipefail

project_dir="${CLAUDE_PROJECT_DIR:-$(pwd)}"

echo "=== AGENTS.md Files Found ==="
find "$project_dir" -maxdepth 5 -name "AGENTS.md" -type f | while read -r file; do
  echo "--- File: $file ---"
  cat "$file"
  echo ""
done
"""
    if not hook_path.exists() or hook_path.read_text(encoding="utf-8") != hook_body:
        hook_path.write_text(hook_body, encoding="utf-8")
        hook_path.chmod(0o755)

    settings_path = claude_dir / CLAUDE_SETTINGS_FILENAME
    settings_payload = {
        "hooks": {
            "SessionStart": [
                {
                    "matcher": "startup",
                    "hooks": [
                        {
                            "type": "command",
                            "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/"
                            "append_agentsmd_context.sh",
                        }
                    ],
                }
            ]
        }
    }
    current = None
    if settings_path.exists():
        try:
            current = json.loads(settings_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            current = None
    if current != settings_payload:
        settings_path.write_text(json.dumps(settings_payload, indent=2) + "\n", encoding="utf-8")


def apply_beads_prime_addendum(content: str, addendum: str | None) -> str:
    """Insert or update the Beads prime addendum block in AGENTS content."""
    body = (addendum or "").strip("\n")
    if not body:
        return content
    pattern = re.compile(
        re.escape(BEADS_PRIME_BLOCK_START) + r".*?" + re.escape(BEADS_PRIME_BLOCK_END),
        re.DOTALL,
    )
    block = "\n".join(
        [
            BEADS_PRIME_BLOCK_START,
            "## Beads Runtime Addendum",
            "",
            body,
            BEADS_PRIME_BLOCK_END,
        ]
    ).rstrip("\n")
    if pattern.search(content):
        updated = pattern.sub(block, content)
        return updated.rstrip("\n") + "\n"
    trimmed = content.rstrip("\n")
    if trimmed:
        trimmed += "\n\n"
    return trimmed + block + "\n"


def preview_agent_home(
    project_dir: Path,
    project_config: ProjectConfig,
    *,
    role: str,
    session_key: str | None = None,
) -> AgentHome:
    """Return agent identity and path without creating files."""
    env_agent_id = os.environ.get("ATELIER_AGENT_ID")
    config_agent_id = project_config.agent.identity
    resolved_session = _normalize_session_key(session_key or os.environ.get(SESSION_ENV_VAR))
    if env_agent_id:
        agent_id = env_agent_id.strip()
        if not agent_id:
            die("ATELIER_AGENT_ID must not be empty")
        _enforce_role_consistent_agent_id(
            role=role,
            agent_id=agent_id,
            source="ATELIER_AGENT_ID",
        )
        agent_name = _derive_agent_name(agent_id)
    elif config_agent_id:
        agent_id = config_agent_id
        agent_name = _derive_agent_name(agent_id)
    else:
        agent_name = _normalize_agent_name(project_config.agent.default)
        agent_id = _derive_agent_id(role, agent_name, session_key=resolved_session)
    home_dir = _agent_home_path(
        project_dir,
        role=role,
        agent_name=agent_name,
        session_key=resolved_session,
    )
    return AgentHome(
        name=agent_name,
        agent_id=agent_id,
        role=role,
        path=home_dir,
        session_key=resolved_session,
    )

"""Agent home directory helpers."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from . import paths, templates
from .io import die
from .models import ProjectConfig

AGENT_METADATA_FILENAME = "agent.json"
AGENT_INSTRUCTIONS_FILENAME = "AGENTS.md"


@dataclass(frozen=True)
class AgentHome:
    name: str
    agent_id: str
    role: str
    path: Path


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
    return _normalize_agent_name(parts[-1])


def _derive_agent_id(role: str, agent_name: str) -> str:
    normalized_role = role.strip().lower()
    if not normalized_role:
        die("agent role must not be empty")
    return f"atelier/{normalized_role}/{agent_name}"


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
    if not isinstance(agent_id, str) or not agent_id:
        return None
    if not isinstance(name, str) or not name:
        return None
    if not isinstance(role, str) or not role:
        return None
    return AgentHome(name=name, agent_id=agent_id, role=role, path=home_dir)


def _write_metadata(home_dir: Path, agent: AgentHome) -> None:
    payload = {
        "id": agent.agent_id,
        "name": agent.name,
        "role": agent.role,
    }
    _metadata_path(home_dir).write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )


def ensure_agent_home(
    project_dir: Path, *, role: str, agent_name: str, agent_id: str
) -> AgentHome:
    """Ensure the agent home directory exists and return its metadata."""
    root = paths.project_agents_dir(project_dir)
    paths.ensure_dir(root)
    home_dir = root / agent_name
    paths.ensure_dir(home_dir)

    agents_path = home_dir / AGENT_INSTRUCTIONS_FILENAME
    if not agents_path.exists():
        agents_path.write_text(
            templates.agent_home_template(prefer_installed_if_modified=True),
            encoding="utf-8",
        )

    stored = _load_metadata(home_dir)
    if stored is None or stored.agent_id != agent_id or stored.role != role:
        stored = AgentHome(
            name=agent_name, agent_id=agent_id, role=role, path=home_dir
        )
        _write_metadata(home_dir, stored)
    return stored


def resolve_agent_home(
    project_dir: Path, project_config: ProjectConfig, *, role: str
) -> AgentHome:
    """Resolve the agent identity and ensure the home directory exists."""
    env_agent_id = os.environ.get("ATELIER_AGENT_ID")
    if env_agent_id:
        agent_id = env_agent_id.strip()
        if not agent_id:
            die("ATELIER_AGENT_ID must not be empty")
        agent_name = _derive_agent_name(agent_id)
    else:
        agent_name = _normalize_agent_name(project_config.agent.default)
        agent_id = _derive_agent_id(role, agent_name)
    return ensure_agent_home(
        project_dir, role=role, agent_name=agent_name, agent_id=agent_id
    )

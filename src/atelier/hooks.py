"""Hook configuration helpers for hook-capable agent runtimes."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .agent_home import AgentHome
from .agents import AgentSpec
from .io import die

HOOKS_DIRNAME = "hooks"
HOOKS_FILENAME = "atelier-hooks.json"


@dataclass(frozen=True)
class HookCommand:
    event: str
    command: list[str]


def hook_commands() -> tuple[HookCommand, ...]:
    """Return the default hook command set for Atelier."""
    return (
        HookCommand(event="SessionStart", command=["atelier", "hook", "session-start"]),
        HookCommand(event="PreCompact", command=["atelier", "hook", "pre-compact"]),
        HookCommand(event="Stop", command=["atelier", "hook", "stop"]),
    )


def hooks_path(agent_home: AgentHome) -> Path:
    """Return the path to the hook configuration file."""
    return agent_home.path / HOOKS_DIRNAME / HOOKS_FILENAME


def render_hook_config(commands: tuple[HookCommand, ...]) -> dict[str, object]:
    """Render the hook configuration payload."""
    hooks: dict[str, list[list[str]]] = {}
    for command in commands:
        hooks.setdefault(command.event, []).append(command.command)
    return {"hooks": hooks}


def ensure_agent_hooks(agent_home: AgentHome, agent: AgentSpec) -> Path | None:
    """Ensure hook config exists for hook-capable agents."""
    if not agent.supports_hooks:
        return None
    path = hooks_path(agent_home)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = render_hook_config(hook_commands())
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def ensure_hooks_path(env: dict[str, str], path: Path | None) -> None:
    """Inject hook path into the environment when available."""
    if path is None:
        return
    env["ATELIER_HOOKS_PATH"] = str(path)


def parse_hook_event(value: str | None) -> str:
    """Normalize hook event input."""
    if not value:
        return "session-start"
    normalized = value.strip().lower().replace("_", "-")
    allowed = {"session-start", "pre-compact", "stop"}
    if normalized not in allowed:
        die(f"unsupported hook event: {value}")
    return normalized

"""Agent registry and invocation helpers."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal, Mapping

WorkingDirMode = Literal["cwd", "flag"]


@dataclass(frozen=True)
class AgentSpec:
    """Describe how to launch and resume an agent CLI."""

    name: str
    display_name: str
    command: tuple[str, ...]
    working_dir_mode: WorkingDirMode = "cwd"
    working_dir_flag: str | None = None
    prompt_flag: str | None = None
    resume_subcommand: tuple[str, ...] | None = None
    resume_requires_session_id: bool = True
    version_args: tuple[str, ...] = ("--version",)
    yolo_flags: tuple[str, ...] = ()

    def _base_command(
        self, workspace_dir: Path, options: list[str]
    ) -> tuple[list[str], Path | None]:
        cmd = list(self.command)
        cwd: Path | None = None
        if self.working_dir_mode == "flag":
            if not self.working_dir_flag:
                raise ValueError("working_dir_flag required for flag mode")
            cmd.extend([self.working_dir_flag, str(workspace_dir)])
        else:
            cwd = workspace_dir
        if options:
            cmd.extend(options)
        return cmd, cwd

    def build_start_command(
        self, workspace_dir: Path, options: list[str], prompt: str
    ) -> tuple[list[str], Path | None]:
        cmd, cwd = self._base_command(workspace_dir, options)
        if prompt:
            if self.prompt_flag:
                cmd.append(self.prompt_flag)
            cmd.append(prompt)
        return cmd, cwd

    def build_resume_command(
        self, workspace_dir: Path, options: list[str], session_id: str | None
    ) -> tuple[list[str], Path | None] | None:
        if self.resume_subcommand is None:
            return None
        if self.resume_requires_session_id and not session_id:
            return None
        cmd, cwd = self._base_command(workspace_dir, options)
        cmd.extend(self.resume_subcommand)
        if self.resume_requires_session_id and session_id:
            cmd.append(session_id)
        return cmd, cwd


DEFAULT_AGENT = "codex"

AGENTS: dict[str, AgentSpec] = {
    "codex": AgentSpec(
        name="codex",
        display_name="Codex",
        command=("codex",),
        working_dir_mode="flag",
        working_dir_flag="--cd",
        resume_subcommand=("resume",),
        yolo_flags=("--yolo",),
    ),
    "claude": AgentSpec(
        name="claude",
        display_name="Claude",
        command=("claude",),
        resume_subcommand=("--continue",),
        resume_requires_session_id=False,
    ),
    "gemini": AgentSpec(
        name="gemini",
        display_name="Gemini",
        command=("gemini",),
        prompt_flag="--prompt-interactive",
        resume_subcommand=("--resume",),
        resume_requires_session_id=False,
    ),
    "copilot": AgentSpec(
        name="copilot",
        display_name="Copilot",
        command=("copilot",),
        prompt_flag="--interactive",
        resume_subcommand=("--continue",),
        resume_requires_session_id=False,
    ),
    "aider": AgentSpec(
        name="aider",
        display_name="Aider",
        command=("aider",),
        resume_subcommand=("--restore-chat-history",),
        resume_requires_session_id=False,
    ),
}

AIDER_DEFAULT_CHAT_HISTORY = ".aider.chat.history.md"


def normalize_agent_name(value: str | None) -> str:
    if value is None:
        return ""
    return value.strip().lower()


def supported_agents() -> tuple[AgentSpec, ...]:
    return tuple(AGENTS.values())


def supported_agent_names() -> tuple[str, ...]:
    return tuple(AGENTS.keys())


def get_agent(name: str) -> AgentSpec | None:
    normalized = normalize_agent_name(name)
    if not normalized:
        return None
    return AGENTS.get(normalized)


def is_supported_agent(name: str | None) -> bool:
    if name is None:
        return False
    return normalize_agent_name(name) in AGENTS


def probe_agent_version(agent: AgentSpec) -> str | None:
    """Attempt to read a version string from the agent CLI."""
    cmd = [*agent.command, *agent.version_args]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return None
    if result.returncode != 0:
        return None
    output = (result.stdout or result.stderr).strip()
    if not output:
        return None
    return output.splitlines()[0].strip() or None


def available_agents() -> dict[str, str | None]:
    """Return available agent names mapped to their version string when known."""
    available: dict[str, str | None] = {}
    for agent in AGENTS.values():
        executable = agent.command[0]
        if shutil.which(executable) is None:
            continue
        available[agent.name] = probe_agent_version(agent)
    return available


def available_agent_names() -> tuple[str, ...]:
    return tuple(available_agents().keys())


def agent_environment(
    agent_id: str, *, base_env: Mapping[str, str] | None = None
) -> dict[str, str]:
    """Return environment variables for agent identity injection."""
    env = dict(base_env or os.environ)
    if agent_id:
        env["ATELIER_AGENT_ID"] = agent_id
        env["BD_ACTOR"] = agent_id
        env["BEADS_AGENT_NAME"] = agent_id
    return env


def unique_available_agent(available: Iterable[str]) -> str | None:
    names = list(available)
    if len(names) == 1:
        return names[0]
    return None


def find_resume_session(
    agent: AgentSpec,
    project_enlistment: str,
    workspace_branch: str,
    workspace_uid: str | None = None,
) -> str | None:
    if agent.name != "codex":
        return None
    from . import sessions

    return sessions.find_codex_session(
        project_enlistment, workspace_branch, workspace_uid
    )


def apply_yolo_options(agent: AgentSpec, options: list[str]) -> list[str]:
    """Return agent options with any yolo flags appended once."""
    if not agent.yolo_flags:
        return list(options)
    merged = list(options)
    for flag in agent.yolo_flags:
        if flag not in merged:
            merged.append(flag)
    return merged


def aider_chat_history_path(workspace_dir: Path) -> Path | None:
    raw_path = os.environ.get("AIDER_CHAT_HISTORY_FILE")
    if raw_path:
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = workspace_dir / path
    else:
        path = workspace_dir / AIDER_DEFAULT_CHAT_HISTORY
    if not path.is_file():
        return None
    return path

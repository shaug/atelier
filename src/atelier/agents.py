"""Agent registry and invocation helpers."""

from __future__ import annotations

import os
import shutil
import subprocess
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Literal, Mapping, Sequence

WorkingDirMode = Literal["cwd", "flag"]
LaunchRole = Literal["planner", "worker"]

LAUNCH_ROLE_VALUES: tuple[LaunchRole, ...] = ("planner", "worker")
_LAUNCH_ROLE_ALIASES = {
    "plan": "planner",
    "planner": "planner",
    "work": "worker",
    "worker": "worker",
}
_CLAUDE_WORKER_DEFAULT_OPTIONS: tuple[str, ...] = ("--print", "--output-format=stream-json")


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
    supports_hooks: bool = False
    project_skill_lookup_paths: tuple[str, ...] = ()
    global_skill_lookup_paths: tuple[str, ...] = ()

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
        project_skill_lookup_paths=(".agents/skills",),
        global_skill_lookup_paths=("~/.codex/skills",),
    ),
    "claude": AgentSpec(
        name="claude",
        display_name="Claude",
        command=("claude",),
        resume_subcommand=("--continue",),
        resume_requires_session_id=False,
        yolo_flags=("--dangerously-skip-permissions",),
        supports_hooks=True,
        project_skill_lookup_paths=(".claude/skills",),
        global_skill_lookup_paths=("~/.claude/skills",),
    ),
    "gemini": AgentSpec(
        name="gemini",
        display_name="Gemini",
        command=("gemini",),
        prompt_flag="--prompt-interactive",
        resume_subcommand=("--resume",),
        resume_requires_session_id=False,
        supports_hooks=True,
        project_skill_lookup_paths=(".agents/skills",),
        global_skill_lookup_paths=("~/.gemini/skills",),
    ),
    "opencode": AgentSpec(
        name="opencode",
        display_name="OpenCode",
        command=("opencode",),
        supports_hooks=True,
        project_skill_lookup_paths=(".agents/skills",),
        global_skill_lookup_paths=("~/.config/opencode/skills",),
    ),
    "copilot": AgentSpec(
        name="copilot",
        display_name="Copilot",
        command=("copilot",),
        prompt_flag="--interactive",
        resume_subcommand=("--continue",),
        resume_requires_session_id=False,
        project_skill_lookup_paths=(".agents/skills",),
        global_skill_lookup_paths=("~/.copilot/skills",),
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


def normalize_launch_role(value: str | None) -> str:
    """Normalize a launch role string.

    Args:
        value: Raw role value, for example ``planner``, ``plan``,
            ``worker``, or ``work``.

    Returns:
        Canonical role name when supported, otherwise an empty string.
    """
    if value is None:
        return ""
    normalized = value.strip().lower()
    if not normalized:
        return ""
    resolved = _LAUNCH_ROLE_ALIASES.get(normalized)
    return resolved or ""


def supported_agents() -> tuple[AgentSpec, ...]:
    return tuple(AGENTS.values())


def supported_agent_names() -> tuple[str, ...]:
    return tuple(AGENTS.keys())


def get_agent(name: str) -> AgentSpec | None:
    normalized = normalize_agent_name(name)
    if not normalized:
        return None
    return AGENTS.get(normalized)


def skill_lookup_paths(agent_name: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return project/global skill lookup paths for an agent."""
    agent = get_agent(agent_name)
    if agent is None:
        return (), ()
    return agent.project_skill_lookup_paths, agent.global_skill_lookup_paths


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
    """Return available agent names mapped to version strings, when known."""
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
    _inject_atelier_pythonpath(env)
    return env


def _inject_atelier_pythonpath(env: dict[str, str]) -> None:
    """Ensure child tool invocations can import the installed atelier package."""
    import_root = str(Path(__file__).resolve().parent.parent)
    if not import_root:
        return
    current = env.get("PYTHONPATH", "")
    entries = [entry for entry in current.split(os.pathsep) if entry] if current else []
    merged = [import_root]
    seen = {import_root}
    for entry in entries:
        if entry in seen:
            continue
        seen.add(entry)
        merged.append(entry)
    env["PYTHONPATH"] = os.pathsep.join(merged)


@contextmanager
def scoped_agent_env(agent_id: str) -> Iterator[None]:
    """Temporarily set agent identity environment variables."""
    keys = ("ATELIER_AGENT_ID", "BD_ACTOR", "BEADS_AGENT_NAME")
    previous = {key: os.environ.get(key) for key in keys}
    if agent_id:
        os.environ["ATELIER_AGENT_ID"] = agent_id
        os.environ["BD_ACTOR"] = agent_id
        os.environ["BEADS_AGENT_NAME"] = agent_id
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


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

    return sessions.find_codex_session(project_enlistment, workspace_branch, workspace_uid)


def apply_yolo_options(agent: AgentSpec, options: list[str]) -> list[str]:
    """Return agent options with any yolo flags appended once."""
    if not agent.yolo_flags:
        return merge_cli_options(options)
    return merge_cli_options(options, agent.yolo_flags)


@dataclass(frozen=True)
class _OptionTokens:
    tokens: tuple[str, ...]
    key: str | None


def _consume_option_tokens(
    options: Sequence[str], index: int, *, stop_option_parsing: bool
) -> tuple[_OptionTokens, int, bool]:
    token = options[index]
    if stop_option_parsing:
        return _OptionTokens(tokens=(token,), key=None), 1, stop_option_parsing
    if token == "--":
        return _OptionTokens(tokens=("--",), key=None), 1, True
    if not token.startswith("-") or token == "-":
        return _OptionTokens(tokens=(token,), key=None), 1, stop_option_parsing
    if token.startswith("--") and "=" in token:
        flag = token.split("=", 1)[0]
        return _OptionTokens(tokens=(token,), key=flag), 1, stop_option_parsing
    if index + 1 < len(options):
        candidate_value = options[index + 1]
        if not candidate_value.startswith("-"):
            return (
                _OptionTokens(tokens=(token, candidate_value), key=token),
                2,
                stop_option_parsing,
            )
    return _OptionTokens(tokens=(token,), key=token), 1, stop_option_parsing


def merge_cli_options(*groups: Sequence[str]) -> list[str]:
    """Merge CLI option groups using last-wins semantics for option flags.

    Args:
        groups: Option token groups ordered from low to high precedence.

    Returns:
        Deduplicated option tokens with higher-precedence groups overriding
        lower-precedence values for the same flag.
    """
    entries: list[_OptionTokens] = []
    stop_option_parsing = False
    for group in groups:
        normalized_group = [str(token) for token in group]
        index = 0
        while index < len(normalized_group):
            entry, consumed, stop_option_parsing = _consume_option_tokens(
                normalized_group,
                index,
                stop_option_parsing=stop_option_parsing,
            )
            if entry.key is not None:
                entries = [item for item in entries if item.key != entry.key]
            entries.append(entry)
            index += consumed
    merged: list[str] = []
    for entry in entries:
        merged.extend(entry.tokens)
    return merged


def resolve_launch_options(
    *,
    agent_name: str,
    role: str,
    global_options: Mapping[str, list[str]] | None = None,
    launch_options: Mapping[str, Mapping[str, list[str]]] | None = None,
) -> list[str]:
    """Resolve launch options for one role/agent pair.

    Deterministic precedence:
    1) built-in worker defaults (Claude-only)
    2) legacy global `agent.options[agent]`
    3) role-scoped `agent.launch_options[role][agent]`

    Args:
        agent_name: Agent name to resolve, for example ``codex``.
        role: Launch role (``planner``/``worker`` or aliases ``plan``/``work``).
        global_options: Legacy per-agent options map.
        launch_options: Role-scoped per-agent options map.

    Returns:
        Effective launch option tokens for the selected role and agent.

    Raises:
        ValueError: If role is unsupported.
    """
    normalized_agent = normalize_agent_name(agent_name)
    normalized_role = normalize_launch_role(role)
    if normalized_role not in LAUNCH_ROLE_VALUES:
        raise ValueError("role must be one of: planner, worker")
    base_options = list((global_options or {}).get(normalized_agent, []))
    scoped_by_agent = (launch_options or {}).get(normalized_role, {})
    scoped_options = list(scoped_by_agent.get(normalized_agent, []))
    merged = merge_cli_options(base_options, scoped_options)
    if normalized_role == "worker" and normalized_agent == "claude":
        merged = merge_cli_options(_CLAUDE_WORKER_DEFAULT_OPTIONS, merged)
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

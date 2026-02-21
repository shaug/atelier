from __future__ import annotations

from pathlib import Path

from atelier import agent_home, codex
from atelier.models import ProjectConfig
from atelier.worker.session import agent as session_agent


class _FakeAgentSpec:
    def __init__(self, *, name: str = "codex", display_name: str = "Codex") -> None:
        self.name = name
        self.display_name = display_name

    def build_start_command(
        self, _agent_home: Path, _options: list[str], prompt: str
    ) -> tuple[list[str], Path]:
        return ["codex", prompt], Path("/tmp/agent")


class _TestControl:
    def __init__(self) -> None:
        self.logs: list[str] = []

    def confirm(self, _prompt: str, *, default: bool = False) -> bool:
        return default

    def dry_run_log(self, message: str) -> None:
        self.logs.append(message)

    def die(self, _message: str) -> None:
        return None

    def say(self, _message: str) -> None:
        return None


class _TestCommandOps:
    def strip_flag_with_value(self, args: list[str], _flag: str) -> list[str]:
        return args

    def with_codex_exec(self, cmd: list[str], prompt: str) -> list[str]:
        return [*cmd[:-1], "exec", prompt]

    def ensure_exec_subcommand_flag(self, args: list[str], _flag: str) -> list[str]:
        return args


class _TestBlockedHandler:
    def mark_changeset_blocked(self, _reason: str) -> None:
        return None


def _project_config() -> ProjectConfig:
    return ProjectConfig(
        project={"enlistment": "/repo"},
        git={"path": "git"},
        branch={},
        agent={"default": "codex", "options": {"codex": []}},
        editor={},
    )


def test_prepare_agent_session_dry_run_sets_workspace_env(monkeypatch) -> None:
    monkeypatch.setattr(
        session_agent.agents, "get_agent", lambda _name: _FakeAgentSpec(name="codex")
    )
    agent = agent_home.AgentHome(
        name="codex",
        agent_id="atelier/worker/codex/p100",
        role="worker",
        path=Path("/tmp/agent-home"),
    )
    control = _TestControl()

    prep = session_agent.prepare_agent_session(
        project_config=_project_config(),
        project_data_dir=Path("/project-data"),
        repo_root=Path("/repo"),
        beads_root=Path("/beads"),
        agent=agent,
        changeset_worktree_path=Path("/worktree"),
        selected_epic="at-epic",
        changeset_id="at-epic.1",
        root_branch_value="feat/root",
        enlistment_path=Path("/repo"),
        yes=True,
        dry_run=True,
        session_control=control,
        command_ops=_TestCommandOps(),
    )

    assert prep.env["ATELIER_EPIC_ID"] == "at-epic"
    assert prep.env["ATELIER_CHANGESET_ID"] == "at-epic.1"
    assert prep.env["BEADS_DIR"] == "/beads"
    assert any(
        "Would prepare workspace environment variables." in msg for msg in control.logs
    )


def test_start_agent_session_dry_run_returns_none() -> None:
    control = _TestControl()
    agent = agent_home.AgentHome(
        name="codex",
        agent_id="atelier/worker/codex/p100",
        role="worker",
        path=Path("/tmp/agent-home"),
    )
    spec = _FakeAgentSpec(name="codex")

    result = session_agent.start_agent_session(
        dry_run=True,
        agent=agent,
        agent_spec=spec,
        agent_options=[],
        opening_prompt="hello",
        env={},
        command_ops=_TestCommandOps(),
        session_control=control,
        blocked_handler=_TestBlockedHandler(),
    )

    assert result is None
    assert any("Agent command:" in msg for msg in control.logs)


def test_start_agent_session_runs_codex_success(monkeypatch) -> None:
    monkeypatch.setattr(
        codex,
        "run_codex_command",
        lambda _cmd, *, cwd, env: codex.CodexRunResult(
            returncode=0, session_id=None, resume_command=None
        ),
    )
    agent = agent_home.AgentHome(
        name="codex",
        agent_id="atelier/worker/codex/p100",
        role="worker",
        path=Path("/tmp/agent-home"),
    )
    spec = _FakeAgentSpec(name="codex")

    result = session_agent.start_agent_session(
        dry_run=False,
        agent=agent,
        agent_spec=spec,
        agent_options=[],
        opening_prompt="hello",
        env={},
        command_ops=_TestCommandOps(),
        session_control=_TestControl(),
        blocked_handler=_TestBlockedHandler(),
    )

    assert result is not None
    assert result.returncode == 0

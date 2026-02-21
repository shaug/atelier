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
    logs: list[str] = []

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
        strip_flag_with_value=lambda args, _flag: args,
        confirm_update=lambda _message: False,
        dry_run_log=logs.append,
        emit=lambda _message: None,
    )

    assert prep.env["ATELIER_EPIC_ID"] == "at-epic"
    assert prep.env["ATELIER_CHANGESET_ID"] == "at-epic.1"
    assert prep.env["BEADS_DIR"] == "/beads"
    assert any("Would prepare workspace environment variables." in msg for msg in logs)


def test_start_agent_session_dry_run_returns_none() -> None:
    logs: list[str] = []
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
        with_codex_exec=lambda cmd, prompt: [*cmd[:-1], "exec", prompt],
        strip_flag_with_value=lambda args, _flag: args,
        ensure_exec_subcommand_flag=lambda args, _flag: args,
        mark_changeset_blocked=lambda _reason: None,
        die_fn=lambda _message: None,
        dry_run_log=logs.append,
        emit=lambda _message: None,
    )

    assert result is None
    assert any("Agent command:" in msg for msg in logs)


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
        with_codex_exec=lambda cmd, prompt: [*cmd[:-1], "exec", prompt],
        strip_flag_with_value=lambda args, _flag: args,
        ensure_exec_subcommand_flag=lambda args, _flag: args,
        mark_changeset_blocked=lambda _reason: None,
        die_fn=lambda _message: None,
        dry_run_log=lambda _message: None,
        emit=lambda _message: None,
    )

    assert result is not None
    assert result.returncode == 0

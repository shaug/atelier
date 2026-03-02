from __future__ import annotations

from pathlib import Path

from atelier import agent_home, codex
from atelier.models import ProjectConfig
from atelier.worker.session import agent as session_agent


class _FakeAgentSpec:
    def __init__(
        self,
        *,
        name: str = "codex",
        display_name: str = "Codex",
        yolo_flags: tuple[str, ...] = (),
    ) -> None:
        self.name = name
        self.display_name = display_name
        self.yolo_flags = yolo_flags

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
        yolo=False,
        dry_run=True,
        session_control=control,
        command_ops=_TestCommandOps(),
    )

    assert prep.env["ATELIER_EPIC_ID"] == "at-epic"
    assert prep.env["ATELIER_CHANGESET_ID"] == "at-epic.1"
    assert prep.env["BEADS_DIR"] == "/beads"
    assert prep.env["BEADS_DB"] == "/beads/beads.db"
    assert any("Would prepare workspace environment variables." in msg for msg in control.logs)


def test_prepare_agent_session_applies_yolo_options(monkeypatch) -> None:
    monkeypatch.setattr(
        session_agent.agents,
        "get_agent",
        lambda _name: _FakeAgentSpec(name="codex", yolo_flags=("--yolo",)),
    )
    project_config = _project_config().model_copy(
        update={
            "agent": _project_config().agent.model_copy(
                update={"options": {"codex": ["--model", "fast"]}}
            )
        }
    )
    agent = agent_home.AgentHome(
        name="codex",
        agent_id="atelier/worker/codex/p100",
        role="worker",
        path=Path("/tmp/agent-home"),
    )

    prep = session_agent.prepare_agent_session(
        project_config=project_config,
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
        yolo=True,
        dry_run=True,
        session_control=_TestControl(),
        command_ops=_TestCommandOps(),
    )

    assert "--model" in prep.agent_options
    assert "fast" in prep.agent_options
    assert "--yolo" in prep.agent_options


def test_prepare_agent_session_prefers_worker_scoped_options(monkeypatch) -> None:
    monkeypatch.setattr(
        session_agent.agents, "get_agent", lambda _name: _FakeAgentSpec(name="codex")
    )
    project_config = _project_config().model_copy(
        update={
            "agent": _project_config().agent.model_copy(
                update={
                    "options": {"codex": ["--model", "gpt-4"]},
                    "launch_options": {
                        "worker": {"codex": ["--model", "gpt-5"]},
                        "planner": {"codex": ["--model", "gpt-4.5"]},
                    },
                }
            )
        }
    )
    agent = agent_home.AgentHome(
        name="codex",
        agent_id="atelier/worker/codex/p100",
        role="worker",
        path=Path("/tmp/agent-home"),
    )

    prep = session_agent.prepare_agent_session(
        project_config=project_config,
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
        yolo=False,
        dry_run=True,
        session_control=_TestControl(),
        command_ops=_TestCommandOps(),
    )

    assert prep.agent_options == ["--model", "gpt-5"]


def test_prepare_agent_session_applies_claude_yolo_options(monkeypatch) -> None:
    monkeypatch.setattr(
        session_agent.agents,
        "get_agent",
        lambda _name: _FakeAgentSpec(name="claude", yolo_flags=("--dangerously-skip-permissions",)),
    )
    project_config = _project_config().model_copy(
        update={
            "agent": _project_config().agent.model_copy(
                update={"default": "claude", "options": {"claude": ["--model", "sonnet"]}}
            )
        }
    )
    agent = agent_home.AgentHome(
        name="claude",
        agent_id="atelier/worker/claude/p100",
        role="worker",
        path=Path("/tmp/agent-home"),
    )

    prep = session_agent.prepare_agent_session(
        project_config=project_config,
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
        yolo=True,
        dry_run=True,
        session_control=_TestControl(),
        command_ops=_TestCommandOps(),
    )

    assert "--model" in prep.agent_options
    assert "sonnet" in prep.agent_options
    assert "--dangerously-skip-permissions" in prep.agent_options


def test_prepare_agent_session_adds_claude_worker_print_defaults(monkeypatch) -> None:
    monkeypatch.setattr(
        session_agent.agents,
        "get_agent",
        lambda _name: _FakeAgentSpec(name="claude"),
    )
    project_config = _project_config().model_copy(
        update={
            "agent": _project_config().agent.model_copy(
                update={"default": "claude", "options": {"claude": ["--model", "sonnet"]}}
            )
        }
    )
    agent = agent_home.AgentHome(
        name="claude",
        agent_id="atelier/worker/claude/p100",
        role="worker",
        path=Path("/tmp/agent-home"),
    )

    prep = session_agent.prepare_agent_session(
        project_config=project_config,
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
        yolo=False,
        dry_run=True,
        session_control=_TestControl(),
        command_ops=_TestCommandOps(),
    )

    assert "--print" in prep.agent_options
    assert "--output-format=stream-json" in prep.agent_options


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

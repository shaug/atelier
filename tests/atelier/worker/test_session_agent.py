from __future__ import annotations

from pathlib import Path

from atelier import agent_home
from atelier import exec as atelier_exec
from atelier.models import ProjectConfig
from atelier.worker import work_command_helpers
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
        self, _agent_home: Path, options: list[str], prompt: str
    ) -> tuple[list[str], Path]:
        return [self.name, *options, prompt], Path("/tmp/agent")


class _TestControl:
    def __init__(self) -> None:
        self.logs: list[str] = []
        self.say_messages: list[str] = []

    def confirm(self, _prompt: str, *, default: bool = False) -> bool:
        return default

    def dry_run_log(self, message: str) -> None:
        self.logs.append(message)

    def die(self, _message: str) -> None:
        return None

    def say(self, message: str) -> None:
        self.say_messages.append(message)


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
    assert "--verbose" in prep.agent_options


def test_prepare_agent_session_claude_worker_output_override_avoids_forced_verbose(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        session_agent.agents,
        "get_agent",
        lambda _name: _FakeAgentSpec(name="claude"),
    )
    project_config = _project_config().model_copy(
        update={
            "agent": _project_config().agent.model_copy(
                update={
                    "default": "claude",
                    "options": {"claude": ["--model", "sonnet"]},
                    "launch_options": {"worker": {"claude": ["--output-format=json"]}},
                }
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
    assert "--output-format=json" in prep.agent_options
    assert "--verbose" not in prep.agent_options


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


def test_start_agent_session_dry_run_logs_claude_worker_compatible_flags() -> None:
    control = _TestControl()
    agent = agent_home.AgentHome(
        name="claude",
        agent_id="atelier/worker/claude/p100",
        role="worker",
        path=Path("/tmp/agent-home"),
    )
    spec = _FakeAgentSpec(name="claude", display_name="Claude")

    result = session_agent.start_agent_session(
        dry_run=True,
        agent=agent,
        agent_spec=spec,
        agent_options=["--print", "--output-format=stream-json", "--verbose"],
        opening_prompt="hello",
        env={},
        command_ops=_TestCommandOps(),
        session_control=control,
        blocked_handler=_TestBlockedHandler(),
    )

    assert result is None
    command_logs = [msg for msg in control.logs if msg.startswith("Agent command:")]
    assert len(command_logs) == 1
    assert "--output-format=stream-json" in command_logs[0]
    assert "--verbose" in command_logs[0]


def test_start_agent_session_runs_codex_success(monkeypatch) -> None:
    seen: dict[str, object] = {}

    def _run_streaming_capture_command(
        *,
        cmd: list[str],
        cwd: Path | None,
        env: dict[str, str],
        stdout_line_handler=None,
        stderr_line_handler=None,
    ) -> session_agent._StreamedCommandResult | None:
        del stderr_line_handler
        seen["cmd"] = list(cmd)
        seen["cwd"] = cwd
        seen["env"] = env
        if stdout_line_handler is not None:
            stdout_line_handler('{"type":"turn.started"}')
            stdout_line_handler(
                '{"type":"item.completed","item":{"type":"agent_message","text":"Implemented"}}'
            )
        return session_agent._StreamedCommandResult(
            returncode=0,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(
        session_agent,
        "_run_streaming_capture_command",
        _run_streaming_capture_command,
    )
    agent = agent_home.AgentHome(
        name="codex",
        agent_id="atelier/worker/codex/p100",
        role="worker",
        path=Path("/tmp/agent-home"),
    )
    spec = _FakeAgentSpec(name="codex")
    control = _TestControl()

    result = session_agent.start_agent_session(
        dry_run=False,
        agent=agent,
        agent_spec=spec,
        agent_options=[],
        opening_prompt="hello",
        env={},
        command_ops=_TestCommandOps(),
        session_control=control,
        blocked_handler=_TestBlockedHandler(),
    )

    assert result is not None
    assert result.returncode == 0
    assert "exec" in seen["cmd"]
    assert any("Agent output (codex): completed" in line for line in control.say_messages)


def test_start_agent_session_codex_emits_live_progress_updates(monkeypatch) -> None:
    def _run_streaming_capture_command(
        *,
        cmd: list[str],
        cwd: Path | None,
        env: dict[str, str],
        stdout_line_handler=None,
        stderr_line_handler=None,
    ) -> session_agent._StreamedCommandResult | None:
        del cmd, cwd, env, stderr_line_handler
        if stdout_line_handler is not None:
            stdout_line_handler('{"type":"thread.started","thread_id":"thread_1"}')
            stdout_line_handler(
                '{"type":"item.completed","item":{"type":"reasoning","text":"Assessing scope"}}'
            )
            stdout_line_handler(
                '{"type":"item.completed","item":{"type":"command_execution","command":"bash -lc ls"}}'
            )
            stdout_line_handler(
                '{"type":"item.completed","item":{"type":"reasoning","text":"Inspecting history"}}'
            )
            stdout_line_handler(
                '{"type":"item.completed","item":{"type":"command_execution","command":"git status"}}'
            )
            stdout_line_handler(
                '{"type":"item.completed","item":{"type":"reasoning","text":"Preparing patch"}}'
            )
            stdout_line_handler(
                '{"type":"item.completed","item":{"type":"reasoning","text":"Validating diff"}}'
            )
            stdout_line_handler(
                '{"type":"item.completed","item":{"type":"reasoning","text":"Ready to summarize"}}'
            )
            stdout_line_handler(
                '{"type":"item.completed","item":{"type":"agent_message","text":"Applied fix"}}'
            )
        return session_agent._StreamedCommandResult(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(
        session_agent,
        "_run_streaming_capture_command",
        _run_streaming_capture_command,
    )
    agent = agent_home.AgentHome(
        name="codex",
        agent_id="atelier/worker/codex/p100",
        role="worker",
        path=Path("/tmp/agent-home"),
    )
    control = _TestControl()

    result = session_agent.start_agent_session(
        dry_run=False,
        agent=agent,
        agent_spec=_FakeAgentSpec(name="codex"),
        agent_options=[],
        opening_prompt="hello",
        env={},
        command_ops=_TestCommandOps(),
        session_control=control,
        blocked_handler=_TestBlockedHandler(),
    )

    assert result is not None
    assert any("• Codex stream connected" in m for m in control.say_messages)
    assert any("• Ran bash -lc ls" in m for m in control.say_messages)
    assert any("• Ran git status" in m for m in control.say_messages)
    reasoning_lines = [m for m in control.say_messages if m.startswith("• Reasoning: ")]
    assert len(reasoning_lines) == 5
    assert any("• Reasoning: Assessing scope" in m for m in control.say_messages)
    assert any("• Reasoning: Ready to summarize" in m for m in control.say_messages)
    assert any("• Preview:" in m for m in control.say_messages)
    assert any("Agent output (codex): completed" in m for m in control.say_messages)


def test_consume_stream_chunk_flushes_split_lines_deterministically() -> None:
    captured: list[str] = []
    handled: list[str] = []

    pending = session_agent._consume_stream_chunk(
        chunk=b'{"type":"turn.started"}\npartial',
        pending="",
        target=captured,
        line_handler=handled.append,
    )
    assert pending == "partial"
    assert captured == ['{"type":"turn.started"}']
    assert handled == ['{"type":"turn.started"}']

    pending = session_agent._consume_stream_chunk(
        chunk=b' line\n{"type":"turn.completed","usage":{"output_tokens":1}}',
        pending=pending,
        target=captured,
        line_handler=handled.append,
    )
    assert pending == '{"type":"turn.completed","usage":{"output_tokens":1}}'
    assert captured == ['{"type":"turn.started"}', "partial line"]
    assert handled == ['{"type":"turn.started"}', "partial line"]

    session_agent._flush_stream_tail(
        pending=pending,
        target=captured,
        line_handler=handled.append,
    )

    assert captured == [
        '{"type":"turn.started"}',
        "partial line",
        '{"type":"turn.completed","usage":{"output_tokens":1}}',
    ]
    assert handled == [
        '{"type":"turn.started"}',
        "partial line",
        '{"type":"turn.completed","usage":{"output_tokens":1}}',
    ]


class _RealCommandOps:
    """Command ops using actual worker helpers (for integration-style tests)."""

    def with_codex_exec(self, cmd: list[str], prompt: str) -> list[str]:
        return work_command_helpers.with_codex_exec(cmd, prompt)

    def strip_flag_with_value(self, args: list[str], flag: str) -> list[str]:
        return work_command_helpers.strip_flag_with_value(args, flag)

    def ensure_exec_subcommand_flag(self, args: list[str], flag: str) -> list[str]:
        return work_command_helpers.ensure_exec_subcommand_flag(args, flag)


def test_start_agent_session_codex_includes_json_flag(monkeypatch) -> None:
    """Codex worker sessions must pass --json for structured output parsing."""
    seen_cmd: list[str] = []

    def _run_streaming_capture_command(
        *,
        cmd: list[str],
        cwd: Path | None,
        env: dict[str, str],
        stdout_line_handler=None,
        stderr_line_handler=None,
    ) -> session_agent._StreamedCommandResult | None:
        del cwd, env, stderr_line_handler
        seen_cmd[:] = cmd
        if stdout_line_handler is not None:
            stdout_line_handler('{"type":"turn.completed","usage":{"output_tokens":1}}')
        return session_agent._StreamedCommandResult(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(
        session_agent,
        "_run_streaming_capture_command",
        _run_streaming_capture_command,
    )
    agent = agent_home.AgentHome(
        name="codex",
        agent_id="atelier/worker/codex/p100",
        role="worker",
        path=Path("/tmp/agent-home"),
    )

    session_agent.start_agent_session(
        dry_run=False,
        agent=agent,
        agent_spec=_FakeAgentSpec(name="codex"),
        agent_options=[],
        opening_prompt="hello",
        env={},
        command_ops=_RealCommandOps(),
        session_control=_TestControl(),
        blocked_handler=_TestBlockedHandler(),
    )

    assert "--json" in seen_cmd


def test_start_agent_session_codex_trace_streams_raw_output(monkeypatch) -> None:
    seen_requests: list[atelier_exec.CommandRequest] = []

    def _run_with_runner(
        request: atelier_exec.CommandRequest, *, runner=None
    ) -> atelier_exec.CommandResult | None:
        del runner
        seen_requests.append(request)
        return atelier_exec.CommandResult(
            argv=request.argv,
            returncode=0,
            stdout="",
            stderr="",
        )

    def _run_streaming_capture_command(
        *,
        cmd: list[str],
        cwd: Path | None,
        env: dict[str, str],
        stdout_line_handler=None,
        stderr_line_handler=None,
    ) -> session_agent._StreamedCommandResult | None:
        del cmd, cwd, env, stdout_line_handler, stderr_line_handler
        raise AssertionError("streaming capture should not be used in trace mode")

    monkeypatch.setattr(session_agent.exec, "run_with_runner", _run_with_runner)
    monkeypatch.setattr(
        session_agent,
        "_run_streaming_capture_command",
        _run_streaming_capture_command,
    )
    agent = agent_home.AgentHome(
        name="codex",
        agent_id="atelier/worker/codex/p100",
        role="worker",
        path=Path("/tmp/agent-home"),
    )
    spec = _FakeAgentSpec(name="codex")
    control = _TestControl()

    result = session_agent.start_agent_session(
        dry_run=False,
        agent=agent,
        agent_spec=spec,
        agent_options=[],
        opening_prompt="hello",
        env={"ATELIER_WORK_AGENT_TRACE": "1"},
        command_ops=_TestCommandOps(),
        session_control=control,
        blocked_handler=_TestBlockedHandler(),
    )

    assert result is not None
    assert result.returncode == 0
    assert len(seen_requests) == 1
    assert seen_requests[0].capture_output is False
    assert seen_requests[0].text is False
    assert not any("Agent output (codex):" in line for line in control.say_messages)


def test_start_agent_session_codex_failure_with_truncated_tail_uses_tail_diagnostic(
    monkeypatch,
) -> None:
    def _run_streaming_capture_command(
        *,
        cmd: list[str],
        cwd: Path | None,
        env: dict[str, str],
        stdout_line_handler=None,
        stderr_line_handler=None,
    ) -> session_agent._StreamedCommandResult | None:
        del cmd, cwd, env, stderr_line_handler
        if stdout_line_handler is not None:
            stdout_line_handler(
                '{"type":"item.completed","item":{"type":"agent_message","text":"Working"}}'
            )
            stdout_line_handler(
                '{"type":"item.completed","item":{"type":"agent_message","text":"incomplete"'
            )
        return session_agent._StreamedCommandResult(returncode=1, stdout="", stderr="")

    monkeypatch.setattr(
        session_agent,
        "_run_streaming_capture_command",
        _run_streaming_capture_command,
    )
    agent = agent_home.AgentHome(
        name="codex",
        agent_id="atelier/worker/codex/p100",
        role="worker",
        path=Path("/tmp/agent-home"),
    )
    control = _TestControl()

    result = session_agent.start_agent_session(
        dry_run=False,
        agent=agent,
        agent_spec=_FakeAgentSpec(name="codex"),
        agent_options=[],
        opening_prompt="hello",
        env={},
        command_ops=_TestCommandOps(),
        session_control=control,
        blocked_handler=_TestBlockedHandler(),
    )

    assert result is None
    assert any("Agent output (codex): failed" in line for line in control.say_messages)
    assert any(
        'Diagnostic: {"type":"item.completed","item":{"type":"agent_message","text":"incomplete"'
        in line
        for line in control.say_messages
    )
    assert any("ATELIER_WORK_AGENT_TRACE=1" in line for line in control.say_messages)


def test_start_agent_session_claude_stream_json_renders_summary(
    monkeypatch,
    claude_session_fixture_content: str,
) -> None:
    """Claude fixture stdout renders a summary with events and preview text."""
    seen_cmds: list[list[str]] = []

    def _run_streaming_capture_command(
        *,
        cmd: list[str],
        cwd: Path | None,
        env: dict[str, str],
        stdout_line_handler=None,
        stderr_line_handler=None,
    ) -> session_agent._StreamedCommandResult | None:
        del cwd, env, stderr_line_handler
        seen_cmds.append(list(cmd))
        if stdout_line_handler is not None:
            for line in claude_session_fixture_content.splitlines():
                stdout_line_handler(line)
        return session_agent._StreamedCommandResult(
            returncode=0,
            stdout=claude_session_fixture_content,
            stderr="",
        )

    monkeypatch.setattr(
        session_agent,
        "_run_streaming_capture_command",
        _run_streaming_capture_command,
    )
    agent = agent_home.AgentHome(
        name="claude",
        agent_id="atelier/worker/claude/p100",
        role="worker",
        path=Path("/tmp/agent-home"),
    )
    spec = _FakeAgentSpec(name="claude", display_name="Claude")
    control = _TestControl()

    result = session_agent.start_agent_session(
        dry_run=False,
        agent=agent,
        agent_spec=spec,
        agent_options=["--print", "--output-format=stream-json", "--verbose"],
        opening_prompt="hello",
        env={},
        command_ops=_TestCommandOps(),
        session_control=control,
        blocked_handler=_TestBlockedHandler(),
    )

    assert result is not None
    assert result.returncode == 0
    assert len(seen_cmds) == 1
    assert seen_cmds[0][0] == "claude"
    assert any(
        "Claude stream: receiving structured events." in line for line in control.say_messages
    )
    assert any("Agent output (claude): completed" in line for line in control.say_messages)
    assert any("Assistant preview:" in line for line in control.say_messages)
    assert any("events=" in line for line in control.say_messages)
    assert any("tools=" in line for line in control.say_messages)


def test_start_agent_session_claude_failure_reports_diagnostic(monkeypatch) -> None:
    def _run_streaming_capture_command(
        *,
        cmd: list[str],
        cwd: Path | None,
        env: dict[str, str],
        stdout_line_handler=None,
        stderr_line_handler=None,
    ) -> session_agent._StreamedCommandResult | None:
        del cmd, cwd, env, stderr_line_handler
        if stdout_line_handler is not None:
            stdout_line_handler('{"type":"error","error":{"message":"tool call failed"}}')
        return session_agent._StreamedCommandResult(
            returncode=1,
            stdout='{"type":"error","error":{"message":"tool call failed"}}\n',
            stderr="",
        )

    monkeypatch.setattr(
        session_agent,
        "_run_streaming_capture_command",
        _run_streaming_capture_command,
    )
    agent = agent_home.AgentHome(
        name="claude",
        agent_id="atelier/worker/claude/p100",
        role="worker",
        path=Path("/tmp/agent-home"),
    )
    spec = _FakeAgentSpec(name="claude", display_name="Claude")
    control = _TestControl()

    result = session_agent.start_agent_session(
        dry_run=False,
        agent=agent,
        agent_spec=spec,
        agent_options=["--print", "--output-format=stream-json", "--verbose"],
        opening_prompt="hello",
        env={},
        command_ops=_TestCommandOps(),
        session_control=control,
        blocked_handler=_TestBlockedHandler(),
    )

    assert result is None
    assert any("Agent output (claude): failed" in line for line in control.say_messages)
    assert any("Diagnostic: tool call failed" in line for line in control.say_messages)
    assert any("ATELIER_WORK_AGENT_TRACE=1" in line for line in control.say_messages)


def test_start_agent_session_non_claude_preserves_passthrough_mode(monkeypatch) -> None:
    seen_requests: list[atelier_exec.CommandRequest] = []

    def _run_with_runner(
        request: atelier_exec.CommandRequest, *, runner=None
    ) -> atelier_exec.CommandResult | None:
        del runner
        seen_requests.append(request)
        return atelier_exec.CommandResult(
            argv=request.argv,
            returncode=0,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(session_agent.exec, "run_with_runner", _run_with_runner)
    agent = agent_home.AgentHome(
        name="gemini",
        agent_id="atelier/worker/gemini/p100",
        role="worker",
        path=Path("/tmp/agent-home"),
    )
    spec = _FakeAgentSpec(name="gemini", display_name="Gemini")

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
    assert len(seen_requests) == 1
    assert seen_requests[0].capture_output is False
    assert seen_requests[0].text is False

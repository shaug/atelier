import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from atelier import agents
from atelier.agents import AgentSpec, get_agent
from atelier.models import AgentConfig


class TestAgentSpec:
    def test_build_start_command_uses_cwd_mode(self) -> None:
        spec = AgentSpec(
            name="demo",
            display_name="Demo",
            command=("demo",),
        )
        workspace_dir = Path("/tmp/workspace")
        cmd, cwd = spec.build_start_command(workspace_dir, ["--opt"], "hello world")
        assert cmd == ["demo", "--opt", "hello world"]
        assert cwd == workspace_dir

    def test_build_start_command_flag_mode_requires_flag(self) -> None:
        spec = AgentSpec(
            name="demo",
            display_name="Demo",
            command=("demo",),
            working_dir_mode="flag",
        )
        with pytest.raises(ValueError):
            spec.build_start_command(Path("/tmp/workspace"), [], "hello")

    def test_build_start_command_flag_mode_orders_args(self) -> None:
        spec = AgentSpec(
            name="demo",
            display_name="Demo",
            command=("demo",),
            working_dir_mode="flag",
            working_dir_flag="--cd",
        )
        workspace_dir = Path("/tmp/workspace")
        cmd, cwd = spec.build_start_command(workspace_dir, ["--opt"], "hello")
        assert cmd == ["demo", "--cd", str(workspace_dir), "--opt", "hello"]
        assert cwd is None

    def test_build_start_command_prompt_flag(self) -> None:
        spec = AgentSpec(
            name="demo",
            display_name="Demo",
            command=("demo",),
            prompt_flag="--prompt-interactive",
        )
        cmd, _ = spec.build_start_command(Path("/tmp/workspace"), [], "hello")
        assert cmd == ["demo", "--prompt-interactive", "hello"]

    def test_build_resume_command_requires_session_id(self) -> None:
        spec = AgentSpec(
            name="demo",
            display_name="Demo",
            command=("demo",),
            working_dir_mode="flag",
            working_dir_flag="--cd",
            resume_subcommand=("resume",),
        )
        workspace_dir = Path("/tmp/workspace")
        assert spec.build_resume_command(workspace_dir, [], None) is None
        cmd, cwd = spec.build_resume_command(workspace_dir, ["--opt"], "sess-1") or (
            [],
            None,
        )
        assert cmd == ["demo", "--cd", str(workspace_dir), "--opt", "resume", "sess-1"]
        assert cwd is None

    def test_build_resume_command_without_session_id_allowed(self) -> None:
        spec = AgentSpec(
            name="demo",
            display_name="Demo",
            command=("demo",),
            resume_subcommand=("continue",),
            resume_requires_session_id=False,
        )
        cmd, cwd = spec.build_resume_command(Path("/tmp/workspace"), ["--opt"], None) or (
            [],
            None,
        )
        assert cmd == ["demo", "--opt", "continue"]
        assert cwd == Path("/tmp/workspace")

    def test_build_resume_command_no_subcommand(self) -> None:
        spec = AgentSpec(name="demo", display_name="Demo", command=("demo",))
        assert spec.build_resume_command(Path("/tmp/workspace"), ["--opt"], "sess-1") is None

    def test_copilot_defaults(self) -> None:
        copilot = get_agent("copilot")
        assert copilot is not None
        assert copilot.command == ("copilot",)
        assert copilot.prompt_flag == "--interactive"
        assert copilot.resume_subcommand == ("--continue",)
        assert copilot.resume_requires_session_id is False

    def test_aider_defaults(self) -> None:
        aider = get_agent("aider")
        assert aider is not None
        assert aider.command == ("aider",)
        assert aider.resume_subcommand == ("--restore-chat-history",)
        assert aider.resume_requires_session_id is False

    def test_supported_agent_names(self) -> None:
        assert agents.supported_agent_names() == (
            "codex",
            "claude",
            "gemini",
            "opencode",
            "copilot",
            "aider",
        )

    def test_skill_lookup_paths_codex(self) -> None:
        project_paths, global_paths = agents.skill_lookup_paths("codex")
        assert project_paths == (".agents/skills",)
        assert global_paths == ("~/.codex/skills",)

    def test_skill_lookup_paths_claude(self) -> None:
        project_paths, global_paths = agents.skill_lookup_paths("claude")
        assert project_paths == (".claude/skills",)
        assert global_paths == ("~/.claude/skills",)

    def test_claude_yolo_flag_defaults(self) -> None:
        claude = get_agent("claude")
        assert claude is not None
        assert claude.yolo_flags == ("--dangerously-skip-permissions",)

    def test_skill_lookup_paths_unsupported_agent(self) -> None:
        assert agents.skill_lookup_paths("unknown") == ((), ())

    def test_agent_config_rejects_unsupported_default(self) -> None:
        with pytest.raises(ValidationError):
            AgentConfig(default="unsupported", options={})

    def test_agent_config_rejects_unsupported_options(self) -> None:
        with pytest.raises(ValidationError):
            AgentConfig(default="codex", options={"unsupported": ["--flag"]})

    def test_agent_config_accepts_supported_default(self) -> None:
        config = AgentConfig(default="Codex", options={"codex": []})
        assert config.default == "codex"

    def test_agent_config_accepts_role_scoped_launch_options(self) -> None:
        config = AgentConfig(
            default="codex",
            options={"codex": []},
            launch_options={
                "plan": {"codex": ["--model", "gpt-5"]},
                "worker": {"claude": ["--print"]},
            },
        )
        assert config.launch_options["planner"]["codex"] == ["--model", "gpt-5"]
        assert config.launch_options["worker"]["claude"] == ["--print"]

    def test_agent_config_rejects_unsupported_role_scoped_launch_options(self) -> None:
        with pytest.raises(ValidationError):
            AgentConfig(
                default="codex",
                options={"codex": []},
                launch_options={"unknown": {"codex": ["--flag"]}},
            )

    def test_agent_config_rejects_unsupported_agents_in_launch_options(self) -> None:
        with pytest.raises(ValidationError):
            AgentConfig(
                default="codex",
                options={"codex": []},
                launch_options={"worker": {"unsupported": ["--flag"]}},
            )

    def test_merge_cli_options_uses_last_wins_for_flag_values(self) -> None:
        merged = agents.merge_cli_options(
            ["--model", "haiku", "--print"],
            ["--model=sonnet", "--output-format", "json"],
        )
        assert merged == ["--print", "--model=sonnet", "--output-format", "json"]

    def test_resolve_launch_options_prefers_role_scoped_over_global(self) -> None:
        resolved = agents.resolve_launch_options(
            agent_name="codex",
            role="planner",
            global_options={"codex": ["--model", "gpt-4"]},
            launch_options={"planner": {"codex": ["--model", "gpt-5"]}},
        )
        assert resolved == ["--model", "gpt-5"]

    def test_resolve_launch_options_adds_claude_worker_print_defaults(self) -> None:
        resolved = agents.resolve_launch_options(
            agent_name="claude",
            role="worker",
            global_options={"claude": ["--model", "sonnet"]},
            launch_options={},
        )
        assert "--print" in resolved
        assert "--output-format=stream-json" in resolved

    def test_resolve_launch_options_keeps_claude_planner_interactive(self) -> None:
        resolved = agents.resolve_launch_options(
            agent_name="claude",
            role="planner",
            global_options={"claude": ["--model", "sonnet"]},
            launch_options={},
        )
        assert "--print" not in resolved

    def test_aider_chat_history_path_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace_dir = Path(tmp)
            history = workspace_dir / agents.AIDER_DEFAULT_CHAT_HISTORY
            history.write_text("hello\n", encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                assert agents.aider_chat_history_path(workspace_dir) == history

    def test_aider_chat_history_path_env_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace_dir = Path(tmp)
            history = workspace_dir / "custom.history"
            history.write_text("hello\n", encoding="utf-8")
            with patch.dict(os.environ, {"AIDER_CHAT_HISTORY_FILE": "custom.history"}, clear=True):
                assert agents.aider_chat_history_path(workspace_dir) == history

    def test_aider_chat_history_path_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace_dir = Path(tmp)
            with patch.dict(os.environ, {}, clear=True):
                assert agents.aider_chat_history_path(workspace_dir) is None

    def test_agent_environment_injects_atelier_pythonpath(self) -> None:
        env = agents.agent_environment("planner/test-session", base_env={})
        expected_root = str(Path(agents.__file__).resolve().parent.parent)
        assert env["ATELIER_AGENT_ID"] == "planner/test-session"
        assert env["BD_ACTOR"] == "planner/test-session"
        assert env["BEADS_AGENT_NAME"] == "planner/test-session"
        assert env["PYTHONPATH"].split(os.pathsep)[0] == expected_root

    def test_agent_environment_preserves_existing_pythonpath_entries(self) -> None:
        expected_root = str(Path(agents.__file__).resolve().parent.parent)
        existing = ["/tmp/one", expected_root, "/tmp/two", "/tmp/one"]
        env = agents.agent_environment(
            "planner/test-session",
            base_env={"PYTHONPATH": os.pathsep.join(existing)},
        )
        assert env["PYTHONPATH"].split(os.pathsep) == [expected_root, "/tmp/one", "/tmp/two"]

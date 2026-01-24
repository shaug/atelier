import os
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from pydantic import ValidationError

from atelier import agents
from atelier.agents import AgentSpec, get_agent
from atelier.models import AgentConfig


class AgentSpecTestCase(TestCase):
    def test_build_start_command_uses_cwd_mode(self) -> None:
        spec = AgentSpec(
            name="demo",
            display_name="Demo",
            command=("demo",),
        )
        workspace_dir = Path("/tmp/workspace")
        cmd, cwd = spec.build_start_command(workspace_dir, ["--opt"], "hello world")
        self.assertEqual(cmd, ["demo", "--opt", "hello world"])
        self.assertEqual(cwd, workspace_dir)

    def test_build_start_command_flag_mode_requires_flag(self) -> None:
        spec = AgentSpec(
            name="demo",
            display_name="Demo",
            command=("demo",),
            working_dir_mode="flag",
        )
        with self.assertRaises(ValueError):
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
        self.assertEqual(cmd, ["demo", "--cd", str(workspace_dir), "--opt", "hello"])
        self.assertIsNone(cwd)

    def test_build_start_command_prompt_flag(self) -> None:
        spec = AgentSpec(
            name="demo",
            display_name="Demo",
            command=("demo",),
            prompt_flag="--prompt-interactive",
        )
        cmd, _ = spec.build_start_command(Path("/tmp/workspace"), [], "hello")
        self.assertEqual(cmd, ["demo", "--prompt-interactive", "hello"])

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
        self.assertIsNone(spec.build_resume_command(workspace_dir, [], None))
        cmd, cwd = spec.build_resume_command(workspace_dir, ["--opt"], "sess-1") or (
            [],
            None,
        )
        self.assertEqual(
            cmd,
            ["demo", "--cd", str(workspace_dir), "--opt", "resume", "sess-1"],
        )
        self.assertIsNone(cwd)

    def test_build_resume_command_without_session_id_allowed(self) -> None:
        spec = AgentSpec(
            name="demo",
            display_name="Demo",
            command=("demo",),
            resume_subcommand=("continue",),
            resume_requires_session_id=False,
        )
        cmd, cwd = spec.build_resume_command(
            Path("/tmp/workspace"), ["--opt"], None
        ) or (
            [],
            None,
        )
        self.assertEqual(cmd, ["demo", "--opt", "continue"])
        self.assertEqual(cwd, Path("/tmp/workspace"))

    def test_build_resume_command_no_subcommand(self) -> None:
        spec = AgentSpec(name="demo", display_name="Demo", command=("demo",))
        self.assertIsNone(
            spec.build_resume_command(Path("/tmp/workspace"), ["--opt"], "sess-1")
        )

    def test_copilot_defaults(self) -> None:
        copilot = get_agent("copilot")
        self.assertIsNotNone(copilot)
        assert copilot is not None
        self.assertEqual(copilot.command, ("copilot",))
        self.assertEqual(copilot.prompt_flag, "--interactive")
        self.assertEqual(copilot.resume_subcommand, ("--continue",))
        self.assertFalse(copilot.resume_requires_session_id)

    def test_aider_defaults(self) -> None:
        aider = get_agent("aider")
        self.assertIsNotNone(aider)
        assert aider is not None
        self.assertEqual(aider.command, ("aider",))
        self.assertEqual(aider.resume_subcommand, ("--restore-chat-history",))
        self.assertFalse(aider.resume_requires_session_id)

    def test_supported_agent_names(self) -> None:
        self.assertEqual(
            agents.supported_agent_names(),
            ("codex", "claude", "gemini", "copilot", "aider"),
        )

    def test_agent_config_rejects_unsupported_default(self) -> None:
        with self.assertRaises(ValidationError):
            AgentConfig(default="unsupported", options={})

    def test_agent_config_rejects_unsupported_options(self) -> None:
        with self.assertRaises(ValidationError):
            AgentConfig(default="codex", options={"unsupported": ["--flag"]})

    def test_agent_config_accepts_supported_default(self) -> None:
        config = AgentConfig(default="Codex", options={"codex": []})
        self.assertEqual(config.default, "codex")

    def test_aider_chat_history_path_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace_dir = Path(tmp)
            history = workspace_dir / agents.AIDER_DEFAULT_CHAT_HISTORY
            history.write_text("hello\n", encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                self.assertEqual(agents.aider_chat_history_path(workspace_dir), history)

    def test_aider_chat_history_path_env_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace_dir = Path(tmp)
            history = workspace_dir / "custom.history"
            history.write_text("hello\n", encoding="utf-8")
            with patch.dict(
                os.environ, {"AIDER_CHAT_HISTORY_FILE": "custom.history"}, clear=True
            ):
                self.assertEqual(agents.aider_chat_history_path(workspace_dir), history)

    def test_aider_chat_history_path_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace_dir = Path(tmp)
            with patch.dict(os.environ, {}, clear=True):
                self.assertIsNone(agents.aider_chat_history_path(workspace_dir))

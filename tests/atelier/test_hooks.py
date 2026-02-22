from pathlib import Path
from tempfile import TemporaryDirectory

from atelier import hooks
from atelier.agent_home import AgentHome
from atelier.agents import AgentSpec


def test_ensure_agent_hooks_writes_config_for_supported_agent() -> None:
    with TemporaryDirectory() as tmp:
        home = AgentHome(
            name="agent",
            agent_id="atelier/worker/agent",
            role="worker",
            path=Path(tmp),
        )
        agent = AgentSpec(
            name="claude",
            display_name="Claude",
            command=("claude",),
            supports_hooks=True,
        )
        path = hooks.ensure_agent_hooks(home, agent)
        assert path is not None
        payload = path.read_text(encoding="utf-8")
        assert "SessionStart" in payload
        assert "atelier" in payload


def test_ensure_agent_hooks_skips_when_unsupported() -> None:
    with TemporaryDirectory() as tmp:
        home = AgentHome(
            name="agent",
            agent_id="atelier/worker/agent",
            role="worker",
            path=Path(tmp),
        )
        agent = AgentSpec(name="codex", display_name="Codex", command=("codex",))
        path = hooks.ensure_agent_hooks(home, agent)
        assert path is None


def test_ensure_hooks_path_sets_env() -> None:
    env: dict[str, str] = {}
    hooks.ensure_hooks_path(env, Path("/tmp/hooks.json"))
    assert env["ATELIER_HOOKS_PATH"] == "/tmp/hooks.json"


def test_parse_hook_event_accepts_commit_msg() -> None:
    assert hooks.parse_hook_event("commit-msg") == "commit-msg"

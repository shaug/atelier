import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from atelier import agent_home
from atelier.models import AgentConfig, ProjectConfig


def _assert_link_or_marker(base: Path, name: str, target: Path) -> None:
    link = base / name
    if link.is_symlink():
        assert link.resolve() == target.resolve()
        return
    marker = base / f"{name}.path"
    assert marker.exists()
    assert marker.read_text(encoding="utf-8").strip() == str(target)


def test_resolve_agent_home_creates_metadata_and_instructions() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp) / "project"
        project_dir.mkdir(parents=True)
        home = agent_home.resolve_agent_home(
            project_dir, ProjectConfig(), role="worker"
        )

        assert home.path.exists()
        assert (home.path / agent_home.AGENT_INSTRUCTIONS_FILENAME).exists()
        metadata_path = home.path / agent_home.AGENT_METADATA_FILENAME
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        assert payload["id"] == "atelier/worker/codex"
        assert payload["name"] == "codex"
        assert payload["role"] == "worker"
        assert home.path == project_dir / "agents" / "worker" / "codex"


def test_env_agent_id_overrides_default_name() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp) / "project"
        project_dir.mkdir(parents=True)
        with patch.dict(os.environ, {"ATELIER_AGENT_ID": "atelier/worker/alice"}):
            home = agent_home.resolve_agent_home(
                project_dir, ProjectConfig(), role="worker"
            )
        assert home.name == "alice"
        assert home.agent_id == "atelier/worker/alice"
        assert home.path == project_dir / "agents" / "worker" / "alice"


def test_config_agent_identity_is_used_when_env_missing() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp) / "project"
        project_dir.mkdir(parents=True)
        config_payload = ProjectConfig(agent=AgentConfig(identity="atelier/worker/bob"))
        home = agent_home.resolve_agent_home(project_dir, config_payload, role="worker")
    assert home.name == "bob"
    assert home.agent_id == "atelier/worker/bob"
    assert home.path == project_dir / "agents" / "worker" / "bob"


def test_session_agent_home_isolated_by_session_key() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp) / "project"
        project_dir.mkdir(parents=True)
        home = agent_home.resolve_agent_home(
            project_dir,
            ProjectConfig(),
            role="worker",
            session_key="p111-t222",
        )
        assert home.agent_id == "atelier/worker/codex/p111-t222"
        assert home.path == project_dir / "agents" / "worker" / "codex" / "p111-t222"
        metadata_path = home.path / agent_home.AGENT_METADATA_FILENAME
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        assert payload["session_key"] == "p111-t222"


def test_preview_agent_home_uses_session_env_var() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp) / "project"
        project_dir.mkdir(parents=True)
        with patch.dict(os.environ, {agent_home.SESSION_ENV_VAR: "p10-t20"}):
            home = agent_home.preview_agent_home(
                project_dir,
                ProjectConfig(),
                role="planner",
            )
        assert home.agent_id == "atelier/planner/codex/p10-t20"
        assert home.path == project_dir / "agents" / "planner" / "codex" / "p10-t20"


def test_ensure_agent_links_creates_symlinks_or_markers() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        project_dir = root / "project"
        project_dir.mkdir(parents=True)
        home = agent_home.resolve_agent_home(
            project_dir, ProjectConfig(), role="worker"
        )
        worktree = root / "worktree"
        beads = root / "beads"
        skills = root / "skills"
        worktree.mkdir()
        beads.mkdir()
        skills.mkdir()

        agent_home.ensure_agent_links(
            home,
            worktree_path=worktree,
            beads_root=beads,
            skills_dir=skills,
        )

        _assert_link_or_marker(home.path, "worktree", worktree)
        _assert_link_or_marker(home.path, "beads", beads)
        _assert_link_or_marker(home.path, "skills", skills)


def test_cleanup_agent_home_removes_session_dir_and_prunes() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp) / "project"
        project_dir.mkdir(parents=True)
        home = agent_home.resolve_agent_home(
            project_dir,
            ProjectConfig(),
            role="worker",
            session_key="p1-t2",
        )
        marker = home.path / "marker.txt"
        marker.write_text("x", encoding="utf-8")
        assert home.path.exists()

        removed = agent_home.cleanup_agent_home(home, project_dir=project_dir)

        assert removed is True
        assert not home.path.exists()
        assert not (project_dir / "agents" / "worker" / "codex").exists()


def test_cleanup_agent_home_by_id_ignores_non_session_identity() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp) / "project"
        project_dir.mkdir(parents=True)
        removed = agent_home.cleanup_agent_home_by_id(
            project_dir, "atelier/worker/codex"
        )
        assert removed is False


def test_ensure_claude_compat_writes_files() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        agent_path = root / "agent"
        agent_path.mkdir(parents=True)
        content = "# Agent Instructions\nRule: test\n"

        agent_home.ensure_claude_compat(agent_path, content)

        claude_md = agent_path / agent_home.CLAUDE_INSTRUCTIONS_FILENAME
        assert claude_md.exists()
        assert "AGENTS.md" in claude_md.read_text(encoding="utf-8")

        hook_path = (
            agent_path
            / agent_home.CLAUDE_DIRNAME
            / agent_home.CLAUDE_HOOKS_DIRNAME
            / agent_home.CLAUDE_HOOK_SCRIPT
        )
        assert hook_path.exists()

        settings_path = (
            agent_path / agent_home.CLAUDE_DIRNAME / agent_home.CLAUDE_SETTINGS_FILENAME
        )
        assert settings_path.exists()

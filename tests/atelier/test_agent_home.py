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


def test_config_agent_identity_is_used_when_env_missing() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp) / "project"
        project_dir.mkdir(parents=True)
        config_payload = ProjectConfig(agent=AgentConfig(identity="atelier/worker/bob"))
        home = agent_home.resolve_agent_home(project_dir, config_payload, role="worker")
    assert home.name == "bob"
    assert home.agent_id == "atelier/worker/bob"


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

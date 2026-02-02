import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from atelier import agent_home
from atelier.models import AgentConfig, ProjectConfig


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
        config_payload = ProjectConfig(
            agent=AgentConfig(identity="atelier/worker/bob")
        )
        home = agent_home.resolve_agent_home(
            project_dir, config_payload, role="worker"
        )
    assert home.name == "bob"
    assert home.agent_id == "atelier/worker/bob"

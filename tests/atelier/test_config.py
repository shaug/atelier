import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import atelier.config as config
import atelier.paths as paths
from atelier.models import AtelierSection, ProjectConfig


def test_build_project_config_sets_data_dir() -> None:
    args = SimpleNamespace(
        branch_prefix="",
        branch_pr_mode="draft",
        branch_history="merge",
        branch_pr_strategy="sequential",
        agent="codex",
        editor_edit="cat",
        editor_work="cat",
        ticket_provider="none",
        ticket_project=None,
        ticket_namespace=None,
    )
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp) / "data"
        with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
            with patch("atelier.agents.available_agent_names", return_value=("codex",)):
                payload = config.build_project_config(
                    {},
                    "/repo",
                    "github.com/org/repo",
                    "https://github.com/org/repo",
                    args,
                    allow_editor_empty=True,
                )
            expected = str(paths.project_dir_for_enlistment("/repo", "github.com/org/repo"))
    assert payload.atelier.data_dir == expected


def test_resolve_project_data_dir_prefers_config() -> None:
    config_payload = ProjectConfig(atelier=AtelierSection(data_dir="/custom"))
    assert config.resolve_project_data_dir(Path("/project"), config_payload) == Path("/custom")


def test_resolve_beads_root_is_project_scoped() -> None:
    project_dir = Path("/project/.atelier")
    repo_root = Path("/project/repo")
    assert config.resolve_beads_root(project_dir, repo_root) == project_dir / ".beads"


def test_build_project_config_forces_project_beads_location() -> None:
    args = SimpleNamespace(
        branch_prefix="",
        branch_pr_mode="draft",
        branch_history="merge",
        branch_pr_strategy="sequential",
        agent="codex",
        editor_edit="cat",
        editor_work="cat",
    )
    existing = {
        "beads": {"location": "repo"},
    }
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp) / "data"
        with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
            with patch("atelier.agents.available_agent_names", return_value=("codex",)):
                payload = config.build_project_config(
                    existing,
                    "/repo",
                    "github.com/org/repo",
                    "https://github.com/org/repo",
                    args,
                    allow_editor_empty=True,
                )
    assert payload.beads.location == "project"


def test_build_project_config_accepts_branch_squash_message_override() -> None:
    args = SimpleNamespace(
        branch_prefix="",
        branch_pr_mode="draft",
        branch_history="squash",
        branch_squash_message="agent",
        branch_pr_strategy="sequential",
        agent="codex",
        editor_edit="cat",
        editor_work="cat",
    )
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp) / "data"
        with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
            with patch("atelier.agents.available_agent_names", return_value=("codex",)):
                payload = config.build_project_config(
                    {},
                    "/repo",
                    "github.com/org/repo",
                    "https://github.com/org/repo",
                    args,
                    allow_editor_empty=True,
                )
    assert payload.branch.squash_message == "agent"


def test_build_project_config_preserves_project_auto_export_setting() -> None:
    args = SimpleNamespace(
        branch_prefix="",
        branch_pr_mode="draft",
        branch_history="merge",
        branch_pr_strategy="sequential",
        agent="codex",
        editor_edit="cat",
        editor_work="cat",
    )
    existing = {
        "project": {
            "auto_export_new": True,
        },
    }
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp) / "data"
        with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
            with patch("atelier.agents.available_agent_names", return_value=("codex",)):
                payload = config.build_project_config(
                    existing,
                    "/repo",
                    "github.com/org/repo",
                    "https://github.com/org/repo",
                    args,
                    allow_editor_empty=True,
                )
    assert payload.project.auto_export_new is True


def test_build_project_config_accepts_explicit_none_pr_mode() -> None:
    args = SimpleNamespace(
        branch_prefix="",
        branch_pr_mode="none",
        branch_history="merge",
        branch_pr_strategy="sequential",
        agent="codex",
        editor_edit="cat",
        editor_work="cat",
    )
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp) / "data"
        with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
            with patch("atelier.agents.available_agent_names", return_value=("codex",)):
                payload = config.build_project_config(
                    {},
                    "/repo",
                    "github.com/org/repo",
                    "https://github.com/org/repo",
                    args,
                    allow_editor_empty=True,
                )
    assert payload.branch.pr_mode == "none"

import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import atelier.config as config
import atelier.paths as paths
from atelier.models import AtelierSection, ProjectConfig


def test_build_project_config_sets_data_dir() -> None:
    args = SimpleNamespace(
        branch_prefix="",
        beads_prefix="at",
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
        beads_prefix="at",
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
    assert payload.beads.runtime_mode == "dolt-server"


def test_build_project_config_normalizes_legacy_beads_runtime_mode() -> None:
    args = SimpleNamespace(
        branch_prefix="",
        beads_prefix="at",
        branch_pr_mode="draft",
        branch_history="merge",
        branch_pr_strategy="sequential",
        agent="codex",
        editor_edit="cat",
        editor_work="cat",
    )
    existing = {
        "beads": {"mode": "server"},
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
    assert payload.beads.runtime_mode == "dolt-server"


def test_resolve_beads_runtime_mode_defaults_to_dolt_server() -> None:
    assert config.resolve_beads_runtime_mode(None) == "dolt-server"
    assert config.resolve_beads_runtime_mode({"beads": {"runtime_mode": "server"}}) == "dolt-server"


def test_build_project_config_accepts_branch_squash_message_override() -> None:
    args = SimpleNamespace(
        branch_prefix="",
        beads_prefix="at",
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
        beads_prefix="at",
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
        beads_prefix="at",
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


def test_build_project_config_skips_pr_strategy_prompt_when_pr_mode_none() -> None:
    args = SimpleNamespace(
        branch_prefix="",
        beads_prefix="at",
        branch_pr_mode="none",
        branch_history="merge",
        branch_squash_message="deterministic",
        branch_pr_strategy=None,
        agent="codex",
        editor_edit="cat",
        editor_work="cat",
    )
    existing = {
        "branch": {
            "pr_mode": "none",
            "pr_strategy": "on-ready",
        }
    }
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp) / "data"
        with (
            patch("atelier.paths.atelier_data_dir", return_value=data_dir),
            patch("atelier.agents.available_agent_names", return_value=("codex",)),
            patch(
                "atelier.config.select",
                side_effect=AssertionError("select should not be called"),
            ),
        ):
            payload = config.build_project_config(
                existing,
                "/repo",
                "github.com/org/repo",
                "https://github.com/org/repo",
                args,
                allow_editor_empty=True,
            )

    assert payload.branch.pr_mode == "none"
    assert payload.branch.pr_strategy == "on-ready"


@pytest.mark.parametrize("pr_mode", ("draft", "ready"))
def test_build_project_config_prompts_pr_strategy_when_pr_mode_enabled(pr_mode: str) -> None:
    args = SimpleNamespace(
        branch_prefix="",
        beads_prefix="at",
        branch_pr_mode=pr_mode,
        branch_history="merge",
        branch_squash_message="deterministic",
        branch_pr_strategy=None,
        agent="codex",
        editor_edit="cat",
        editor_work="cat",
    )
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp) / "data"
        with (
            patch("atelier.paths.atelier_data_dir", return_value=data_dir),
            patch("atelier.agents.available_agent_names", return_value=("codex",)),
            patch("atelier.config.select", return_value="parallel") as select_mock,
        ):
            payload = config.build_project_config(
                {},
                "/repo",
                "github.com/org/repo",
                "https://github.com/org/repo",
                args,
                allow_editor_empty=True,
            )

    select_mock.assert_called_once_with(
        "PR strategy",
        config.pr_strategy.PR_STRATEGY_VALUES,
        "sequential",
    )
    assert payload.branch.pr_mode == pr_mode
    assert payload.branch.pr_strategy == "parallel"


def test_derive_beads_prefix_seed_for_tuber_service() -> None:
    assert config.derive_beads_prefix_seed("/tmp/tuber-service", None) == "ts"


def test_suggest_available_beads_prefix_uses_deterministic_numeric_suffix() -> None:
    assert config.suggest_available_beads_prefix("ts", {"ts"}) == "ts2"
    assert config.suggest_available_beads_prefix("ts", {"ts", "ts2"}) == "ts3"


def test_resolve_beads_prefix_defaults_and_reads_explicit_prefix() -> None:
    assert config.resolve_beads_prefix(None) == "at"
    assert config.resolve_beads_prefix({"beads": {"prefix": "ts"}}) == "ts"


def test_build_project_config_rejects_colliding_beads_prefix_override() -> None:
    args = SimpleNamespace(
        branch_prefix="",
        beads_prefix="ts",
        branch_pr_mode="draft",
        branch_history="merge",
        branch_pr_strategy="sequential",
        agent="codex",
        editor_edit="cat",
        editor_work="cat",
    )
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp) / "data"
        with (
            patch("atelier.paths.atelier_data_dir", return_value=data_dir),
            patch("atelier.agents.available_agent_names", return_value=("codex",)),
            patch("atelier.config.discover_local_project_prefixes", return_value={"ts"}),
            pytest.raises(SystemExit),
        ):
            config.build_project_config(
                {},
                "/repo",
                "github.com/org/repo",
                "https://github.com/org/repo",
                args,
                allow_editor_empty=True,
            )


def test_build_project_config_non_interactive_uses_available_suggested_beads_prefix() -> None:
    args = SimpleNamespace(
        branch_prefix="",
        beads_prefix=None,
        branch_pr_mode="draft",
        branch_history="merge",
        branch_pr_strategy="sequential",
        agent="codex",
        editor_edit="cat",
        editor_work="cat",
    )
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp) / "data"
        with (
            patch("atelier.paths.atelier_data_dir", return_value=data_dir),
            patch("atelier.agents.available_agent_names", return_value=("codex",)),
            patch("atelier.config.discover_local_project_prefixes", return_value={"at"}),
        ):
            payload = config.build_project_config(
                ProjectConfig(),
                "/tmp/tuber-service",
                None,
                None,
                args,
                prompt_missing_only=True,
                raw_existing={"beads": {"prefix": "at"}},
                allow_editor_empty=True,
            )

    assert payload.beads.prefix == "ts"

from __future__ import annotations

import importlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import atelier.config as config
from tests.atelier.helpers import DummyResult

normalize_prefix_cmd = importlib.import_module("atelier.commands.normalize_prefix")


def test_rollback_guidance_uses_supported_beads_commands(tmp_path: Path) -> None:
    project_data_dir = tmp_path / "data"
    beads_root = tmp_path / "beads-store"

    guidance = normalize_prefix_cmd._rollback_guidance(
        project_data_dir=project_data_dir,
        beads_root=beads_root,
    )

    rendered = "\n".join(guidance.values())
    assert guidance["beads_inspect"] == f'BEADS_DIR="{beads_root}" bd info --json'
    assert guidance["beads_backup"].startswith(
        f'cp -R "{beads_root}" "{beads_root.parent / (beads_root.name + ".backup-")}'
    )
    assert "bd export" not in rendered
    assert "sync --export" not in rendered


def test_normalize_prefix_apply_json_guidance_uses_supported_commands(tmp_path: Path) -> None:
    root = tmp_path
    project_root = root / "project"
    repo_root = root / "repo"
    project_root.mkdir(parents=True, exist_ok=True)
    repo_root.mkdir(parents=True, exist_ok=True)

    project_config = config.ProjectConfig.model_validate(
        {"project": {"enlistment": str(repo_root), "origin": "github.com/org/repo"}}
    )
    project_data_dir = config.resolve_project_data_dir(project_root, project_config)
    beads_root = config.resolve_beads_root(project_data_dir, repo_root)

    with (
        patch(
            "atelier.commands.normalize_prefix.resolve_current_project_with_repo_root",
            return_value=(project_root, project_config, str(repo_root), repo_root),
        ),
        patch("atelier.commands.normalize_prefix.beads.run_bd_command", return_value=DummyResult()),
        patch("atelier.commands.normalize_prefix._active_agent_hook_blockers", return_value=[]),
        patch(
            "atelier.commands.normalize_prefix.prefix_migration_drift.repair_prefix_migration_drift",
            return_value=[],
        ),
    ):
        buffer = io.StringIO()
        with patch("sys.stdout", buffer):
            normalize_prefix_cmd.normalize_prefix(
                SimpleNamespace(format="json", apply=True, force=False)
            )

    payload = json.loads(buffer.getvalue())
    guidance = payload["rollback_guidance"]
    rendered = "\n".join(guidance.values())

    assert guidance["beads_inspect"] == f'BEADS_DIR="{beads_root}" bd info --json'
    assert "bd info --json" in rendered
    assert "bd export" not in rendered
    assert "sync --export" not in rendered

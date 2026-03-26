from __future__ import annotations

import importlib
import io
import json
import sqlite3
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import atelier.config as config
from tests.atelier.helpers import DummyResult

repair_cmd = importlib.import_module("atelier.commands.repair_event_history")
beads_module = importlib.import_module("atelier.beads")


def test_repair_event_history_overflow_json_reports_sqlite_backup() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        project_root = root / "project"
        repo_root = root / "repo"
        beads_root = root / "beads"
        project_root.mkdir(parents=True, exist_ok=True)
        repo_root.mkdir(parents=True, exist_ok=True)
        beads_root.mkdir(parents=True, exist_ok=True)
        sqlite3.connect(beads_root / "beads.db").close()
        project_config = config.ProjectConfig.model_validate(
            {"project": {"enlistment": str(repo_root), "origin": "github.com/org/repo"}}
        )
        result = beads_module.EventHistoryOverflowRepairResult(
            issue_id="at-overflow",
            repaired=True,
            verified_mutable=True,
            snapshot_bytes_before=90000,
            snapshot_bytes_after=32000,
            retained_notes_chars=4096,
        )

        with (
            patch(
                "atelier.commands.repair_event_history.resolve_current_project_with_repo_root",
                return_value=(project_root, project_config, str(repo_root), repo_root),
            ),
            patch(
                "atelier.commands.repair_event_history.config.resolve_beads_root",
                return_value=beads_root,
            ),
            patch(
                "atelier.commands.repair_event_history.beads.run_bd_command",
                return_value=DummyResult(),
            ),
            patch(
                "atelier.commands.repair_event_history.beads.configured_beads_backend",
                return_value="sqlite",
            ),
            patch(
                "atelier.commands.repair_event_history.beads.repair_issue_event_history_overflow",
                return_value=result,
            ),
        ):
            buffer = io.StringIO()
            with patch("sys.stdout", buffer):
                repair_cmd.repair_event_history_overflow(
                    SimpleNamespace(issue_id="at-overflow", format="json")
                )
            payload = json.loads(buffer.getvalue())
            assert payload["backup_path"].endswith(".sqlite3")
            assert Path(payload["backup_path"]).exists()

    payload = json.loads(buffer.getvalue())
    assert payload["backend"] == "sqlite"
    assert payload["issue_id"] == "at-overflow"
    assert payload["repaired"] is True
    assert payload["verified_mutable"] is True
    assert "does not support `bd history` or `bd restore`" in payload["recovery_guidance"]


def test_repair_event_history_overflow_table_uses_dolt_guidance_without_backup() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        project_root = root / "project"
        repo_root = root / "repo"
        beads_root = root / "beads"
        project_root.mkdir(parents=True, exist_ok=True)
        repo_root.mkdir(parents=True, exist_ok=True)
        beads_root.mkdir(parents=True, exist_ok=True)
        project_config = config.ProjectConfig.model_validate(
            {"project": {"enlistment": str(repo_root), "origin": "github.com/org/repo"}}
        )
        result = beads_module.EventHistoryOverflowRepairResult(
            issue_id="at-overflow",
            repaired=False,
            verified_mutable=True,
            snapshot_bytes_before=1200,
            snapshot_bytes_after=1200,
            retained_notes_chars=12,
        )

        with (
            patch(
                "atelier.commands.repair_event_history.resolve_current_project_with_repo_root",
                return_value=(project_root, project_config, str(repo_root), repo_root),
            ),
            patch(
                "atelier.commands.repair_event_history.config.resolve_beads_root",
                return_value=beads_root,
            ),
            patch(
                "atelier.commands.repair_event_history.beads.run_bd_command",
                return_value=DummyResult(),
            ),
            patch(
                "atelier.commands.repair_event_history.beads.configured_beads_backend",
                return_value="dolt",
            ),
            patch(
                "atelier.commands.repair_event_history.beads.repair_issue_event_history_overflow",
                return_value=result,
            ),
        ):
            buffer = io.StringIO()
            with patch("sys.stdout", buffer):
                repair_cmd.repair_event_history_overflow(
                    SimpleNamespace(issue_id="at-overflow", format="table")
                )

    output = buffer.getvalue()
    assert "already mutable" in output
    assert "backend: dolt" in output
    assert "sqlite backup" not in output
    assert "bd history at-overflow" in output
    assert "bd restore at-overflow" in output

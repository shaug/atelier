from __future__ import annotations

import importlib
import io
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import atelier.config as config
from atelier.prefix_migration_drift import PrefixMigrationRepairAction
from tests.atelier.helpers import DummyResult

doctor_cmd = importlib.import_module("atelier.commands.doctor")


def test_doctor_json_check_mode() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        project_root = root / "project"
        repo_root = root / "repo"
        project_root.mkdir(parents=True, exist_ok=True)
        repo_root.mkdir(parents=True, exist_ok=True)
        project_config = config.ProjectConfig.model_validate(
            {"project": {"enlistment": str(repo_root), "origin": "github.com/org/repo"}}
        )
        actions = [
            PrefixMigrationRepairAction(
                epic_id="epic-1",
                changeset_id="epic-1.2",
                drift_classes=("work-branch-conflict",),
                canonical_root_branch="feat/root",
                canonical_work_branch="feat/new",
                work_branch_source="open-pr-head",
                canonical_worktree_path="worktrees/epic-1.2",
                worktree_path_source="mapping",
                pr_head_ref="feat/new",
                pr_lookup_branch="feat/old",
                update_workspace_root_branch=False,
                update_changeset_metadata=True,
                update_changeset_worktree_path=False,
                update_mapping=True,
                applied=False,
            )
        ]
        with (
            patch(
                "atelier.commands.doctor.resolve_current_project_with_repo_root",
                return_value=(project_root, project_config, str(repo_root), repo_root),
            ),
            patch("atelier.commands.doctor.beads.run_bd_command", return_value=DummyResult()),
            patch(
                "atelier.commands.doctor.prefix_migration_drift.repair_prefix_migration_drift",
                return_value=actions,
            ),
        ):
            buffer = io.StringIO()
            with patch("sys.stdout", buffer):
                doctor_cmd.doctor(SimpleNamespace(format="json", fix=False))

    payload = json.loads(buffer.getvalue())
    assert payload["mode"] == "check"
    assert payload["fix"] is False
    assert payload["counts"]["changesets_drifted"] == 1
    assert payload["counts"]["changesets_changed"] == 1
    assert payload["counts"]["changesets_applied"] == 0


def test_doctor_json_fix_mode_reports_applied() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        project_root = root / "project"
        repo_root = root / "repo"
        project_root.mkdir(parents=True, exist_ok=True)
        repo_root.mkdir(parents=True, exist_ok=True)
        project_config = config.ProjectConfig.model_validate(
            {"project": {"enlistment": str(repo_root), "origin": "github.com/org/repo"}}
        )
        actions = [
            PrefixMigrationRepairAction(
                epic_id="epic-1",
                changeset_id="epic-1.2",
                drift_classes=("work-branch-conflict", "worktree-path-conflict"),
                canonical_root_branch="feat/root",
                canonical_work_branch="feat/new",
                work_branch_source="open-pr-head",
                canonical_worktree_path="worktrees/epic-1.2",
                worktree_path_source="mapping",
                pr_head_ref="feat/new",
                pr_lookup_branch="feat/old",
                update_workspace_root_branch=True,
                update_changeset_metadata=True,
                update_changeset_worktree_path=True,
                update_mapping=True,
                applied=True,
            )
        ]
        with (
            patch(
                "atelier.commands.doctor.resolve_current_project_with_repo_root",
                return_value=(project_root, project_config, str(repo_root), repo_root),
            ),
            patch("atelier.commands.doctor.beads.run_bd_command", return_value=DummyResult()),
            patch("atelier.commands.doctor._active_agent_hook_blockers", return_value=[]),
            patch(
                "atelier.commands.doctor.prefix_migration_drift.repair_prefix_migration_drift",
                return_value=actions,
            ),
        ):
            buffer = io.StringIO()
            with patch("sys.stdout", buffer):
                doctor_cmd.doctor(SimpleNamespace(format="json", fix=True))

    payload = json.loads(buffer.getvalue())
    assert payload["mode"] == "fix"
    assert payload["fix"] is True
    assert payload["counts"]["changesets_drifted"] == 1
    assert payload["counts"]["changesets_changed"] == 1
    assert payload["counts"]["changesets_applied"] == 1


def test_doctor_fix_mode_blocks_when_active_hooks_exist() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        project_root = root / "project"
        repo_root = root / "repo"
        project_root.mkdir(parents=True, exist_ok=True)
        repo_root.mkdir(parents=True, exist_ok=True)
        project_config = config.ProjectConfig.model_validate(
            {"project": {"enlistment": str(repo_root), "origin": "github.com/org/repo"}}
        )
        blockers = [
            doctor_cmd._ActiveHookBlocker(
                agent_id="atelier/worker/codex/p123-t123",
                hook_bead="at-epic",
                session_state="live",
                heartbeat_at="2026-03-04T01:02:03Z",
            )
        ]
        with (
            patch(
                "atelier.commands.doctor.resolve_current_project_with_repo_root",
                return_value=(project_root, project_config, str(repo_root), repo_root),
            ),
            patch("atelier.commands.doctor.beads.run_bd_command", return_value=DummyResult()),
            patch("atelier.commands.doctor._active_agent_hook_blockers", return_value=blockers),
            patch(
                "atelier.commands.doctor.prefix_migration_drift.repair_prefix_migration_drift"
            ) as repair,
        ):
            with pytest.raises(SystemExit) as raised:
                doctor_cmd.doctor(SimpleNamespace(format="json", fix=True, force=False))

    assert "active agent hooks detected" in str(raised.value)
    repair.assert_not_called()


def test_doctor_fix_mode_force_bypasses_active_hook_gate() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        project_root = root / "project"
        repo_root = root / "repo"
        project_root.mkdir(parents=True, exist_ok=True)
        repo_root.mkdir(parents=True, exist_ok=True)
        project_config = config.ProjectConfig.model_validate(
            {"project": {"enlistment": str(repo_root), "origin": "github.com/org/repo"}}
        )
        blockers = [
            doctor_cmd._ActiveHookBlocker(
                agent_id="atelier/worker/codex/p123-t123",
                hook_bead="at-epic",
                session_state="live",
                heartbeat_at="2026-03-04T01:02:03Z",
            )
        ]
        with (
            patch(
                "atelier.commands.doctor.resolve_current_project_with_repo_root",
                return_value=(project_root, project_config, str(repo_root), repo_root),
            ),
            patch("atelier.commands.doctor.beads.run_bd_command", return_value=DummyResult()),
            patch("atelier.commands.doctor._active_agent_hook_blockers", return_value=blockers),
            patch(
                "atelier.commands.doctor.prefix_migration_drift.repair_prefix_migration_drift",
                return_value=[],
            ) as repair,
        ):
            buffer = io.StringIO()
            with patch("sys.stdout", buffer):
                doctor_cmd.doctor(SimpleNamespace(format="json", fix=True, force=True))

    payload = json.loads(buffer.getvalue())
    assert payload["mode"] == "fix"
    assert payload["fix"] is True
    repair.assert_called_once()

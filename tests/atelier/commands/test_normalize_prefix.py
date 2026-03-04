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

normalize_prefix_cmd = importlib.import_module("atelier.commands.normalize_prefix")


def test_normalize_prefix_json_dry_run_reports_actions_and_guidance() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        project_root = root / "project"
        repo_root = root / "repo"
        project_root.mkdir(parents=True, exist_ok=True)
        repo_root.mkdir(parents=True, exist_ok=True)
        project_config = config.ProjectConfig.model_validate(
            {
                "project": {"enlistment": str(repo_root), "origin": "github.com/org/repo"},
                "beads": {"prefix": "ts"},
            }
        )
        actions = [
            PrefixMigrationRepairAction(
                epic_id="ts-epic",
                changeset_id="ts-epic.1",
                drift_classes=("work-branch-conflict", "worktree-path-conflict"),
                canonical_root_branch="feat/ts-root",
                canonical_work_branch="feat/ts-head",
                work_branch_source="open-pr-head",
                canonical_worktree_path="worktrees/ts-epic.1",
                worktree_path_source="filesystem-metadata-branch",
                pr_head_ref="feat/ts-head",
                pr_lookup_branch="feat/legacy-head",
                update_workspace_root_branch=False,
                update_changeset_metadata=True,
                update_changeset_worktree_path=True,
                update_mapping=True,
                applied=False,
            )
        ]
        with (
            patch(
                "atelier.commands.normalize_prefix.resolve_current_project_with_repo_root",
                return_value=(project_root, project_config, str(repo_root), repo_root),
            ),
            patch(
                "atelier.commands.normalize_prefix.beads.run_bd_command", return_value=DummyResult()
            ),
            patch(
                "atelier.commands.normalize_prefix.prefix_migration_drift.repair_prefix_migration_drift",
                return_value=actions,
            ),
        ):
            buffer = io.StringIO()
            with patch("sys.stdout", buffer):
                normalize_prefix_cmd.normalize_prefix(
                    SimpleNamespace(format="json", apply=False, force=False)
                )

    payload = json.loads(buffer.getvalue())
    assert payload["mode"] == "dry-run"
    assert payload["apply"] is False
    assert payload["project"]["configured_prefix"] == "ts"
    assert payload["counts"] == {
        "changesets_applied": 0,
        "changesets_changed": 1,
        "changesets_drifted": 1,
    }
    assert "BEADS_DIR" in payload["rollback_guidance"]["beads_export"]
    assert ".meta.backup-" in payload["rollback_guidance"]["mapping_backup"]
    assert len(payload["actions"]) == 1


def test_normalize_prefix_apply_blocks_when_active_hooks_exist() -> None:
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
            normalize_prefix_cmd._ActiveHookBlocker(
                agent_id="worker-a",
                hook_bead="ts-epic",
                session_state="live",
                heartbeat_at="2026-03-03T05:00:00Z",
            )
        ]
        with (
            patch(
                "atelier.commands.normalize_prefix.resolve_current_project_with_repo_root",
                return_value=(project_root, project_config, str(repo_root), repo_root),
            ),
            patch(
                "atelier.commands.normalize_prefix.beads.run_bd_command", return_value=DummyResult()
            ),
            patch(
                "atelier.commands.normalize_prefix._active_agent_hook_blockers",
                return_value=blockers,
            ),
            patch(
                "atelier.commands.normalize_prefix.prefix_migration_drift.repair_prefix_migration_drift"
            ) as repair,
        ):
            with pytest.raises(SystemExit) as exc_info:
                normalize_prefix_cmd.normalize_prefix(
                    SimpleNamespace(format="json", apply=True, force=False)
                )

    detail = str(exc_info.value)
    assert "refusing `atelier normalize-prefix --apply`" in detail
    repair.assert_not_called()


def test_normalize_prefix_apply_force_bypasses_active_hook_gate() -> None:
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
                epic_id="ts-epic",
                changeset_id="ts-epic.1",
                drift_classes=("work-branch-conflict",),
                canonical_root_branch="feat/ts-root",
                canonical_work_branch="feat/ts-head",
                work_branch_source="open-pr-head",
                canonical_worktree_path="worktrees/ts-epic.1",
                worktree_path_source="mapping",
                pr_head_ref="feat/ts-head",
                pr_lookup_branch="feat/legacy-head",
                update_workspace_root_branch=False,
                update_changeset_metadata=True,
                update_changeset_worktree_path=False,
                update_mapping=True,
                applied=True,
            )
        ]
        with (
            patch(
                "atelier.commands.normalize_prefix.resolve_current_project_with_repo_root",
                return_value=(project_root, project_config, str(repo_root), repo_root),
            ),
            patch(
                "atelier.commands.normalize_prefix.beads.run_bd_command", return_value=DummyResult()
            ),
            patch(
                "atelier.commands.normalize_prefix.prefix_migration_drift.repair_prefix_migration_drift",
                return_value=actions,
            ) as repair,
        ):
            buffer = io.StringIO()
            with patch("sys.stdout", buffer):
                normalize_prefix_cmd.normalize_prefix(
                    SimpleNamespace(format="json", apply=True, force=True)
                )

    payload = json.loads(buffer.getvalue())
    assert payload["mode"] == "apply"
    assert payload["apply"] is True
    assert payload["counts"]["changesets_applied"] == 1
    repair.assert_called_once()

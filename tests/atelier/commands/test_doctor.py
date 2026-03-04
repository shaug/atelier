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
from atelier.worktrees import WorktreeMapping
from tests.atelier.helpers import DummyResult

doctor_cmd = importlib.import_module("atelier.commands.doctor")


def _empty_context(project_data_dir: Path) -> object:
    return doctor_cmd._DoctorContext(
        project_data_dir=project_data_dir,
        epics_by_id={},
        changesets=[],
        changeset_to_epic={},
        fields_by_changeset={},
        mappings_by_epic={},
    )


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
            patch(
                "atelier.commands.doctor._collect_doctor_context",
                return_value=_empty_context(project_root),
            ),
            patch("atelier.commands.doctor._collect_agent_runtime", return_value=({}, {})),
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
    assert payload["counts"]["check_families"] == 3
    assert "startup_blocking_lineage_consistency" in payload["checks"]
    assert "in_progress_integrity_signals" in payload["checks"]


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
            patch(
                "atelier.commands.doctor._collect_doctor_context",
                return_value=_empty_context(project_root),
            ),
            patch("atelier.commands.doctor._collect_agent_runtime", return_value=({}, {})),
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


def test_doctor_json_includes_multi_check_health_report() -> None:
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
                changeset_id="epic-1.1",
                drift_classes=("work-branch-conflict", "worktree-path-conflict"),
                canonical_root_branch="root-one",
                canonical_work_branch="root-one-epic-1.1",
                work_branch_source="mapping",
                canonical_worktree_path="worktrees/epic-1.1",
                worktree_path_source="mapping",
                pr_head_ref=None,
                pr_lookup_branch="legacy-branch",
                update_workspace_root_branch=False,
                update_changeset_metadata=True,
                update_changeset_worktree_path=True,
                update_mapping=False,
                applied=False,
            )
        ]
        context = doctor_cmd._DoctorContext(
            project_data_dir=project_root,
            epics_by_id={
                "epic-1": {
                    "id": "epic-1",
                    "status": "in_progress",
                    "assignee": "worker-a",
                    "description": "workspace.root_branch: root-one\n",
                    "labels": ["at:epic"],
                }
            },
            changesets=[
                {
                    "id": "epic-1.1",
                    "status": "in_progress",
                    "description": "changeset.work_branch: legacy-branch\n",
                },
                {
                    "id": "epic-1.2",
                    "status": "blocked",
                    "description": "",
                },
                {
                    "id": "epic-1.3",
                    "status": "open",
                    "description": "",
                },
            ],
            changeset_to_epic={
                "epic-1.1": "epic-1",
                "epic-1.2": "epic-1",
                "epic-1.3": "epic-1",
            },
            fields_by_changeset={
                "epic-1.1": {
                    "changeset.root_branch": "root-one",
                    "changeset.parent_branch": "main",
                    "changeset.work_branch": "legacy-branch",
                    "worktree_path": "worktrees/epic-1.1-old",
                },
                "epic-1.2": {
                    "changeset.root_branch": "root-one",
                    "changeset.parent_branch": "main",
                    "changeset.work_branch": "root-one-epic-1.2",
                },
                "epic-1.3": {},
            },
            mappings_by_epic={
                "epic-1": WorktreeMapping(
                    epic_id="epic-1",
                    worktree_path="worktrees/epic-1",
                    root_branch="root-one",
                    changesets={
                        "epic-1.1": "root-one-epic-1.1",
                        "epic-1.2": "root-one-epic-1.2",
                        "epic-1.3": "root-one-epic-1.3",
                    },
                    changeset_worktrees={
                        "epic-1.1": "worktrees/epic-1.1",
                        "epic-1.2": "worktrees/epic-1.2",
                        "epic-1.3": "worktrees/epic-1.3",
                    },
                )
            },
        )
        agent_index = {
            "worker-a": doctor_cmd._AgentRuntime(
                agent_id="worker-a",
                hook_bead=None,
                session_state="stale",
                heartbeat_at="2026-03-01T00:00:00Z",
            )
        }
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
            patch("atelier.commands.doctor._collect_doctor_context", return_value=context),
            patch(
                "atelier.commands.doctor._collect_agent_runtime",
                return_value=({}, agent_index),
            ),
        ):
            buffer = io.StringIO()
            with patch("sys.stdout", buffer):
                doctor_cmd.doctor(SimpleNamespace(format="json", fix=False))

    payload = json.loads(buffer.getvalue())
    assert payload["mode"] == "check"
    assert payload["counts"]["check_families"] == 3
    assert payload["counts"]["check_families_with_findings"] == 3
    assert payload["counts"]["startup_blockers"] >= 1
    assert payload["counts"]["changesets_in_progress"] == 1
    assert payload["counts"]["changesets_blocked"] == 1
    checks = payload["checks"]
    assert "prefix_migration_drift" in checks
    assert "startup_blocking_lineage_consistency" in checks
    assert "in_progress_integrity_signals" in checks

    ownership_findings = checks["in_progress_integrity_signals"]["findings"]
    ownership_codes = {finding["code"] for finding in ownership_findings}
    assert "in-progress-epic-unhooked" in ownership_codes
    stale_finding = next(
        finding
        for finding in ownership_findings
        if finding["code"] == "in-progress-assignee-session-stale"
    )
    assert stale_finding["startup_blocker"] is False
    assert checks["in_progress_integrity_signals"]["counts"]["startup_blockers"] == 1

    readiness_findings = checks["startup_blocking_lineage_consistency"]["findings"]
    readiness_codes = {finding["code"] for finding in readiness_findings}
    assert "metadata-work-branch-conflict" in readiness_codes
    assert "metadata-worktree-path-conflict" in readiness_codes
    assert not any(
        finding.get("changeset_id") == "epic-1.3"
        and str(finding.get("code", "")).startswith("metadata-missing-")
        for finding in readiness_findings
    )


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
            patch(
                "atelier.commands.doctor._collect_doctor_context",
                return_value=_empty_context(project_root),
            ),
            patch("atelier.commands.doctor._collect_agent_runtime", return_value=({}, {})),
        ):
            buffer = io.StringIO()
            with patch("sys.stdout", buffer):
                doctor_cmd.doctor(SimpleNamespace(format="json", fix=True, force=True))

    payload = json.loads(buffer.getvalue())
    assert payload["mode"] == "fix"
    assert payload["fix"] is True
    repair.assert_called_once()

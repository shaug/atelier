"""Tests for gc command orchestration."""

import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import atelier.commands.gc as gc_cmd
import atelier.config as config
import atelier.worktrees as worktrees


def test_gc_reconcile_flag_runs_changeset_reconciliation() -> None:
    project_root = Path("/project")
    repo_root = Path("/repo")
    project_config = config.ProjectConfig()

    with (
        patch(
            "atelier.commands.gc.resolve_current_project_with_repo_root",
            return_value=(project_root, project_config, "/repo", repo_root),
        ),
        patch(
            "atelier.commands.gc.config.resolve_project_data_dir",
            return_value=Path("/data"),
        ),
        patch(
            "atelier.commands.gc.config.resolve_beads_root",
            return_value=Path("/beads"),
        ),
        patch("atelier.beads.run_bd_json", return_value=[]),
        patch(
            "atelier.commands.gc.work_cmd.list_reconcile_epic_candidates",
            return_value={"at-wjj": ["at-wjj.1"]},
        ),
        patch(
            "atelier.gc.reconcile.reconcile_preview_lines",
            return_value=("final integration: feat/root -> main",),
        ),
        patch(
            "atelier.commands.gc.work_cmd.reconcile_blocked_merged_changesets",
            return_value=gc_cmd.work_cmd.ReconcileResult(
                scanned=2, actionable=1, reconciled=1, failed=0
            ),
        ) as reconcile,
        patch("atelier.commands.gc.confirm") as confirm,
        patch("atelier.commands.gc.say") as say,
    ):
        gc_cmd.gc(
            SimpleNamespace(
                stale_hours=24.0,
                stale_if_missing_heartbeat=False,
                dry_run=False,
                reconcile=True,
                yes=True,
            )
        )

    reconcile.assert_called_once()
    confirm.assert_not_called()
    assert any(
        "Reconcile blocked changesets: scanned=2, actionable=1, reconciled=1, failed=0"
        in str(call.args[0])
        for call in say.call_args_list
    )


def test_gc_reconcile_flag_prompts_and_skips_without_confirmation() -> None:
    project_root = Path("/project")
    repo_root = Path("/repo")
    project_config = config.ProjectConfig()

    with (
        patch(
            "atelier.commands.gc.resolve_current_project_with_repo_root",
            return_value=(project_root, project_config, "/repo", repo_root),
        ),
        patch(
            "atelier.commands.gc.config.resolve_project_data_dir",
            return_value=Path("/data"),
        ),
        patch(
            "atelier.commands.gc.config.resolve_beads_root",
            return_value=Path("/beads"),
        ),
        patch("atelier.beads.run_bd_json", return_value=[]),
        patch(
            "atelier.commands.gc.work_cmd.list_reconcile_epic_candidates",
            return_value={"at-wjj": ["at-wjj.1", "at-wjj.2"]},
        ),
        patch(
            "atelier.gc.reconcile.reconcile_preview_lines",
            return_value=("final integration: feat/root -> main",),
        ),
        patch("atelier.commands.gc.work_cmd.reconcile_blocked_merged_changesets") as reconcile,
        patch("atelier.commands.gc.confirm", return_value=False) as confirm,
        patch("atelier.commands.gc.say") as say,
    ):
        gc_cmd.gc(
            SimpleNamespace(
                stale_hours=24.0,
                stale_if_missing_heartbeat=False,
                dry_run=False,
                reconcile=True,
                yes=False,
            )
        )

    confirm.assert_called_once_with(
        "Reconcile epic at-wjj (2 merged changesets: at-wjj.1, at-wjj.2)?",
        default=False,
    )
    reconcile.assert_not_called()
    assert any("Skipped reconcile: epic at-wjj" in str(call.args[0]) for call in say.call_args_list)


def test_gc_reconcile_flag_prompts_and_runs_with_confirmation() -> None:
    project_root = Path("/project")
    repo_root = Path("/repo")
    project_config = config.ProjectConfig()

    with (
        patch(
            "atelier.commands.gc.resolve_current_project_with_repo_root",
            return_value=(project_root, project_config, "/repo", repo_root),
        ),
        patch(
            "atelier.commands.gc.config.resolve_project_data_dir",
            return_value=Path("/data"),
        ),
        patch(
            "atelier.commands.gc.config.resolve_beads_root",
            return_value=Path("/beads"),
        ),
        patch("atelier.beads.run_bd_json", return_value=[]),
        patch(
            "atelier.commands.gc.work_cmd.list_reconcile_epic_candidates",
            return_value={"at-wjj": ["at-wjj.1", "at-wjj.2", "at-wjj.3", "at-wjj.4"]},
        ),
        patch(
            "atelier.gc.reconcile.reconcile_preview_lines",
            return_value=("final integration: feat/root -> main",),
        ),
        patch(
            "atelier.commands.gc.work_cmd.reconcile_blocked_merged_changesets",
            return_value=gc_cmd.work_cmd.ReconcileResult(
                scanned=1, actionable=1, reconciled=1, failed=0
            ),
        ) as reconcile,
        patch("atelier.commands.gc.confirm", return_value=True) as confirm,
        patch("atelier.commands.gc.say") as say,
    ):
        gc_cmd.gc(
            SimpleNamespace(
                stale_hours=24.0,
                stale_if_missing_heartbeat=False,
                dry_run=False,
                reconcile=True,
                yes=False,
            )
        )

    confirm.assert_called_once_with(
        "Reconcile epic at-wjj (4 merged changesets: at-wjj.1, at-wjj.2, at-wjj.3, +1 more)?",
        default=False,
    )
    reconcile.assert_called_once()
    assert reconcile.call_args.kwargs["epic_filter"] == "at-wjj"
    assert reconcile.call_args.kwargs["changeset_filter"] == {
        "at-wjj.1",
        "at-wjj.2",
        "at-wjj.3",
        "at-wjj.4",
    }
    assert any(
        "Reconcile blocked changesets: scanned=1, actionable=1, reconciled=1, failed=0"
        in str(call.args[0])
        for call in say.call_args_list
    )


def test_gc_reconcile_flag_no_candidates_skips_prompts() -> None:
    project_root = Path("/project")
    repo_root = Path("/repo")
    project_config = config.ProjectConfig()

    with (
        patch(
            "atelier.commands.gc.resolve_current_project_with_repo_root",
            return_value=(project_root, project_config, "/repo", repo_root),
        ),
        patch(
            "atelier.commands.gc.config.resolve_project_data_dir",
            return_value=Path("/data"),
        ),
        patch(
            "atelier.commands.gc.config.resolve_beads_root",
            return_value=Path("/beads"),
        ),
        patch("atelier.beads.run_bd_json", return_value=[]),
        patch(
            "atelier.commands.gc.work_cmd.list_reconcile_epic_candidates",
            return_value={},
        ),
        patch("atelier.commands.gc.work_cmd.reconcile_blocked_merged_changesets") as reconcile,
        patch("atelier.commands.gc.confirm") as confirm,
        patch("atelier.commands.gc.say") as say,
    ):
        gc_cmd.gc(
            SimpleNamespace(
                stale_hours=24.0,
                stale_if_missing_heartbeat=False,
                dry_run=False,
                reconcile=True,
                yes=False,
            )
        )

    reconcile.assert_not_called()
    confirm.assert_not_called()
    assert any("No reconcile candidates." in str(call.args[0]) for call in say.call_args_list)


def test_gc_orphan_worktree_dirty_prompts_force_or_exit() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        project_root = root / "project"
        repo_root = root / "repo"
        data_dir = root / "data"
        project_root.mkdir(parents=True, exist_ok=True)
        repo_root.mkdir(parents=True, exist_ok=True)
        mapping_path = worktrees.mapping_path(data_dir, "orphan-epic")
        mapping_path.parent.mkdir(parents=True, exist_ok=True)
        worktrees.write_mapping(
            mapping_path,
            worktrees.WorktreeMapping(
                epic_id="orphan-epic",
                worktree_path="worktrees/orphan-epic",
                root_branch="feat/orphan",
                changesets={},
                changeset_worktrees={},
            ),
        )
        orphan_path = data_dir / "worktrees" / "orphan-epic"
        orphan_path.mkdir(parents=True, exist_ok=True)
        (orphan_path / ".git").write_text("gitdir: /tmp/gitdir", encoding="utf-8")
        project_config = config.ProjectConfig()

        with (
            patch(
                "atelier.commands.gc.resolve_current_project_with_repo_root",
                return_value=(project_root, project_config, "/repo", repo_root),
            ),
            patch(
                "atelier.commands.gc.config.resolve_project_data_dir",
                return_value=data_dir,
            ),
            patch(
                "atelier.commands.gc.config.resolve_beads_root",
                return_value=Path("/beads"),
            ),
            patch("atelier.beads.run_bd_json", return_value=[]),
            patch("atelier.gc.worktrees.try_show_issue", return_value=None),
            patch(
                "atelier.git.git_status_porcelain",
                return_value=[" M foo.py", "?? bar.txt"],
            ),
            patch("atelier.worktrees.remove_git_worktree") as remove_worktree,
            patch("atelier.commands.gc.confirm", return_value=True),
            patch("atelier.gc.worktrees.select", return_value="exit"),
            patch("atelier.commands.gc.say"),
        ):
            with pytest.raises(SystemExit):
                gc_cmd.gc(
                    SimpleNamespace(
                        stale_hours=24.0,
                        stale_if_missing_heartbeat=False,
                        dry_run=False,
                        reconcile=False,
                        yes=False,
                    )
                )

        remove_worktree.assert_not_called()


def test_gc_orphan_worktree_dirty_force_remove_calls_force() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        project_root = root / "project"
        repo_root = root / "repo"
        data_dir = root / "data"
        project_root.mkdir(parents=True, exist_ok=True)
        repo_root.mkdir(parents=True, exist_ok=True)
        mapping_path = worktrees.mapping_path(data_dir, "orphan-epic")
        mapping_path.parent.mkdir(parents=True, exist_ok=True)
        worktrees.write_mapping(
            mapping_path,
            worktrees.WorktreeMapping(
                epic_id="orphan-epic",
                worktree_path="worktrees/orphan-epic",
                root_branch="feat/orphan",
                changesets={},
                changeset_worktrees={},
            ),
        )
        orphan_path = data_dir / "worktrees" / "orphan-epic"
        orphan_path.mkdir(parents=True, exist_ok=True)
        (orphan_path / ".git").write_text("gitdir: /tmp/gitdir", encoding="utf-8")
        project_config = config.ProjectConfig()

        with (
            patch(
                "atelier.commands.gc.resolve_current_project_with_repo_root",
                return_value=(project_root, project_config, "/repo", repo_root),
            ),
            patch(
                "atelier.commands.gc.config.resolve_project_data_dir",
                return_value=data_dir,
            ),
            patch(
                "atelier.commands.gc.config.resolve_beads_root",
                return_value=Path("/beads"),
            ),
            patch("atelier.beads.run_bd_json", return_value=[]),
            patch("atelier.gc.worktrees.try_show_issue", return_value=None),
            patch(
                "atelier.git.git_status_porcelain",
                return_value=[" M foo.py"],
            ),
            patch("atelier.worktrees.remove_git_worktree") as remove_worktree,
            patch("atelier.commands.gc.confirm", return_value=True),
            patch("atelier.gc.worktrees.select", return_value="force-remove"),
            patch("atelier.commands.gc.say"),
        ):
            gc_cmd.gc(
                SimpleNamespace(
                    stale_hours=24.0,
                    stale_if_missing_heartbeat=False,
                    dry_run=False,
                    reconcile=False,
                    yes=False,
                )
            )

        remove_worktree.assert_called_once_with(
            data_dir,
            repo_root,
            "orphan-epic",
            git_path="git",
            force=True,
        )


def test_gc_logs_action_lifecycle_in_dry_run() -> None:
    project_root = Path("/project")
    repo_root = Path("/repo")
    project_config = config.ProjectConfig()
    action = gc_cmd.GcAction(description="Test action", apply=lambda: None)

    with (
        patch(
            "atelier.commands.gc.resolve_current_project_with_repo_root",
            return_value=(project_root, project_config, "/repo", repo_root),
        ),
        patch(
            "atelier.commands.gc.config.resolve_project_data_dir",
            return_value=Path("/data"),
        ),
        patch(
            "atelier.commands.gc.config.resolve_beads_root",
            return_value=Path("/beads"),
        ),
        patch(
            "atelier.gc.labels.collect_normalize_changeset_labels",
            return_value=[],
        ),
        patch(
            "atelier.gc.labels.collect_remove_deprecated_label",
            return_value=[],
        ),
        patch(
            "atelier.gc.labels.collect_normalize_epic_labels",
            return_value=[],
        ),
        patch("atelier.gc.hooks.collect_hooks", return_value=[]),
        patch("atelier.gc.worktrees.collect_orphan_worktrees", return_value=[]),
        patch(
            "atelier.gc.worktrees.collect_resolved_epic_artifacts",
            return_value=[],
        ),
        patch(
            "atelier.gc.worktrees.collect_closed_workspace_branches_without_mapping",
            return_value=[],
        ),
        patch("atelier.gc.messages.collect_message_claims", return_value=[]),
        patch(
            "atelier.gc.messages.collect_message_retention",
            return_value=[action],
        ),
        patch("atelier.gc.agents.collect_agent_homes", return_value=[]),
        patch("atelier.commands.gc.say"),
        patch("atelier.commands.gc.log_debug") as log_debug,
    ):
        gc_cmd.gc(
            SimpleNamespace(
                stale_hours=24.0,
                stale_if_missing_heartbeat=False,
                dry_run=True,
                reconcile=False,
                yes=False,
            )
        )

    debug_messages = [str(call.args[0]) for call in log_debug.call_args_list]
    assert any("gc start" in message for message in debug_messages)
    assert any("gc action queued description=Test action" in message for message in debug_messages)
    assert any("gc action dry-run description=Test action" in message for message in debug_messages)

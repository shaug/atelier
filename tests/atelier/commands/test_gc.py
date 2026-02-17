import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import atelier.beads as beads
import atelier.commands.gc as gc_cmd
import atelier.config as config
import atelier.worktrees as worktrees
from atelier.messages import render_message


def test_gc_closes_expired_channel_messages() -> None:
    project_root = Path("/project")
    repo_root = Path("/repo")
    project_config = config.ProjectConfig()
    description = render_message(
        {"channel": "ops", "retention_days": 1},
        "hello",
    )
    issue = {
        "id": "msg-1",
        "description": description,
        "created_at": "2026-01-01T00:00:00Z",
    }

    calls: list[list[str]] = []

    def fake_run_bd_json(
        args: list[str], *, beads_root: Path, cwd: Path
    ) -> list[dict[str, object]]:
        if args[:3] == ["list", "--label", "at:message"]:
            return [issue]
        return []

    def fake_run_bd_command(
        args: list[str], *, beads_root: Path, cwd: Path, allow_failure: bool = False
    ) -> object:
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

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
        patch("atelier.commands.gc.beads.run_bd_json", side_effect=fake_run_bd_json),
        patch(
            "atelier.commands.gc.beads.run_bd_command", side_effect=fake_run_bd_command
        ),
        patch("atelier.commands.gc.say"),
    ):
        gc_cmd.gc(SimpleNamespace(stale_hours=24.0, dry_run=False, yes=True))

    assert any(cmd[:2] == ["close", "msg-1"] for cmd in calls)


def test_gc_removes_stale_session_agent_home() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        project_root = root / "project"
        repo_root = root / "repo"
        data_dir = root / "data"
        project_root.mkdir(parents=True, exist_ok=True)
        repo_root.mkdir(parents=True, exist_ok=True)
        stale_home = data_dir / "agents" / "worker" / "codex" / "p4242-t1"
        stale_home.mkdir(parents=True, exist_ok=True)
        (stale_home / "AGENTS.md").write_text("x", encoding="utf-8")
        project_config = config.ProjectConfig()
        agent_issue = {
            "id": "agent-1",
            "title": "atelier/worker/codex/p4242-t1",
            "labels": ["at:agent"],
            "description": "agent_id: atelier/worker/codex/p4242-t1\nrole_type: worker\n",
        }

        def fake_run_bd_json(
            args: list[str], *, beads_root: Path, cwd: Path
        ) -> list[dict[str, object]]:
            if args[:3] == ["list", "--label", "at:agent"]:
                return [agent_issue]
            if args[:3] == ["list", "--label", "at:epic"]:
                return []
            if args[:3] == ["list", "--label", "at:message"]:
                return []
            return []

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
            patch(
                "atelier.commands.gc.beads.run_bd_json", side_effect=fake_run_bd_json
            ),
            patch("atelier.commands.gc.beads.run_bd_command"),
            patch("atelier.commands.gc.beads.get_agent_hook", return_value=None),
            patch(
                "atelier.commands.gc.agent_home.is_session_agent_active",
                return_value=False,
            ),
            patch("atelier.commands.gc.say"),
        ):
            gc_cmd.gc(SimpleNamespace(stale_hours=24.0, dry_run=False, yes=True))

        assert not stale_home.exists()


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
        patch("atelier.commands.gc.beads.run_bd_json", return_value=[]),
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
        patch("atelier.commands.gc.beads.run_bd_json", return_value=[]),
        patch(
            "atelier.commands.gc.work_cmd.list_reconcile_epic_candidates",
            return_value={"at-wjj": ["at-wjj.1", "at-wjj.2"]},
        ),
        patch(
            "atelier.commands.gc.work_cmd.reconcile_blocked_merged_changesets"
        ) as reconcile,
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
    assert any(
        "Skipped reconcile: epic at-wjj" in str(call.args[0])
        for call in say.call_args_list
    )


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
        patch("atelier.commands.gc.beads.run_bd_json", return_value=[]),
        patch(
            "atelier.commands.gc.work_cmd.list_reconcile_epic_candidates",
            return_value={"at-wjj": ["at-wjj.1", "at-wjj.2", "at-wjj.3", "at-wjj.4"]},
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
        patch("atelier.commands.gc.beads.run_bd_json", return_value=[]),
        patch(
            "atelier.commands.gc.work_cmd.list_reconcile_epic_candidates",
            return_value={},
        ),
        patch(
            "atelier.commands.gc.work_cmd.reconcile_blocked_merged_changesets"
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
                yes=False,
            )
        )

    reconcile.assert_not_called()
    confirm.assert_not_called()
    assert any(
        "No reconcile candidates." in str(call.args[0]) for call in say.call_args_list
    )


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
            patch("atelier.commands.gc.beads.run_bd_json", return_value=[]),
            patch("atelier.commands.gc._try_show_issue", return_value=None),
            patch(
                "atelier.commands.gc.git.git_status_porcelain",
                return_value=[" M foo.py", "?? bar.txt"],
            ),
            patch(
                "atelier.commands.gc.worktrees.remove_git_worktree"
            ) as remove_worktree,
            patch("atelier.commands.gc.confirm", return_value=True),
            patch("atelier.commands.gc.select", return_value="exit"),
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
            patch("atelier.commands.gc.beads.run_bd_json", return_value=[]),
            patch("atelier.commands.gc._try_show_issue", return_value=None),
            patch(
                "atelier.commands.gc.git.git_status_porcelain",
                return_value=[" M foo.py"],
            ),
            patch(
                "atelier.commands.gc.worktrees.remove_git_worktree"
            ) as remove_worktree,
            patch("atelier.commands.gc.confirm", return_value=True),
            patch("atelier.commands.gc.select", return_value="force-remove"),
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


def test_gc_resolved_epic_artifacts_prunes_worktrees_and_branches() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        project_dir = root / "data"
        repo_root = root / "repo"
        project_dir.mkdir(parents=True, exist_ok=True)
        repo_root.mkdir(parents=True, exist_ok=True)
        epic_id = "at-epic"
        mapping_path = worktrees.mapping_path(project_dir, epic_id)
        mapping_path.parent.mkdir(parents=True, exist_ok=True)
        worktrees.write_mapping(
            mapping_path,
            worktrees.WorktreeMapping(
                epic_id=epic_id,
                worktree_path=f"worktrees/{epic_id}",
                root_branch="feat/root",
                changesets={"at-epic.1": "feat/root-at-epic.1"},
                changeset_worktrees={"at-epic.1": "worktrees/at-epic.1"},
            ),
        )
        epic_worktree = project_dir / "worktrees" / epic_id
        changeset_worktree = project_dir / "worktrees" / "at-epic.1"
        epic_worktree.mkdir(parents=True, exist_ok=True)
        changeset_worktree.mkdir(parents=True, exist_ok=True)
        (epic_worktree / ".git").write_text("gitdir: /tmp/a", encoding="utf-8")
        (changeset_worktree / ".git").write_text("gitdir: /tmp/b", encoding="utf-8")
        epic_issue = {
            "id": epic_id,
            "status": "closed",
            "labels": ["at:epic"],
            "description": "workspace.parent_branch: main\n",
        }
        refs = {
            "refs/heads/main",
            "refs/remotes/origin/main",
            "refs/heads/feat/root",
            "refs/remotes/origin/feat/root",
            "refs/heads/feat/root-at-epic.1",
            "refs/remotes/origin/feat/root-at-epic.1",
        }
        commands: list[list[str]] = []

        with (
            patch("atelier.commands.gc._try_show_issue", return_value=epic_issue),
            patch(
                "atelier.commands.gc.beads.epic_changeset_summary",
                return_value=beads.ChangesetSummary(
                    total=1, ready=0, merged=1, abandoned=0, remaining=0
                ),
            ),
            patch("atelier.commands.gc.git.git_default_branch", return_value="main"),
            patch(
                "atelier.commands.gc.git.git_ref_exists",
                side_effect=lambda repo, ref, git_path=None: ref in refs,
            ),
            patch("atelier.commands.gc.git.git_is_ancestor", return_value=True),
            patch(
                "atelier.commands.gc.git.git_branch_fully_applied", return_value=False
            ),
            patch("atelier.commands.gc.git.git_status_porcelain", return_value=[]),
            patch("atelier.commands.gc.git.git_current_branch", return_value="main"),
            patch(
                "atelier.commands.gc._run_git_gc_command",
                side_effect=lambda args, repo_root, git_path: (
                    commands.append(args),
                    (True, ""),
                )[1],
            ),
        ):
            actions = gc_cmd._gc_resolved_epic_artifacts(
                project_dir=project_dir,
                beads_root=Path("/beads"),
                repo_root=repo_root,
                git_path="git",
                assume_yes=False,
            )
            assert len(actions) == 1
            actions[0].apply()

        assert ["worktree", "remove", str(epic_worktree)] in commands
        assert ["worktree", "remove", str(changeset_worktree)] in commands
        assert ["push", "origin", "--delete", "feat/root"] in commands
        assert ["push", "origin", "--delete", "feat/root-at-epic.1"] in commands
        assert ["branch", "-D", "feat/root"] in commands
        assert ["branch", "-D", "feat/root-at-epic.1"] in commands
        assert not mapping_path.exists()


def test_gc_resolved_epic_artifacts_skips_when_not_integrated() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        project_dir = root / "data"
        repo_root = root / "repo"
        project_dir.mkdir(parents=True, exist_ok=True)
        repo_root.mkdir(parents=True, exist_ok=True)
        epic_id = "at-epic"
        mapping_path = worktrees.mapping_path(project_dir, epic_id)
        mapping_path.parent.mkdir(parents=True, exist_ok=True)
        worktrees.write_mapping(
            mapping_path,
            worktrees.WorktreeMapping(
                epic_id=epic_id,
                worktree_path=f"worktrees/{epic_id}",
                root_branch="feat/root",
                changesets={},
                changeset_worktrees={},
            ),
        )
        epic_worktree = project_dir / "worktrees" / epic_id
        epic_worktree.mkdir(parents=True, exist_ok=True)
        (epic_worktree / ".git").write_text("gitdir: /tmp/a", encoding="utf-8")
        epic_issue = {
            "id": epic_id,
            "status": "closed",
            "labels": ["at:epic"],
            "description": "workspace.parent_branch: main\n",
        }
        refs = {
            "refs/heads/main",
            "refs/remotes/origin/main",
            "refs/heads/feat/root",
            "refs/remotes/origin/feat/root",
        }

        with (
            patch("atelier.commands.gc._try_show_issue", return_value=epic_issue),
            patch(
                "atelier.commands.gc.beads.epic_changeset_summary",
                return_value=beads.ChangesetSummary(
                    total=1, ready=0, merged=1, abandoned=0, remaining=0
                ),
            ),
            patch("atelier.commands.gc.git.git_default_branch", return_value="main"),
            patch(
                "atelier.commands.gc.git.git_ref_exists",
                side_effect=lambda repo, ref, git_path=None: ref in refs,
            ),
            patch("atelier.commands.gc.git.git_is_ancestor", return_value=False),
            patch(
                "atelier.commands.gc.git.git_branch_fully_applied", return_value=False
            ),
        ):
            actions = gc_cmd._gc_resolved_epic_artifacts(
                project_dir=project_dir,
                beads_root=Path("/beads"),
                repo_root=repo_root,
                git_path="git",
                assume_yes=False,
            )

        assert actions == []

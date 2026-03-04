from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import atelier.beads as beads
import atelier.prefix_migration_drift as prefix_migration_drift
import atelier.worktrees as worktrees


def _git_worktree_output(path: Path, branch: str) -> str:
    return (
        f"worktree {path}\n"
        "HEAD 0123456789abcdef0123456789abcdef01234567\n"
        f"branch refs/heads/{branch}\n\n"
    )


def test_scan_prefix_migration_drift_reports_conflicts_deterministically(tmp_path: Path) -> None:
    project_data_dir = tmp_path / "data"
    repo_root = tmp_path / "repo"
    project_data_dir.mkdir(parents=True)
    repo_root.mkdir(parents=True)
    worktrees.write_mapping(
        worktrees.mapping_path(project_data_dir, "ts-epic"),
        worktrees.WorktreeMapping(
            epic_id="ts-epic",
            worktree_path="worktrees/ts-epic",
            root_branch="feat/new-root",
            changesets={"ts-epic.1": "feat/legacy-branch"},
            changeset_worktrees={"ts-epic.1": "worktrees/at-legacy.1"},
        ),
    )

    epic_issue = {
        "id": "ts-epic",
        "labels": ["at:epic"],
        "description": "workspace.root_branch: feat/new-root\n",
    }
    changeset_issue = {
        "id": "ts-epic.1",
        "labels": [],
        "type": "task",
        "description": (
            "changeset.root_branch: feat/new-root\nchangeset.work_branch: feat/new-branch\n"
        ),
    }
    worktree_output = _git_worktree_output(
        project_data_dir / "worktrees" / "ts-epic.1",
        "feat/new-branch",
    )

    def fake_lookup(repo: str, branch: str) -> SimpleNamespace:
        assert repo == "org/repo"
        if branch == "feat/legacy-branch":
            return SimpleNamespace(
                found=True,
                failed=False,
                payload={"headRefName": "feat/pr-head"},
            )
        return SimpleNamespace(found=False, failed=False, payload=None)

    with (
        patch("atelier.prefix_migration_drift.beads.list_epics", return_value=[epic_issue]),
        patch(
            "atelier.prefix_migration_drift.beads.list_descendant_changesets",
            return_value=[changeset_issue],
        ),
        patch("atelier.prefix_migration_drift.beads.list_work_children", return_value=[]),
        patch(
            "atelier.prefix_migration_drift.exec_util.try_run_command",
            return_value=subprocess.CompletedProcess(
                args=["git", "worktree", "list", "--porcelain"],
                returncode=0,
                stdout=worktree_output,
                stderr="",
            ),
        ),
    ):
        first = prefix_migration_drift.scan_prefix_migration_drift(
            project_data_dir=project_data_dir,
            beads_root=tmp_path / ".beads",
            repo_root=repo_root,
            repo_slug="org/repo",
            lookup_pr_status=fake_lookup,
        )
        second = prefix_migration_drift.scan_prefix_migration_drift(
            project_data_dir=project_data_dir,
            beads_root=tmp_path / ".beads",
            repo_root=repo_root,
            repo_slug="org/repo",
            lookup_pr_status=fake_lookup,
        )

    assert first == second
    assert [record["drift_class"] for record in first] == [
        "work-branch-conflict",
        "worktree-path-conflict",
    ]
    branch_conflict = first[0]
    assert branch_conflict["changeset_id"] == "ts-epic.1"
    assert branch_conflict["values"]["metadata.changeset.work_branch"] == "feat/new-branch"
    assert branch_conflict["values"]["mapping.work_branch"] == "feat/legacy-branch"
    assert branch_conflict["values"]["pr.head_ref"] == "feat/pr-head"
    assert branch_conflict["values"]["filesystem.worktree_branch"] is None
    assert "(unset)" not in branch_conflict["values"].values()
    path_conflict = first[1]
    assert path_conflict["values"]["mapping.worktree_path"] == "worktrees/at-legacy.1"
    assert path_conflict["values"]["filesystem.path_for_metadata_branch"] == "worktrees/ts-epic.1"


def test_scan_prefix_migration_drift_returns_empty_when_metadata_mapping_and_worktree_align(
    tmp_path: Path,
) -> None:
    project_data_dir = tmp_path / "data"
    repo_root = tmp_path / "repo"
    project_data_dir.mkdir(parents=True)
    repo_root.mkdir(parents=True)
    worktrees.write_mapping(
        worktrees.mapping_path(project_data_dir, "ts-epic"),
        worktrees.WorktreeMapping(
            epic_id="ts-epic",
            worktree_path="worktrees/ts-epic",
            root_branch="feat/new-root",
            changesets={"ts-epic.1": "feat/new-branch"},
            changeset_worktrees={"ts-epic.1": "worktrees/ts-epic.1"},
        ),
    )

    epic_issue = {
        "id": "ts-epic",
        "labels": ["at:epic"],
        "description": "workspace.root_branch: feat/new-root\n",
    }
    changeset_issue = {
        "id": "ts-epic.1",
        "labels": [],
        "type": "task",
        "description": (
            "changeset.root_branch: feat/new-root\nchangeset.work_branch: feat/new-branch\n"
        ),
    }
    worktree_output = _git_worktree_output(
        project_data_dir / "worktrees" / "ts-epic.1",
        "feat/new-branch",
    )
    lookup_calls: list[tuple[str, str]] = []

    def fake_lookup(repo: str, branch: str) -> SimpleNamespace:
        lookup_calls.append((repo, branch))
        return SimpleNamespace(found=False, failed=False, payload=None)

    with (
        patch("atelier.prefix_migration_drift.beads.list_epics", return_value=[epic_issue]),
        patch(
            "atelier.prefix_migration_drift.beads.list_descendant_changesets",
            return_value=[changeset_issue],
        ),
        patch("atelier.prefix_migration_drift.beads.list_work_children", return_value=[]),
        patch(
            "atelier.prefix_migration_drift.exec_util.try_run_command",
            return_value=subprocess.CompletedProcess(
                args=["git", "worktree", "list", "--porcelain"],
                returncode=0,
                stdout=worktree_output,
                stderr="",
            ),
        ),
    ):
        records = prefix_migration_drift.scan_prefix_migration_drift(
            project_data_dir=project_data_dir,
            beads_root=tmp_path / ".beads",
            repo_root=repo_root,
            repo_slug="org/repo",
            lookup_pr_status=fake_lookup,
        )

    assert records == []
    assert lookup_calls == []


def test_scan_prefix_migration_drift_scopes_to_selected_epic_and_changesets(
    tmp_path: Path,
) -> None:
    project_data_dir = tmp_path / "data"
    repo_root = tmp_path / "repo"
    project_data_dir.mkdir(parents=True)
    repo_root.mkdir(parents=True)
    worktrees.write_mapping(
        worktrees.mapping_path(project_data_dir, "ts-epic"),
        worktrees.WorktreeMapping(
            epic_id="ts-epic",
            worktree_path="worktrees/ts-epic",
            root_branch="feat/new-root",
            changesets={"ts-epic.1": "feat/new-branch"},
            changeset_worktrees={"ts-epic.1": "worktrees/ts-epic.1"},
        ),
    )
    epic_issue = {
        "id": "ts-epic",
        "labels": ["at:epic"],
        "description": "workspace.root_branch: feat/new-root\n",
    }
    changeset_issue = {
        "id": "ts-epic.1",
        "labels": [],
        "type": "task",
        "description": (
            "changeset.root_branch: feat/new-root\nchangeset.work_branch: feat/new-branch\n"
        ),
    }
    worktree_output = _git_worktree_output(
        project_data_dir / "worktrees" / "ts-epic.1",
        "feat/new-branch",
    )
    list_epics = Mock()
    list_descendants = Mock()
    list_work_children = Mock()

    def fake_show(
        args: list[str],
        *,
        beads_root: Path,
        cwd: Path,
    ) -> list[dict[str, object]]:
        del beads_root, cwd
        if args == ["show", "ts-epic"]:
            return [epic_issue]
        if args == ["show", "ts-epic.1"]:
            return [changeset_issue]
        raise AssertionError(f"unexpected bd command: {args!r}")

    with (
        patch("atelier.prefix_migration_drift.beads.run_bd_json", side_effect=fake_show),
        patch("atelier.prefix_migration_drift.beads.list_epics", list_epics),
        patch("atelier.prefix_migration_drift.beads.list_descendant_changesets", list_descendants),
        patch("atelier.prefix_migration_drift.beads.list_work_children", list_work_children),
        patch(
            "atelier.prefix_migration_drift.exec_util.try_run_command",
            return_value=subprocess.CompletedProcess(
                args=["git", "worktree", "list", "--porcelain"],
                returncode=0,
                stdout=worktree_output,
                stderr="",
            ),
        ),
    ):
        records = prefix_migration_drift.scan_prefix_migration_drift(
            project_data_dir=project_data_dir,
            beads_root=tmp_path / ".beads",
            repo_root=repo_root,
            target_epic_id="ts-epic",
            target_changeset_ids={"ts-epic.1"},
        )

    assert records == []
    list_epics.assert_not_called()
    list_descendants.assert_not_called()
    list_work_children.assert_not_called()


def test_scan_prefix_migration_drift_reports_missing_mapping_lineage_entries(
    tmp_path: Path,
) -> None:
    project_data_dir = tmp_path / "data"
    repo_root = tmp_path / "repo"
    project_data_dir.mkdir(parents=True)
    repo_root.mkdir(parents=True)
    worktrees.write_mapping(
        worktrees.mapping_path(project_data_dir, "ts-epic"),
        worktrees.WorktreeMapping(
            epic_id="ts-epic",
            worktree_path="worktrees/ts-epic",
            root_branch="feat/new-root",
            changesets={},
            changeset_worktrees={},
        ),
    )
    epic_issue = {
        "id": "ts-epic",
        "labels": ["at:epic"],
        "description": "workspace.root_branch: feat/new-root\n",
    }
    changeset_issue = {
        "id": "ts-epic.1",
        "labels": [],
        "type": "task",
        "description": (
            "changeset.root_branch: feat/new-root\n"
            "changeset.work_branch: feat/new-branch\n"
            "worktree_path: worktrees/ts-epic.1\n"
        ),
    }
    worktree_output = _git_worktree_output(
        project_data_dir / "worktrees" / "ts-epic.1",
        "feat/new-branch",
    )

    with (
        patch("atelier.prefix_migration_drift.beads.list_epics", return_value=[epic_issue]),
        patch(
            "atelier.prefix_migration_drift.beads.list_descendant_changesets",
            return_value=[changeset_issue],
        ),
        patch("atelier.prefix_migration_drift.beads.list_work_children", return_value=[]),
        patch(
            "atelier.prefix_migration_drift.exec_util.try_run_command",
            return_value=subprocess.CompletedProcess(
                args=["git", "worktree", "list", "--porcelain"],
                returncode=0,
                stdout=worktree_output,
                stderr="",
            ),
        ),
    ):
        records = prefix_migration_drift.scan_prefix_migration_drift(
            project_data_dir=project_data_dir,
            beads_root=tmp_path / ".beads",
            repo_root=repo_root,
        )

    assert [record["drift_class"] for record in records] == [
        "metadata-missing-mapping-work-branch",
        "metadata-missing-mapping-worktree-path",
    ]
    assert records[0]["values"]["metadata.changeset.work_branch"] == "feat/new-branch"
    assert records[0]["values"]["mapping.work_branch"] is None
    assert records[1]["values"]["metadata.worktree_path"] == "worktrees/ts-epic.1"
    assert records[1]["values"]["mapping.worktree_path"] is None


def test_scan_prefix_migration_drift_scopes_explicit_changeset_without_epic_id_prefix(
    tmp_path: Path,
) -> None:
    project_data_dir = tmp_path / "data"
    repo_root = tmp_path / "repo"
    project_data_dir.mkdir(parents=True)
    repo_root.mkdir(parents=True)
    epic_issue = {
        "id": "ts-epic",
        "labels": ["at:epic"],
        "description": "workspace.root_branch: feat/new-root\n",
    }
    changeset_issue = {
        "id": "legacy-child",
        "labels": [],
        "type": "task",
        "description": (
            "changeset.root_branch: feat/new-root\nchangeset.work_branch: feat/new-branch\n"
        ),
    }
    worktree_output = _git_worktree_output(
        project_data_dir / "worktrees" / "legacy-child",
        "feat/new-branch",
    )
    show_calls: list[list[str]] = []

    def fake_show(
        args: list[str],
        *,
        beads_root: Path,
        cwd: Path,
    ) -> list[dict[str, object]]:
        del beads_root, cwd
        show_calls.append(args)
        if args == ["show", "ts-epic"]:
            return [epic_issue]
        if args == ["show", "legacy-child"]:
            return [changeset_issue]
        raise AssertionError(f"unexpected bd command: {args!r}")

    with (
        patch("atelier.prefix_migration_drift.beads.run_bd_json", side_effect=fake_show),
        patch("atelier.prefix_migration_drift.beads.list_epics") as list_epics,
        patch(
            "atelier.prefix_migration_drift.beads.list_descendant_changesets"
        ) as list_descendants,
        patch("atelier.prefix_migration_drift.beads.list_work_children") as list_work_children,
        patch(
            "atelier.prefix_migration_drift.exec_util.try_run_command",
            return_value=subprocess.CompletedProcess(
                args=["git", "worktree", "list", "--porcelain"],
                returncode=0,
                stdout=worktree_output,
                stderr="",
            ),
        ),
    ):
        records = prefix_migration_drift.scan_prefix_migration_drift(
            project_data_dir=project_data_dir,
            beads_root=tmp_path / ".beads",
            repo_root=repo_root,
            target_epic_id="ts-epic",
            target_changeset_ids={"legacy-child"},
        )

    assert records == []
    assert ["show", "legacy-child"] in show_calls
    list_epics.assert_not_called()
    list_descendants.assert_not_called()
    list_work_children.assert_not_called()


def test_scan_prefix_migration_drift_records_targeted_changeset_read_failure(
    tmp_path: Path,
) -> None:
    project_data_dir = tmp_path / "data"
    repo_root = tmp_path / "repo"
    project_data_dir.mkdir(parents=True)
    repo_root.mkdir(parents=True)

    epic_issue = {
        "id": "ts-epic",
        "labels": ["at:epic"],
        "description": "workspace.root_branch: feat/new-root\n",
    }

    def fake_show(
        args: list[str],
        *,
        beads_root: Path,
        cwd: Path,
    ) -> list[dict[str, object]]:
        del beads_root, cwd
        if args == ["show", "ts-epic"]:
            return [epic_issue]
        if args == ["show", "ts-epic.1"]:
            raise SystemExit(7)
        raise AssertionError(f"unexpected bd command: {args!r}")

    with (
        patch("atelier.prefix_migration_drift.beads.run_bd_json", side_effect=fake_show),
        patch("atelier.prefix_migration_drift.beads.list_epics") as list_epics,
        patch(
            "atelier.prefix_migration_drift.beads.list_descendant_changesets"
        ) as list_descendants,
        patch("atelier.prefix_migration_drift.beads.list_work_children") as list_work_children,
        patch(
            "atelier.prefix_migration_drift.exec_util.try_run_command",
            return_value=subprocess.CompletedProcess(
                args=["git", "worktree", "list", "--porcelain"],
                returncode=0,
                stdout="",
                stderr="",
            ),
        ),
    ):
        records = prefix_migration_drift.scan_prefix_migration_drift(
            project_data_dir=project_data_dir,
            beads_root=tmp_path / ".beads",
            repo_root=repo_root,
            target_epic_id="ts-epic",
            target_changeset_ids={"ts-epic.1"},
        )

    assert records == [
        {
            "epic_id": "ts-epic",
            "changeset_id": "ts-epic.1",
            "drift_class": "metadata-read-failure",
            "values": {
                "bd.command": "show ts-epic.1",
                "bd.exit_code": "7",
                "lookup.target_id": "ts-epic.1",
                "lookup.target_kind": "changeset",
            },
        }
    ]
    list_epics.assert_not_called()
    list_descendants.assert_not_called()
    list_work_children.assert_not_called()


def test_repair_prefix_migration_drift_plans_updates_without_applying(tmp_path: Path) -> None:
    project_data_dir = tmp_path / "data"
    repo_root = tmp_path / "repo"
    project_data_dir.mkdir(parents=True)
    repo_root.mkdir(parents=True)
    worktrees.write_mapping(
        worktrees.mapping_path(project_data_dir, "ts-epic"),
        worktrees.WorktreeMapping(
            epic_id="ts-epic",
            worktree_path="worktrees/ts-epic",
            root_branch="feat/new-root",
            changesets={"ts-epic.1": "feat/legacy-branch"},
            changeset_worktrees={"ts-epic.1": "worktrees/at-legacy.1"},
        ),
    )
    epic_issue = {
        "id": "ts-epic",
        "labels": ["at:epic"],
        "description": "workspace.root_branch: feat/new-root\n",
    }
    changeset_issue = {
        "id": "ts-epic.1",
        "labels": [],
        "type": "task",
        "description": (
            "changeset.root_branch: feat/new-root\n"
            "changeset.work_branch: feat/new-branch\n"
            "worktree_path: worktrees/at-legacy.1\n"
        ),
    }
    worktree_output = _git_worktree_output(
        project_data_dir / "worktrees" / "ts-epic.1",
        "feat/new-branch",
    )

    def fake_lookup(repo: str, branch: str) -> SimpleNamespace:
        assert repo == "org/repo"
        if branch == "feat/legacy-branch":
            return SimpleNamespace(
                found=True,
                failed=False,
                payload={"headRefName": "feat/pr-head"},
            )
        return SimpleNamespace(found=False, failed=False, payload=None)

    with (
        patch("atelier.prefix_migration_drift.beads.list_epics", return_value=[epic_issue]),
        patch(
            "atelier.prefix_migration_drift.beads.list_descendant_changesets",
            return_value=[changeset_issue],
        ),
        patch("atelier.prefix_migration_drift.beads.list_work_children", return_value=[]),
        patch(
            "atelier.prefix_migration_drift.exec_util.try_run_command",
            return_value=subprocess.CompletedProcess(
                args=["git", "worktree", "list", "--porcelain"],
                returncode=0,
                stdout=worktree_output,
                stderr="",
            ),
        ),
        patch("atelier.prefix_migration_drift.beads.update_workspace_root_branch") as update_root,
        patch(
            "atelier.prefix_migration_drift.beads.update_changeset_branch_metadata"
        ) as update_metadata,
        patch("atelier.prefix_migration_drift.beads.update_worktree_path") as update_path,
    ):
        actions = prefix_migration_drift.repair_prefix_migration_drift(
            project_data_dir=project_data_dir,
            beads_root=tmp_path / ".beads",
            repo_root=repo_root,
            repo_slug="org/repo",
            apply=False,
            lookup_pr_status=fake_lookup,
        )

    assert len(actions) == 1
    action = actions[0]
    assert action.changeset_id == "ts-epic.1"
    assert action.applied is False
    assert action.changed is True
    assert action.canonical_work_branch == "feat/pr-head"
    assert action.work_branch_source == "open-pr-head"
    assert action.canonical_worktree_path == "worktrees/ts-epic.1"
    assert action.worktree_path_source == "filesystem-metadata-branch"
    assert action.update_changeset_metadata is True
    assert action.update_changeset_worktree_path is True
    assert action.update_mapping is True
    update_root.assert_not_called()
    update_metadata.assert_not_called()
    update_path.assert_not_called()


def test_repair_prefix_migration_drift_apply_updates_mapping_and_metadata(tmp_path: Path) -> None:
    project_data_dir = tmp_path / "data"
    repo_root = tmp_path / "repo"
    project_data_dir.mkdir(parents=True)
    repo_root.mkdir(parents=True)
    mapping_path = worktrees.mapping_path(project_data_dir, "ts-epic")
    worktrees.write_mapping(
        mapping_path,
        worktrees.WorktreeMapping(
            epic_id="ts-epic",
            worktree_path="worktrees/ts-epic",
            root_branch="feat/new-root",
            changesets={"ts-epic.1": "feat/legacy-branch"},
            changeset_worktrees={"ts-epic.1": "worktrees/at-legacy.1"},
        ),
    )
    epic_issue = {
        "id": "ts-epic",
        "labels": ["at:epic"],
        "description": "workspace.root_branch: feat/new-root\n",
    }
    changeset_issue = {
        "id": "ts-epic.1",
        "labels": [],
        "type": "task",
        "description": (
            "changeset.root_branch: feat/new-root\n"
            "changeset.work_branch: feat/new-branch\n"
            "worktree_path: worktrees/at-legacy.1\n"
        ),
    }
    worktree_output = _git_worktree_output(
        project_data_dir / "worktrees" / "ts-epic.1",
        "feat/new-branch",
    )

    def fake_lookup(repo: str, branch: str) -> SimpleNamespace:
        assert repo == "org/repo"
        if branch == "feat/legacy-branch":
            return SimpleNamespace(
                found=True,
                failed=False,
                payload={"headRefName": "feat/pr-head"},
            )
        return SimpleNamespace(found=False, failed=False, payload=None)

    with (
        patch("atelier.prefix_migration_drift.beads.list_epics", return_value=[epic_issue]),
        patch(
            "atelier.prefix_migration_drift.beads.list_descendant_changesets",
            return_value=[changeset_issue],
        ),
        patch("atelier.prefix_migration_drift.beads.list_work_children", return_value=[]),
        patch(
            "atelier.prefix_migration_drift.exec_util.try_run_command",
            return_value=subprocess.CompletedProcess(
                args=["git", "worktree", "list", "--porcelain"],
                returncode=0,
                stdout=worktree_output,
                stderr="",
            ),
        ),
        patch("atelier.prefix_migration_drift.beads.update_workspace_root_branch") as update_root,
        patch(
            "atelier.prefix_migration_drift.beads.update_changeset_branch_metadata"
        ) as update_metadata,
        patch("atelier.prefix_migration_drift.beads.update_worktree_path") as update_path,
    ):
        actions = prefix_migration_drift.repair_prefix_migration_drift(
            project_data_dir=project_data_dir,
            beads_root=tmp_path / ".beads",
            repo_root=repo_root,
            repo_slug="org/repo",
            apply=True,
            lookup_pr_status=fake_lookup,
        )

    assert len(actions) == 1
    action = actions[0]
    assert action.applied is True
    update_root.assert_not_called()
    update_metadata.assert_called_once()
    update_path.assert_called_once_with(
        "ts-epic.1",
        "worktrees/ts-epic.1",
        beads_root=tmp_path / ".beads",
        cwd=repo_root,
        allow_override=True,
    )
    updated_mapping = worktrees.load_mapping(mapping_path)
    assert updated_mapping is not None
    assert updated_mapping.root_branch == "feat/new-root"
    assert updated_mapping.changesets["ts-epic.1"] == "feat/pr-head"
    assert updated_mapping.changeset_worktrees["ts-epic.1"] == "worktrees/ts-epic.1"


def test_repair_prefix_migration_drift_converges_duplicate_branch_paths_deterministically(
    tmp_path: Path,
) -> None:
    project_data_dir = tmp_path / "data"
    repo_root = tmp_path / "repo"
    project_data_dir.mkdir(parents=True)
    repo_root.mkdir(parents=True)
    mapping_path = worktrees.mapping_path(project_data_dir, "ts-epic")
    worktrees.write_mapping(
        mapping_path,
        worktrees.WorktreeMapping(
            epic_id="ts-epic",
            worktree_path="worktrees/ts-epic",
            root_branch="feat/new-root",
            changesets={"ts-epic.1": "feat/pr-head"},
            changeset_worktrees={"ts-epic.1": "worktrees/ts-epic.1"},
        ),
    )
    legacy_path = project_data_dir / "worktrees" / "at-legacy-ts-epic.1"
    legacy_path.mkdir(parents=True)
    (legacy_path / ".git").write_text("gitdir: /tmp/gitdir", encoding="utf-8")
    canonical_path = project_data_dir / "worktrees" / "ts-epic.1"
    canonical_path.mkdir(parents=True)
    (canonical_path / ".git").write_text("gitdir: /tmp/gitdir", encoding="utf-8")

    epic_issue = {
        "id": "ts-epic",
        "labels": ["at:epic"],
        "description": "workspace.root_branch: feat/new-root\n",
    }
    changeset_issue = {
        "id": "ts-epic.1",
        "labels": [],
        "type": "task",
        "description": (
            "changeset.root_branch: feat/new-root\n"
            "changeset.work_branch: feat/pr-head\n"
            "worktree_path: worktrees/ts-epic.1\n"
        ),
    }
    worktree_output = _git_worktree_output(legacy_path, "feat/pr-head") + _git_worktree_output(
        canonical_path, "feat/pr-head"
    )

    with (
        patch("atelier.prefix_migration_drift.beads.list_epics", return_value=[epic_issue]),
        patch(
            "atelier.prefix_migration_drift.beads.list_descendant_changesets",
            return_value=[changeset_issue],
        ),
        patch("atelier.prefix_migration_drift.beads.list_work_children", return_value=[]),
        patch(
            "atelier.prefix_migration_drift.exec_util.try_run_command",
            return_value=subprocess.CompletedProcess(
                args=["git", "worktree", "list", "--porcelain"],
                returncode=0,
                stdout=worktree_output,
                stderr="",
            ),
        ),
        patch("atelier.prefix_migration_drift.git.git_current_branch", return_value="feat/pr-head"),
    ):
        actions = prefix_migration_drift.repair_prefix_migration_drift(
            project_data_dir=project_data_dir,
            beads_root=tmp_path / ".beads",
            repo_root=repo_root,
            apply=False,
        )

    assert len(actions) == 1
    action = actions[0]
    assert action.changed is True
    assert action.canonical_work_branch == worktrees.derive_changeset_branch(
        "feat/new-root",
        "ts-epic.1",
    )
    assert action.canonical_worktree_path == "worktrees/ts-epic.1"
    assert action.worktree_path_source == "checked-out-worktree"
    assert action.update_changeset_metadata is True
    assert action.update_changeset_worktree_path is False
    assert action.update_mapping is True


def test_repair_prefix_migration_drift_apply_backfills_missing_mapping_lineage(
    tmp_path: Path,
) -> None:
    project_data_dir = tmp_path / "data"
    repo_root = tmp_path / "repo"
    project_data_dir.mkdir(parents=True)
    repo_root.mkdir(parents=True)
    mapping_path = worktrees.mapping_path(project_data_dir, "ts-epic")
    worktrees.write_mapping(
        mapping_path,
        worktrees.WorktreeMapping(
            epic_id="ts-epic",
            worktree_path="worktrees/ts-epic",
            root_branch="feat/new-root",
            changesets={},
            changeset_worktrees={},
        ),
    )
    epic_issue = {
        "id": "ts-epic",
        "labels": ["at:epic"],
        "description": "workspace.root_branch: feat/new-root\n",
    }
    changeset_issue = {
        "id": "ts-epic.1",
        "labels": [],
        "type": "task",
        "description": (
            "changeset.root_branch: feat/new-root\n"
            "changeset.work_branch: feat/new-branch\n"
            "worktree_path: worktrees/ts-epic.1\n"
        ),
    }
    worktree_output = _git_worktree_output(
        project_data_dir / "worktrees" / "ts-epic.1",
        "feat/new-branch",
    )

    with (
        patch("atelier.prefix_migration_drift.beads.list_epics", return_value=[epic_issue]),
        patch(
            "atelier.prefix_migration_drift.beads.list_descendant_changesets",
            return_value=[changeset_issue],
        ),
        patch("atelier.prefix_migration_drift.beads.list_work_children", return_value=[]),
        patch(
            "atelier.prefix_migration_drift.exec_util.try_run_command",
            return_value=subprocess.CompletedProcess(
                args=["git", "worktree", "list", "--porcelain"],
                returncode=0,
                stdout=worktree_output,
                stderr="",
            ),
        ),
        patch("atelier.prefix_migration_drift.beads.update_workspace_root_branch") as update_root,
        patch(
            "atelier.prefix_migration_drift.beads.update_changeset_branch_metadata"
        ) as update_metadata,
        patch("atelier.prefix_migration_drift.beads.update_worktree_path") as update_path,
    ):
        first = prefix_migration_drift.repair_prefix_migration_drift(
            project_data_dir=project_data_dir,
            beads_root=tmp_path / ".beads",
            repo_root=repo_root,
            apply=True,
        )
        second = prefix_migration_drift.repair_prefix_migration_drift(
            project_data_dir=project_data_dir,
            beads_root=tmp_path / ".beads",
            repo_root=repo_root,
            apply=True,
        )

    assert len(first) == 1
    action = first[0]
    assert action.changed is True
    assert action.applied is True
    assert action.update_mapping is True
    assert action.update_changeset_metadata is False
    assert action.update_changeset_worktree_path is False
    assert "metadata-missing-mapping-work-branch" in action.drift_classes
    assert "metadata-missing-mapping-worktree-path" in action.drift_classes
    assert second == []

    update_root.assert_not_called()
    update_metadata.assert_not_called()
    update_path.assert_not_called()
    updated_mapping = worktrees.load_mapping(mapping_path)
    assert updated_mapping is not None
    assert updated_mapping.changesets["ts-epic.1"] == "feat/new-branch"
    assert updated_mapping.changeset_worktrees["ts-epic.1"] == "worktrees/ts-epic.1"


def test_repair_prefix_migration_drift_defers_blocked_epic_updates(tmp_path: Path) -> None:
    project_data_dir = tmp_path / "data"
    repo_root = tmp_path / "repo"
    project_data_dir.mkdir(parents=True)
    repo_root.mkdir(parents=True)
    mapping_path = worktrees.mapping_path(project_data_dir, "ts-epic")
    worktrees.write_mapping(
        mapping_path,
        worktrees.WorktreeMapping(
            epic_id="ts-epic",
            worktree_path="worktrees/ts-epic",
            root_branch="feat/new-root",
            changesets={"ts-epic.1": "feat/legacy-branch"},
            changeset_worktrees={"ts-epic.1": "worktrees/at-legacy.1"},
        ),
    )
    epic_issue = {
        "id": "ts-epic",
        "labels": ["at:epic"],
        "description": "workspace.root_branch: feat/new-root\n",
    }
    changeset_issue = {
        "id": "ts-epic.1",
        "labels": [],
        "type": "task",
        "description": (
            "changeset.root_branch: feat/new-root\n"
            "changeset.work_branch: feat/new-branch\n"
            "worktree_path: worktrees/at-legacy.1\n"
        ),
    }
    worktree_output = _git_worktree_output(
        project_data_dir / "worktrees" / "ts-epic.1",
        "feat/new-branch",
    )

    with (
        patch("atelier.prefix_migration_drift.beads.list_epics", return_value=[epic_issue]),
        patch(
            "atelier.prefix_migration_drift.beads.list_descendant_changesets",
            return_value=[changeset_issue],
        ),
        patch("atelier.prefix_migration_drift.beads.list_work_children", return_value=[]),
        patch(
            "atelier.prefix_migration_drift.exec_util.try_run_command",
            return_value=subprocess.CompletedProcess(
                args=["git", "worktree", "list", "--porcelain"],
                returncode=0,
                stdout=worktree_output,
                stderr="",
            ),
        ),
        patch("atelier.prefix_migration_drift.beads.update_workspace_root_branch") as update_root,
        patch(
            "atelier.prefix_migration_drift.beads.update_changeset_branch_metadata"
        ) as update_metadata,
        patch("atelier.prefix_migration_drift.beads.update_worktree_path") as update_path,
    ):
        actions = prefix_migration_drift.repair_prefix_migration_drift(
            project_data_dir=project_data_dir,
            beads_root=tmp_path / ".beads",
            repo_root=repo_root,
            repo_slug="org/repo",
            apply=True,
            blocked_epics={"ts-epic"},
        )

    assert len(actions) == 1
    action = actions[0]
    assert action.changed is True
    assert action.applied is False
    assert action.deferred_reason == "active-hook"
    update_root.assert_not_called()
    update_metadata.assert_not_called()
    update_path.assert_not_called()


def test_scan_prefix_migration_drift_reports_mixed_legacy_prefix_states(tmp_path: Path) -> None:
    project_data_dir = tmp_path / "data"
    repo_root = tmp_path / "repo"
    project_data_dir.mkdir(parents=True)
    repo_root.mkdir(parents=True)
    worktrees.write_mapping(
        worktrees.mapping_path(project_data_dir, "ts-epic"),
        worktrees.WorktreeMapping(
            epic_id="ts-epic",
            worktree_path="worktrees/ts-epic",
            root_branch="feat/ts-root",
            changesets={"ts-epic.1": "feat/legacy-ts"},
            changeset_worktrees={"ts-epic.1": "worktrees/at-legacy-ts.1"},
        ),
    )
    worktrees.write_mapping(
        worktrees.mapping_path(project_data_dir, "gs-epic"),
        worktrees.WorktreeMapping(
            epic_id="gs-epic",
            worktree_path="worktrees/gs-epic",
            root_branch="feat/gs-root",
            changesets={},
            changeset_worktrees={},
        ),
    )

    epic_issues = [
        {
            "id": "ts-epic",
            "labels": ["at:epic"],
            "description": "workspace.root_branch: feat/ts-root\n",
        },
        {
            "id": "gs-epic",
            "labels": ["at:epic"],
            "description": "workspace.root_branch: feat/gs-root\n",
        },
    ]
    descendants = {
        "ts-epic": [
            {
                "id": "ts-epic.1",
                "labels": [],
                "type": "task",
                "description": (
                    "changeset.root_branch: feat/ts-root\n"
                    "changeset.work_branch: feat/ts-head\n"
                    "worktree_path: worktrees/at-legacy-ts.1\n"
                ),
            }
        ],
        "gs-epic": [
            {
                "id": "gs-epic.1",
                "labels": [],
                "type": "task",
                "description": (
                    "changeset.root_branch: feat/gs-root\n"
                    "changeset.work_branch: feat/gs-head\n"
                    "worktree_path: worktrees/at-legacy-gs.1\n"
                ),
            }
        ],
    }
    worktree_output = _git_worktree_output(
        project_data_dir / "worktrees" / "ts-epic.1", "feat/ts-head"
    ) + _git_worktree_output(project_data_dir / "worktrees" / "gs-epic.1", "feat/gs-head")

    def fake_descendants(
        epic_id: str,
        *,
        beads_root: Path,
        cwd: Path,
        include_closed: bool,
    ) -> list[dict[str, object]]:
        del beads_root, cwd, include_closed
        return descendants[epic_id]

    with (
        patch("atelier.prefix_migration_drift.beads.list_epics", return_value=epic_issues),
        patch(
            "atelier.prefix_migration_drift.beads.list_descendant_changesets",
            side_effect=fake_descendants,
        ),
        patch("atelier.prefix_migration_drift.beads.list_work_children", return_value=[]),
        patch(
            "atelier.prefix_migration_drift.exec_util.try_run_command",
            return_value=subprocess.CompletedProcess(
                args=["git", "worktree", "list", "--porcelain"],
                returncode=0,
                stdout=worktree_output,
                stderr="",
            ),
        ),
    ):
        records = prefix_migration_drift.scan_prefix_migration_drift(
            project_data_dir=project_data_dir,
            beads_root=tmp_path / ".beads",
            repo_root=repo_root,
            repo_slug=None,
        )

    assert len(records) == 5
    assert {record["changeset_id"] for record in records} == {"ts-epic.1", "gs-epic.1"}
    assert {
        record["drift_class"] for record in records if record["changeset_id"] == "ts-epic.1"
    } == {"work-branch-conflict", "worktree-path-conflict"}
    assert {
        record["drift_class"] for record in records if record["changeset_id"] == "gs-epic.1"
    } == {
        "metadata-missing-mapping-work-branch",
        "metadata-missing-mapping-worktree-path",
        "worktree-path-conflict",
    }
    assert any(
        record["values"]["mapping.worktree_path"] == "worktrees/at-legacy-ts.1"
        for record in records
        if record["drift_class"] == "worktree-path-conflict"
    )
    assert any(
        record["values"]["metadata.worktree_path"] == "worktrees/at-legacy-gs.1"
        for record in records
        if (
            record["drift_class"] == "metadata-missing-mapping-worktree-path"
            and record["changeset_id"] == "gs-epic.1"
        )
    )


def test_repair_prefix_migration_drift_apply_is_idempotent(tmp_path: Path) -> None:
    project_data_dir = tmp_path / "data"
    repo_root = tmp_path / "repo"
    project_data_dir.mkdir(parents=True)
    repo_root.mkdir(parents=True)
    mapping_path = worktrees.mapping_path(project_data_dir, "ts-epic")
    worktrees.write_mapping(
        mapping_path,
        worktrees.WorktreeMapping(
            epic_id="ts-epic",
            worktree_path="worktrees/ts-epic",
            root_branch="feat/ts-root",
            changesets={"ts-epic.1": "feat/legacy-ts"},
            changeset_worktrees={"ts-epic.1": "worktrees/at-legacy-ts.1"},
        ),
    )
    epic_issue = {
        "id": "ts-epic",
        "labels": ["at:epic"],
        "description": "workspace.root_branch: feat/ts-root\n",
    }
    changeset_issue = {
        "id": "ts-epic.1",
        "labels": [],
        "type": "task",
        "description": (
            "changeset.root_branch: feat/ts-root\n"
            "changeset.work_branch: feat/ts-head\n"
            "worktree_path: worktrees/at-legacy-ts.1\n"
        ),
    }

    def set_description_field(issue: dict[str, object], key: str, value: str) -> None:
        fields = beads.parse_description_fields(issue.get("description"))
        fields[key] = value
        issue["description"] = "".join(
            f"{field_key}: {field_value}\n" for field_key, field_value in fields.items()
        )

    def fake_update_metadata(
        changeset_id: str,
        *,
        root_branch: str | None,
        parent_branch: str | None,
        work_branch: str | None,
        beads_root: Path,
        cwd: Path,
        allow_override: bool,
    ) -> None:
        del changeset_id, parent_branch, beads_root, cwd, allow_override
        if root_branch is not None:
            set_description_field(changeset_issue, "changeset.root_branch", root_branch)
        if work_branch is not None:
            set_description_field(changeset_issue, "changeset.work_branch", work_branch)

    def fake_update_worktree_path(
        changeset_id: str,
        worktree_path: str,
        *,
        beads_root: Path,
        cwd: Path,
        allow_override: bool,
    ) -> None:
        del changeset_id, beads_root, cwd, allow_override
        set_description_field(changeset_issue, "worktree_path", worktree_path)

    worktree_output = _git_worktree_output(
        project_data_dir / "worktrees" / "ts-epic.1",
        "feat/ts-head",
    )

    def fake_lookup(repo: str, branch: str) -> SimpleNamespace:
        assert repo == "org/repo"
        if branch == "feat/legacy-ts":
            return SimpleNamespace(
                found=True,
                failed=False,
                payload={"headRefName": "feat/ts-head"},
            )
        return SimpleNamespace(found=False, failed=False, payload=None)

    with (
        patch("atelier.prefix_migration_drift.beads.list_epics", return_value=[epic_issue]),
        patch(
            "atelier.prefix_migration_drift.beads.list_descendant_changesets",
            return_value=[changeset_issue],
        ),
        patch("atelier.prefix_migration_drift.beads.list_work_children", return_value=[]),
        patch(
            "atelier.prefix_migration_drift.exec_util.try_run_command",
            return_value=subprocess.CompletedProcess(
                args=["git", "worktree", "list", "--porcelain"],
                returncode=0,
                stdout=worktree_output,
                stderr="",
            ),
        ),
        patch(
            "atelier.prefix_migration_drift.beads.update_changeset_branch_metadata",
            side_effect=fake_update_metadata,
        ),
        patch(
            "atelier.prefix_migration_drift.beads.update_worktree_path",
            side_effect=fake_update_worktree_path,
        ),
        patch("atelier.prefix_migration_drift.beads.update_workspace_root_branch"),
    ):
        first = prefix_migration_drift.repair_prefix_migration_drift(
            project_data_dir=project_data_dir,
            beads_root=tmp_path / ".beads",
            repo_root=repo_root,
            repo_slug="org/repo",
            apply=True,
            lookup_pr_status=fake_lookup,
        )
        second = prefix_migration_drift.repair_prefix_migration_drift(
            project_data_dir=project_data_dir,
            beads_root=tmp_path / ".beads",
            repo_root=repo_root,
            repo_slug="org/repo",
            apply=True,
            lookup_pr_status=fake_lookup,
        )

    assert len(first) == 1
    assert first[0].changed is True
    assert first[0].applied is True
    assert second == []

    updated_mapping = worktrees.load_mapping(mapping_path)
    assert updated_mapping is not None
    assert updated_mapping.changesets["ts-epic.1"] == "feat/ts-head"
    assert updated_mapping.changeset_worktrees["ts-epic.1"] == "worktrees/ts-epic.1"

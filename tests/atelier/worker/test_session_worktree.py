from __future__ import annotations

from pathlib import Path
from unittest.mock import ANY, Mock, call, patch

import pytest

from atelier import worktrees
from atelier.worker.session import worktree


class _TestControl:
    def __init__(self, logs: list[str]) -> None:
        self.logs = logs

    def say(self, message: str) -> None:
        self.logs.append(message)

    def dry_run_log(self, message: str) -> None:
        self.logs.append(message)


def test_prepare_worktrees_dry_run_derives_changeset_branch(tmp_path: Path) -> None:
    logs: list[str] = []

    result = worktree.prepare_worktrees(
        context=worktree.WorktreePreparationContext(
            dry_run=True,
            project_data_dir=tmp_path,
            repo_root=Path("/repo"),
            beads_root=Path("/beads"),
            selected_epic="at-epic",
            changeset_id="at-epic.1",
            root_branch_value="feat/root",
            changeset_parent_branch="feat/root",
            allow_parent_branch_override=False,
            git_path="git",
        ),
        control=_TestControl(logs),
    )

    assert result.epic_worktree_path == worktrees.worktree_dir(tmp_path, "at-epic")
    assert result.changeset_worktree_path == (
        tmp_path / worktrees.changeset_worktree_relpath("at-epic.1")
    )
    assert result.branch == worktrees.derive_changeset_branch("feat/root", "at-epic.1")
    assert any("Would ensure git worktrees and checkout." in line for line in logs)


def test_prepare_worktrees_dry_run_reuses_epic_worktree_for_epic_changeset(
    tmp_path: Path,
) -> None:
    logs: list[str] = []

    result = worktree.prepare_worktrees(
        context=worktree.WorktreePreparationContext(
            dry_run=True,
            project_data_dir=tmp_path,
            repo_root=Path("/repo"),
            beads_root=Path("/beads"),
            selected_epic="at-epic",
            changeset_id="at-epic",
            root_branch_value="feat/root",
            changeset_parent_branch="feat/root",
            allow_parent_branch_override=False,
            git_path="git",
        ),
        control=_TestControl(logs),
    )

    assert result.changeset_worktree_path == result.epic_worktree_path
    assert result.branch == "feat/root"
    assert any("Changeset branch: feat/root" in line for line in logs)


def test_prepare_worktrees_blocks_before_mutations_on_prefix_drift_for_selected_changeset() -> None:
    logs: list[str] = []
    reconcile_mapping = Mock()
    ensure_epic_worktree = Mock()
    ensure_changeset_branch = Mock()
    scan_drift = Mock(
        return_value=[
            {
                "epic_id": "at-epic",
                "changeset_id": "at-epic.1",
                "drift_class": "work-branch-conflict",
                "values": {
                    "metadata.changeset.work_branch": "feat/new-at-epic.1",
                    "mapping.work_branch": "at/legacy-at-epic.1",
                },
            }
        ]
    )

    with (
        patch(
            "atelier.worker.session.worktree.prefix_migration_drift.scan_prefix_migration_drift",
            scan_drift,
        ),
        patch("atelier.worker.session.worktree.git.git_origin_url", return_value=None),
        patch("atelier.worker.session.worktree.prs.github_repo_slug", return_value=None),
        patch(
            "atelier.worker.session.worktree.worktrees.reconcile_mapping_ownership",
            reconcile_mapping,
        ),
        patch(
            "atelier.worker.session.worktree.worktrees.ensure_git_worktree",
            ensure_epic_worktree,
        ),
        patch(
            "atelier.worker.session.worktree.worktrees.ensure_changeset_branch",
            ensure_changeset_branch,
        ),
    ):
        with pytest.raises(RuntimeError, match="startup preflight blocked"):
            worktree.prepare_worktrees(
                context=worktree.WorktreePreparationContext(
                    dry_run=False,
                    project_data_dir=Path("/project"),
                    repo_root=Path("/repo"),
                    beads_root=Path("/beads"),
                    selected_epic="at-epic",
                    changeset_id="at-epic.1",
                    root_branch_value="feat/new",
                    changeset_parent_branch="feat/new",
                    allow_parent_branch_override=False,
                    git_path="git",
                ),
                control=_TestControl(logs),
            )

    scan_drift.assert_called_once_with(
        project_data_dir=Path("/project"),
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
        repo_slug=None,
        git_path="git",
        target_epic_id="at-epic",
        target_changeset_ids={"at-epic", "at-epic.1"},
    )
    reconcile_mapping.assert_not_called()
    ensure_epic_worktree.assert_not_called()
    ensure_changeset_branch.assert_not_called()
    assert not logs


def test_prepare_worktrees_reconciles_ownership_before_worktree_setup(tmp_path: Path) -> None:
    logs: list[str] = []
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True)
    changeset_worktree_path = tmp_path / "worktrees" / "at-gnc.1"
    changeset_worktree_path.mkdir(parents=True)
    (changeset_worktree_path / ".git").write_text("gitdir: /tmp/gitdir", encoding="utf-8")

    mapping = worktrees.WorktreeMapping(
        epic_id="at-gnc",
        worktree_path="worktrees/at-gnc",
        root_branch="feat/gnc",
        changesets={"at-gnc.1": "feat/gnc-at-gnc.1"},
        changeset_worktrees={"at-gnc.1": "worktrees/at-gnc.1"},
    )
    epics = [
        {
            "id": "at-gnc",
            "labels": ["at:epic"],
            "description": "workspace.root_branch: feat/gnc\nworktree_path: worktrees/at-gnc\n",
        },
        {
            "id": "at-1my",
            "labels": ["at:epic"],
            "description": "workspace.root_branch: feat/1my\nworktree_path: worktrees/at-1my\n",
        },
    ]
    descendants_by_epic = {
        "at-gnc": [{"id": "at-gnc.1"}],
        "at-1my": [{"id": "at-1my.1"}],
    }

    def fake_descendants(
        parent_id: str,
        *,
        beads_root: Path,
        cwd: Path,
        include_closed: bool = False,
    ) -> list[dict[str, object]]:
        del beads_root, cwd, include_closed
        return descendants_by_epic.get(parent_id, [])

    work_children_by_parent = {
        "at-gnc": [{"id": "at-gnc.1", "labels": [], "type": "task"}],
        "at-1my": [{"id": "at-1my.1", "labels": [], "type": "task"}],
        "at-gnc.1": [],
        "at-1my.1": [],
    }

    def fake_run_bd_json(
        args: list[str],
        *,
        beads_root: Path,
        cwd: Path,
    ) -> list[dict[str, object]]:
        if args[:2] == ["list", "--parent"] and len(args) >= 3:
            parent = args[2]
            return work_children_by_parent.get(parent, [])
        if "at:epic" in args:
            return epics
        return []

    with (
        patch("atelier.worker.session.worktree.beads.run_bd_json", side_effect=fake_run_bd_json),
        patch(
            "atelier.worker.session.worktree.beads.list_descendant_changesets",
            side_effect=fake_descendants,
        ),
        patch(
            "atelier.worker.session.worktree.worktrees.reconcile_mapping_ownership",
            return_value=("at-1my", "at-gnc"),
        ) as reconcile_mapping,
        patch(
            "atelier.worker.session.worktree.worktrees.ensure_git_worktree",
            return_value=tmp_path / "worktrees" / "at-gnc",
        ),
        patch(
            "atelier.worker.session.worktree.worktrees.ensure_changeset_branch",
            return_value=("feat/gnc-at-gnc.1", mapping),
        ),
        patch("atelier.worker.session.worktree.beads.update_worktree_path"),
        patch(
            "atelier.worker.session.worktree.worktrees.ensure_changeset_worktree",
            return_value=changeset_worktree_path,
        ),
        patch("atelier.worker.session.worktree.worktrees.ensure_changeset_checkout"),
        patch("atelier.worker.session.worktree.git.git_rev_parse", return_value="abc1234"),
        patch("atelier.worker.session.worktree.beads.update_changeset_branch_metadata"),
    ):
        worktree.prepare_worktrees(
            context=worktree.WorktreePreparationContext(
                dry_run=False,
                project_data_dir=tmp_path,
                repo_root=repo_root,
                beads_root=tmp_path / "beads",
                selected_epic="at-gnc",
                changeset_id="at-gnc.1",
                root_branch_value="feat/gnc",
                changeset_parent_branch="feat/gnc",
                allow_parent_branch_override=False,
                git_path="git",
            ),
            control=_TestControl(logs),
        )

    reconcile_mapping.assert_called_once_with(
        tmp_path,
        owner_by_changeset={
            "at-gnc.1": "at-gnc",
            "at-1my.1": "at-1my",
        },
        epic_root_branches={
            "at-gnc": "feat/gnc",
            "at-1my": "feat/1my",
        },
        epic_worktree_paths={
            "at-gnc": "worktrees/at-gnc",
            "at-1my": "worktrees/at-1my",
        },
        synthesis_diagnostics=ANY,
    )
    assert any("Reconciled mapping ownership: at-1my, at-gnc" in line for line in logs)


def test_prepare_worktrees_review_feedback_resume_logs_lineage_mapping_path_synthesis(
    tmp_path: Path,
) -> None:
    logs: list[str] = []
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True)
    changeset_worktree_path = tmp_path / "worktrees" / "at-legacy.1"
    changeset_worktree_path.mkdir(parents=True)
    (changeset_worktree_path / ".git").write_text("gitdir: /tmp/gitdir", encoding="utf-8")

    mapping = worktrees.WorktreeMapping(
        epic_id="ts-new",
        worktree_path="worktrees/at-legacy",
        root_branch="feat/legacy",
        changesets={"ts-new.1": "feat/legacy-ts-new.1"},
        changeset_worktrees={"ts-new.1": "worktrees/at-legacy.1"},
    )
    epics = [
        {
            "id": "ts-new",
            "labels": ["at:epic"],
            "description": "workspace.root_branch: feat/new\n",
        },
        {
            "id": "at-legacy",
            "labels": ["at:epic"],
            "description": "workspace.root_branch: feat/legacy\nworktree_path: worktrees/at-legacy\n",
        },
    ]

    def fake_run_bd_json(
        args: list[str],
        *,
        beads_root: Path,
        cwd: Path,
    ) -> list[dict[str, object]]:
        del beads_root, cwd
        if args[:2] == ["list", "--parent"] and len(args) >= 3:
            parent = args[2]
            if parent == "ts-new":
                return [{"id": "ts-new.1", "labels": ["review-feedback"], "type": "task"}]
            return []
        if "at:epic" in args:
            return epics
        return []

    def fake_descendants(
        parent_id: str,
        *,
        beads_root: Path,
        cwd: Path,
        include_closed: bool = False,
    ) -> list[dict[str, object]]:
        del beads_root, cwd, include_closed
        if parent_id == "ts-new":
            return [{"id": "ts-new.1"}]
        return []

    def fake_reconcile(
        project_data_dir: Path,
        *,
        owner_by_changeset: dict[str, str],
        epic_root_branches: dict[str, str],
        epic_worktree_paths: dict[str, str],
        synthesis_diagnostics: dict[str, worktrees.MappingSynthesisDiagnostic],
    ) -> tuple[str, ...]:
        del project_data_dir, owner_by_changeset, epic_root_branches, epic_worktree_paths
        synthesis_diagnostics["ts-new"] = worktrees.MappingSynthesisDiagnostic(
            epic_id="ts-new",
            worktree_path="worktrees/at-legacy",
            worktree_path_source="lineage",
            root_branch="feat/new",
            root_branch_source="metadata",
        )
        return ("ts-new",)

    with (
        patch("atelier.worker.session.worktree.beads.run_bd_json", side_effect=fake_run_bd_json),
        patch(
            "atelier.worker.session.worktree.beads.list_descendant_changesets",
            side_effect=fake_descendants,
        ),
        patch(
            "atelier.worker.session.worktree.worktrees.reconcile_mapping_ownership",
            side_effect=fake_reconcile,
        ),
        patch(
            "atelier.worker.session.worktree.worktrees.ensure_git_worktree",
            return_value=tmp_path / "worktrees" / "at-legacy",
        ),
        patch(
            "atelier.worker.session.worktree.worktrees.ensure_changeset_branch",
            return_value=("feat/legacy-ts-new.1", mapping),
        ),
        patch("atelier.worker.session.worktree.beads.update_worktree_path"),
        patch(
            "atelier.worker.session.worktree.worktrees.ensure_changeset_worktree",
            return_value=changeset_worktree_path,
        ),
        patch("atelier.worker.session.worktree.worktrees.ensure_changeset_checkout"),
        patch("atelier.worker.session.worktree.git.git_rev_parse", return_value="abc1234"),
        patch("atelier.worker.session.worktree.beads.update_changeset_branch_metadata"),
    ):
        worktree.prepare_worktrees(
            context=worktree.WorktreePreparationContext(
                dry_run=False,
                project_data_dir=tmp_path,
                repo_root=repo_root,
                beads_root=tmp_path / "beads",
                selected_epic="ts-new",
                changeset_id="ts-new.1",
                root_branch_value="feat/new",
                changeset_parent_branch="feat/new",
                allow_parent_branch_override=False,
                git_path="git",
            ),
            control=_TestControl(logs),
        )

    assert any("Reconciled mapping ownership: ts-new" in line for line in logs)
    assert any(
        "Mapping path synthesis for ts-new: preserved from source mapping lineage "
        "(worktrees/at-legacy)" in line
        for line in logs
    )


def test_resolve_lineage_repair_prefers_open_pr_head_and_checked_out_path(tmp_path: Path) -> None:
    legacy_path = tmp_path / "worktrees" / "at-legacy.1"
    legacy_path.mkdir(parents=True)
    (legacy_path / ".git").write_text("gitdir: /tmp/gitdir", encoding="utf-8")
    mapping = worktrees.WorktreeMapping(
        epic_id="ts-new",
        worktree_path="worktrees/ts-new",
        root_branch="feat/new",
        changesets={"ts-new.1": "feat/new-ts-new.1"},
        changeset_worktrees={"ts-new.1": "worktrees/at-legacy.1"},
    )
    issue = {
        "id": "ts-new.1",
        "description": (
            "changeset.root_branch: feat/new\n"
            "changeset.parent_branch: feat/new\n"
            "changeset.work_branch: feat/new-ts-new.1\n"
        ),
    }

    with (
        patch(
            "atelier.worker.session.worktree.git.git_current_branch",
            return_value="feat/legacy-ts-new.1",
        ),
        patch(
            "atelier.worker.session.worktree._lookup_open_pr_head",
            return_value="feat/legacy-ts-new.1",
        ),
    ):
        decision = worktree._resolve_lineage_repair(
            project_data_dir=tmp_path,
            repo_slug="acme/repo",
            changeset_id="ts-new.1",
            root_branch_value="feat/new",
            parent_branch_value="feat/new",
            mapping=mapping,
            issue=issue,
            git_path="git",
        )

    assert decision.work_branch == "feat/legacy-ts-new.1"
    assert decision.work_branch_source == "open-pr-head"
    assert decision.worktree_relpath == "worktrees/at-legacy.1"
    assert decision.worktree_source == "checked-out-worktree"
    assert decision.metadata_changed is True
    assert decision.mapping_changed is True


def test_lookup_open_pr_head_does_not_force_refresh_on_failed_lookup() -> None:
    lookup = Mock(
        side_effect=[
            worktree.prs.GithubPrLookup(outcome="error", error="network timeout"),
            worktree.prs.GithubPrLookup(
                outcome="found",
                payload={"state": "OPEN", "headRefName": "feat/new-at-epic.1"},
            ),
        ]
    )

    with patch("atelier.worker.session.worktree.prs.lookup_github_pr_status", lookup):
        head = worktree._lookup_open_pr_head(
            repo_slug="acme/repo",
            branch_candidates=("feat/legacy-at-epic.1", "feat/new-at-epic.1"),
        )

    assert head == "feat/new-at-epic.1"
    assert lookup.call_args_list == [
        call("acme/repo", "feat/legacy-at-epic.1"),
        call("acme/repo", "feat/new-at-epic.1"),
    ]


def test_prepare_worktrees_aligns_child_workspace_parent_branch_from_epic(tmp_path: Path) -> None:
    logs: list[str] = []
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True)
    changeset_worktree_path = tmp_path / "worktrees" / "at-epic.1"
    changeset_worktree_path.mkdir(parents=True)
    (changeset_worktree_path / ".git").write_text("gitdir: /tmp/gitdir", encoding="utf-8")
    mapping = worktrees.WorktreeMapping(
        epic_id="at-epic",
        worktree_path="worktrees/at-epic",
        root_branch="feat/epic",
        changesets={"at-epic.1": "feat/epic-at-epic.1"},
        changeset_worktrees={"at-epic.1": "worktrees/at-epic.1"},
    )
    epics = [
        {
            "id": "at-epic",
            "labels": ["at:epic"],
            "description": "workspace.root_branch: feat/epic\n",
        }
    ]

    def fake_run_bd_json(
        args: list[str],
        *,
        beads_root: Path,
        cwd: Path,
    ) -> list[dict[str, object]]:
        del beads_root, cwd
        if args[:3] == ["list", "--label", "at:epic"]:
            return epics
        if args[:2] == ["list", "--parent"] and len(args) >= 3:
            return (
                [{"id": "at-epic.1", "labels": [], "type": "task"}] if args[2] == "at-epic" else []
            )
        if args == ["show", "at-epic.1"]:
            return [{"id": "at-epic.1", "description": "changeset.root_branch: feat/epic\n"}]
        return []

    with (
        patch("atelier.worker.session.worktree.beads.run_bd_json", side_effect=fake_run_bd_json),
        patch(
            "atelier.worker.session.worktree.beads.list_descendant_changesets",
            return_value=[{"id": "at-epic.1"}],
        ),
        patch(
            "atelier.worker.session.worktree.worktrees.reconcile_mapping_ownership", return_value=()
        ),
        patch(
            "atelier.worker.session.worktree.worktrees.ensure_git_worktree",
            return_value=tmp_path / "worktrees" / "at-epic",
        ),
        patch(
            "atelier.worker.session.worktree.worktrees.ensure_changeset_branch",
            return_value=("feat/epic-at-epic.1", mapping),
        ),
        patch("atelier.worker.session.worktree.beads.update_worktree_path"),
        patch(
            "atelier.worker.session.worktree.worktrees.ensure_changeset_worktree",
            return_value=changeset_worktree_path,
        ),
        patch("atelier.worker.session.worktree.worktrees.ensure_changeset_checkout"),
        patch("atelier.worker.session.worktree.git.git_rev_parse", return_value="abc1234"),
        patch(
            "atelier.worker.session.worktree.beads.update_workspace_parent_branch"
        ) as update_parent,
        patch("atelier.worker.session.worktree.beads.update_changeset_branch_metadata"),
    ):
        worktree.prepare_worktrees(
            context=worktree.WorktreePreparationContext(
                dry_run=False,
                project_data_dir=tmp_path,
                repo_root=repo_root,
                beads_root=tmp_path / ".beads",
                selected_epic="at-epic",
                changeset_id="at-epic.1",
                root_branch_value="feat/epic",
                changeset_parent_branch="feat/epic-at-epic.0",
                allow_parent_branch_override=False,
                git_path="git",
                epic_parent_branch="main",
            ),
            control=_TestControl(logs),
        )

    update_parent.assert_called_once_with(
        "at-epic.1",
        "main",
        beads_root=tmp_path / ".beads",
        cwd=repo_root,
        allow_override=False,
    )
    assert any("Aligned workspace.parent_branch for at-epic.1: main" in line for line in logs)


def test_prepare_worktrees_preserves_existing_non_root_child_workspace_parent_branch(
    tmp_path: Path,
) -> None:
    logs: list[str] = []
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True)
    changeset_worktree_path = tmp_path / "worktrees" / "at-epic.1"
    changeset_worktree_path.mkdir(parents=True)
    (changeset_worktree_path / ".git").write_text("gitdir: /tmp/gitdir", encoding="utf-8")
    mapping = worktrees.WorktreeMapping(
        epic_id="at-epic",
        worktree_path="worktrees/at-epic",
        root_branch="feat/epic",
        changesets={"at-epic.1": "feat/epic-at-epic.1"},
        changeset_worktrees={"at-epic.1": "worktrees/at-epic.1"},
    )
    epics = [
        {
            "id": "at-epic",
            "labels": ["at:epic"],
            "description": "workspace.root_branch: feat/epic\n",
        }
    ]

    def fake_run_bd_json(
        args: list[str],
        *,
        beads_root: Path,
        cwd: Path,
    ) -> list[dict[str, object]]:
        del beads_root, cwd
        if args[:3] == ["list", "--label", "at:epic"]:
            return epics
        if args[:2] == ["list", "--parent"] and len(args) >= 3:
            return (
                [{"id": "at-epic.1", "labels": [], "type": "task"}] if args[2] == "at-epic" else []
            )
        if args == ["show", "at-epic.1"]:
            return [
                {
                    "id": "at-epic.1",
                    "description": (
                        "changeset.root_branch: feat/epic\n"
                        "workspace.parent_branch: release/2026.03\n"
                    ),
                }
            ]
        return []

    with (
        patch("atelier.worker.session.worktree.beads.run_bd_json", side_effect=fake_run_bd_json),
        patch(
            "atelier.worker.session.worktree.beads.list_descendant_changesets",
            return_value=[{"id": "at-epic.1"}],
        ),
        patch(
            "atelier.worker.session.worktree.worktrees.reconcile_mapping_ownership", return_value=()
        ),
        patch(
            "atelier.worker.session.worktree.worktrees.ensure_git_worktree",
            return_value=tmp_path / "worktrees" / "at-epic",
        ),
        patch(
            "atelier.worker.session.worktree.worktrees.ensure_changeset_branch",
            return_value=("feat/epic-at-epic.1", mapping),
        ),
        patch("atelier.worker.session.worktree.beads.update_worktree_path"),
        patch(
            "atelier.worker.session.worktree.worktrees.ensure_changeset_worktree",
            return_value=changeset_worktree_path,
        ),
        patch("atelier.worker.session.worktree.worktrees.ensure_changeset_checkout"),
        patch("atelier.worker.session.worktree.git.git_rev_parse", return_value="abc1234"),
        patch(
            "atelier.worker.session.worktree.beads.update_workspace_parent_branch"
        ) as update_parent,
        patch("atelier.worker.session.worktree.beads.update_changeset_branch_metadata"),
    ):
        worktree.prepare_worktrees(
            context=worktree.WorktreePreparationContext(
                dry_run=False,
                project_data_dir=tmp_path,
                repo_root=repo_root,
                beads_root=tmp_path / ".beads",
                selected_epic="at-epic",
                changeset_id="at-epic.1",
                root_branch_value="feat/epic",
                changeset_parent_branch="feat/epic-at-epic.0",
                allow_parent_branch_override=False,
                git_path="git",
                epic_parent_branch="main",
            ),
            control=_TestControl(logs),
        )

    update_parent.assert_not_called()
    assert any(
        "Skipped workspace.parent_branch alignment for at-epic.1: preserving existing "
        "non-root value 'release/2026.03' instead of epic parent 'main'" in line
        for line in logs
    )


def test_prepare_worktrees_skips_child_workspace_parent_alignment_on_beads_lookup_failure(
    tmp_path: Path,
) -> None:
    logs: list[str] = []
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True)
    changeset_worktree_path = tmp_path / "worktrees" / "at-epic.1"
    changeset_worktree_path.mkdir(parents=True)
    (changeset_worktree_path / ".git").write_text("gitdir: /tmp/gitdir", encoding="utf-8")
    mapping = worktrees.WorktreeMapping(
        epic_id="at-epic",
        worktree_path="worktrees/at-epic",
        root_branch="feat/epic",
        changesets={"at-epic.1": "feat/epic-at-epic.1"},
        changeset_worktrees={"at-epic.1": "worktrees/at-epic.1"},
    )
    epics = [
        {
            "id": "at-epic",
            "labels": ["at:epic"],
            "description": "workspace.root_branch: feat/epic\n",
        }
    ]

    def fake_run_bd_json(
        args: list[str],
        *,
        beads_root: Path,
        cwd: Path,
    ) -> list[dict[str, object]]:
        del beads_root, cwd
        if args[:3] == ["list", "--label", "at:epic"]:
            return epics
        if args[:2] == ["list", "--parent"] and len(args) >= 3:
            return (
                [{"id": "at-epic.1", "labels": [], "type": "task"}] if args[2] == "at-epic" else []
            )
        if args == ["show", "at-epic.1"]:
            raise SystemExit(1)
        return []

    with (
        patch("atelier.worker.session.worktree.beads.run_bd_json", side_effect=fake_run_bd_json),
        patch(
            "atelier.worker.session.worktree.beads.list_descendant_changesets",
            return_value=[{"id": "at-epic.1"}],
        ),
        patch(
            "atelier.worker.session.worktree.worktrees.reconcile_mapping_ownership", return_value=()
        ),
        patch(
            "atelier.worker.session.worktree.worktrees.ensure_git_worktree",
            return_value=tmp_path / "worktrees" / "at-epic",
        ),
        patch(
            "atelier.worker.session.worktree.worktrees.ensure_changeset_branch",
            return_value=("feat/epic-at-epic.1", mapping),
        ),
        patch("atelier.worker.session.worktree.beads.update_worktree_path"),
        patch(
            "atelier.worker.session.worktree.worktrees.ensure_changeset_worktree",
            return_value=changeset_worktree_path,
        ),
        patch("atelier.worker.session.worktree.worktrees.ensure_changeset_checkout"),
        patch("atelier.worker.session.worktree.git.git_rev_parse", return_value="abc1234"),
        patch(
            "atelier.worker.session.worktree.beads.update_workspace_parent_branch"
        ) as update_parent,
        patch("atelier.worker.session.worktree.beads.update_changeset_branch_metadata"),
    ):
        worktree.prepare_worktrees(
            context=worktree.WorktreePreparationContext(
                dry_run=False,
                project_data_dir=tmp_path,
                repo_root=repo_root,
                beads_root=tmp_path / ".beads",
                selected_epic="at-epic",
                changeset_id="at-epic.1",
                root_branch_value="feat/epic",
                changeset_parent_branch="feat/epic-at-epic.0",
                allow_parent_branch_override=False,
                git_path="git",
                epic_parent_branch="main",
            ),
            control=_TestControl(logs),
        )

    update_parent.assert_not_called()
    assert any(
        "Skipped workspace.parent_branch alignment for at-epic.1: unable to read metadata from "
        "beads (bd show exit 1)" in line
        for line in logs
    )


def test_prepare_worktrees_fail_closed_when_epic_changeset_lineage_drift_is_detected() -> None:
    logs: list[str] = []
    project_data_dir = Path("/project")
    repo_root = Path("/repo")
    mapping = worktrees.WorktreeMapping(
        epic_id="at-epic",
        worktree_path="worktrees/at-epic",
        root_branch="feat/root",
        changesets={"at-epic": "feat/root"},
        changeset_worktrees={},
    )
    stale_issue = {
        "id": "at-epic",
        "description": (
            "workspace.root_branch: feat/root\n"
            "changeset.root_branch: feat/old\n"
            "changeset.work_branch: feat/old\n"
            "pr_state: in-review\n"
            "pr_url: https://example.test/pr/7\n"
        ),
    }
    epics = [
        {
            "id": "at-epic",
            "labels": ["at:epic"],
            "description": "workspace.root_branch: feat/root\n",
        }
    ]

    def fake_run_bd_json(
        args: list[str],
        *,
        beads_root: Path,
        cwd: Path,
    ) -> list[dict[str, object]]:
        del beads_root, cwd
        if args[:3] == ["list", "--label", "at:epic"]:
            return epics
        if args[:2] == ["list", "--parent"] and len(args) >= 3 and args[2] == "at-epic":
            return []
        if args[:1] == ["show"]:
            return [stale_issue]
        raise AssertionError(f"unexpected bd command: {args!r}")

    with (
        patch("atelier.worker.session.worktree.worktrees.ensure_git_worktree") as ensure_epic,
        patch("atelier.worker.session.worktree.worktrees.ensure_changeset_branch") as ensure_branch,
        patch("atelier.worker.session.worktree.beads.update_worktree_path"),
        patch("atelier.worker.session.worktree.beads.run_bd_json", side_effect=fake_run_bd_json),
        patch("atelier.worker.session.worktree.beads.list_descendant_changesets", return_value=[]),
        patch(
            "atelier.worker.session.worktree.worktrees.reconcile_mapping_ownership", return_value=()
        ),
        patch(
            "atelier.worker.session.worktree.beads.update_changeset_branch_metadata"
        ) as update_metadata,
        patch("atelier.worker.session.worktree.worktrees.ensure_changeset_checkout"),
        patch("atelier.worker.session.worktree.git.git_rev_parse", return_value="abc1234"),
    ):
        ensure_epic.return_value = Path("/project/worktrees/at-epic")
        ensure_branch.return_value = ("feat/root", mapping)

        with pytest.raises(RuntimeError, match="startup preflight blocked"):
            worktree.prepare_worktrees(
                context=worktree.WorktreePreparationContext(
                    dry_run=False,
                    project_data_dir=project_data_dir,
                    repo_root=repo_root,
                    beads_root=Path("/beads"),
                    selected_epic="at-epic",
                    changeset_id="at-epic",
                    root_branch_value="feat/root",
                    changeset_parent_branch="main",
                    allow_parent_branch_override=False,
                    git_path="git",
                ),
                control=_TestControl(logs),
            )

    assert update_metadata.call_count == 0
    ensure_epic.assert_not_called()
    ensure_branch.assert_not_called()
    assert not logs


def test_prepare_worktrees_blocks_ambiguous_epic_changeset_lineage_drift() -> None:
    mapping = worktrees.WorktreeMapping(
        epic_id="at-epic",
        worktree_path="worktrees/at-epic",
        root_branch="feat/root",
        changesets={"at-epic": "feat/root"},
        changeset_worktrees={},
    )
    drifted_issue = {
        "id": "at-epic",
        "description": (
            "workspace.root_branch: feat/root\n"
            "changeset.root_branch: feat/one\n"
            "changeset.work_branch: feat/two\n"
        ),
    }
    checkout = Mock()
    epics = [
        {
            "id": "at-epic",
            "labels": ["at:epic"],
            "description": "workspace.root_branch: feat/root\n",
        }
    ]

    def fake_run_bd_json(
        args: list[str],
        *,
        beads_root: Path,
        cwd: Path,
    ) -> list[dict[str, object]]:
        del beads_root, cwd
        if args[:3] == ["list", "--label", "at:epic"]:
            return epics
        if args[:2] == ["list", "--parent"] and len(args) >= 3 and args[2] == "at-epic":
            return []
        if args[:1] == ["show"]:
            return [drifted_issue]
        raise AssertionError(f"unexpected bd command: {args!r}")

    with (
        patch(
            "atelier.worker.session.worktree.worktrees.ensure_git_worktree",
            return_value=Path("/project/worktrees/at-epic"),
        ),
        patch(
            "atelier.worker.session.worktree.worktrees.ensure_changeset_branch",
            return_value=("feat/root", mapping),
        ),
        patch("atelier.worker.session.worktree.beads.update_worktree_path"),
        patch("atelier.worker.session.worktree.beads.run_bd_json", side_effect=fake_run_bd_json),
        patch("atelier.worker.session.worktree.beads.list_descendant_changesets", return_value=[]),
        patch(
            "atelier.worker.session.worktree.worktrees.reconcile_mapping_ownership", return_value=()
        ),
        patch("atelier.worker.session.worktree.beads.update_changeset_branch_metadata") as update,
        patch("atelier.worker.session.worktree.worktrees.ensure_changeset_checkout", checkout),
    ):
        with pytest.raises(RuntimeError, match="startup preflight blocked"):
            worktree.prepare_worktrees(
                context=worktree.WorktreePreparationContext(
                    dry_run=False,
                    project_data_dir=Path("/project"),
                    repo_root=Path("/repo"),
                    beads_root=Path("/beads"),
                    selected_epic="at-epic",
                    changeset_id="at-epic",
                    root_branch_value="feat/root",
                    changeset_parent_branch="main",
                    allow_parent_branch_override=False,
                    git_path="git",
                ),
                control=_TestControl([]),
            )

    update.assert_not_called()
    checkout.assert_not_called()

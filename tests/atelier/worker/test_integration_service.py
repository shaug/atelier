from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

from atelier import worktrees
from atelier.worker import integration_service


def test_resolve_epic_integration_cwd_uses_legacy_owner_mapping_lookup() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp)
        meta_dir = worktrees.worktrees_root(project_dir) / worktrees.METADATA_DIRNAME
        meta_dir.mkdir(parents=True, exist_ok=True)
        worktrees.write_mapping(
            worktrees.mapping_path(project_dir, "at-legacy"),
            worktrees.WorktreeMapping(
                epic_id="at-legacy",
                worktree_path="worktrees/at-legacy",
                root_branch="feat/root",
                changesets={"ts-new": "feat/root"},
                changeset_worktrees={},
            ),
        )
        expected_path = project_dir / "worktrees/at-legacy"
        expected_path.mkdir(parents=True, exist_ok=True)
        (expected_path / ".git").write_text(
            "gitdir: /repo/.git/worktrees/at-legacy\n",
            encoding="utf-8",
        )

        with patch(
            "atelier.worker.integration_service.git.git_current_branch",
            return_value="feat/root",
        ):
            resolved = integration_service.resolve_epic_integration_cwd(
                project_data_dir=project_dir,
                repo_root=Path("/repo"),
                epic_id="ts-new",
                root_branch="feat/root",
            )

    assert resolved == expected_path


def test_resolve_epic_integration_cwd_fails_closed_on_ambiguous_owner_lookup() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp)
        meta_dir = worktrees.worktrees_root(project_dir) / worktrees.METADATA_DIRNAME
        meta_dir.mkdir(parents=True, exist_ok=True)
        for epic_id in ("at-legacy-a", "at-legacy-b"):
            worktrees.write_mapping(
                worktrees.mapping_path(project_dir, epic_id),
                worktrees.WorktreeMapping(
                    epic_id=epic_id,
                    worktree_path=f"worktrees/{epic_id}",
                    root_branch="feat/root",
                    changesets={"ts-new": f"feat/root-{epic_id}"},
                    changeset_worktrees={},
                ),
            )

        with patch("atelier.worker.integration_service.git.git_current_branch") as current_branch:
            resolved = integration_service.resolve_epic_integration_cwd(
                project_data_dir=project_dir,
                repo_root=Path("/repo"),
                epic_id="ts-new",
                root_branch="feat/root",
            )

    assert resolved == Path("/repo")
    current_branch.assert_not_called()


def test_resolve_changeset_worktree_path_uses_legacy_owner_mapping_lookup() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp)
        meta_dir = worktrees.worktrees_root(project_dir) / worktrees.METADATA_DIRNAME
        meta_dir.mkdir(parents=True, exist_ok=True)
        worktrees.write_mapping(
            worktrees.mapping_path(project_dir, "at-legacy"),
            worktrees.WorktreeMapping(
                epic_id="at-legacy",
                worktree_path="worktrees/at-legacy",
                root_branch="feat/root",
                changesets={"ts-new.1": "feat/root-ts-new.1"},
                changeset_worktrees={"ts-new.1": "worktrees/at-legacy.1"},
            ),
        )
        expected_path = project_dir / "worktrees/at-legacy.1"
        expected_path.mkdir(parents=True, exist_ok=True)
        (expected_path / ".git").write_text(
            "gitdir: /repo/.git/worktrees/at-legacy.1\n",
            encoding="utf-8",
        )

        resolved = integration_service.resolve_changeset_worktree_path(
            project_data_dir=project_dir,
            epic_id="ts-new",
            changeset_id="ts-new.1",
        )

    assert resolved == expected_path


def test_resolve_changeset_worktree_path_fails_closed_on_ambiguous_owner_lookup() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp)
        meta_dir = worktrees.worktrees_root(project_dir) / worktrees.METADATA_DIRNAME
        meta_dir.mkdir(parents=True, exist_ok=True)
        for epic_id in ("at-legacy-a", "at-legacy-b"):
            worktrees.write_mapping(
                worktrees.mapping_path(project_dir, epic_id),
                worktrees.WorktreeMapping(
                    epic_id=epic_id,
                    worktree_path=f"worktrees/{epic_id}",
                    root_branch="feat/root",
                    changesets={"ts-new.1": f"feat/root-{epic_id}.1"},
                    changeset_worktrees={"ts-new.1": f"worktrees/{epic_id}.1"},
                ),
            )

        resolved = integration_service.resolve_changeset_worktree_path(
            project_data_dir=project_dir,
            epic_id="ts-new",
            changeset_id="ts-new.1",
        )

    assert resolved is None

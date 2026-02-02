import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import atelier.worktrees as worktrees


def test_derive_changeset_branch_from_hierarchy() -> None:
    assert worktrees.derive_changeset_branch("epic", "epic.2") == "epic-2"


def test_ensure_changeset_branch_writes_mapping() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp)
        branch, mapping = worktrees.ensure_changeset_branch(
            project_dir, "epic", "epic.1"
        )
        assert branch == "epic-1"
        mapping_file = worktrees.mapping_path(project_dir, "epic")
        assert mapping_file.exists()
        payload = json.loads(mapping_file.read_text(encoding="utf-8"))
        assert payload["epic_id"] == "epic"
        assert payload["changesets"]["epic.1"] == "epic-1"
        assert mapping.worktree_path == "worktrees/epic"


def test_ensure_git_worktree_creates_when_missing() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp) / "project"
        repo_root = Path(tmp) / "repo"
        project_dir.mkdir(parents=True)
        repo_root.mkdir(parents=True)

        def fake_ref_exists(
            _repo: Path, ref: str, *, git_path: str | None = None
        ) -> bool:
            return ref == "refs/remotes/origin/main"

        with (
            patch(
                "atelier.worktrees.git.git_default_branch", return_value="main"
            ),
            patch(
                "atelier.worktrees.git.git_ref_exists", side_effect=fake_ref_exists
            ),
            patch("atelier.worktrees.exec_util.run_command") as run_command,
        ):
            worktree_path = worktrees.ensure_git_worktree(
                project_dir, repo_root, "epic"
            )

        assert worktree_path == project_dir / "worktrees" / "epic"
        assert run_command.called


def test_remove_git_worktree_noop_when_missing() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp) / "project"
        repo_root = Path(tmp) / "repo"
        project_dir.mkdir(parents=True)
        repo_root.mkdir(parents=True)
        with patch("atelier.worktrees.exec_util.run_command") as run_command:
            removed = worktrees.remove_git_worktree(project_dir, repo_root, "epic")
        assert removed is False
        assert not run_command.called


def test_remove_git_worktree_calls_git_remove() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp) / "project"
        repo_root = Path(tmp) / "repo"
        project_dir.mkdir(parents=True)
        repo_root.mkdir(parents=True)
        mapping = worktrees.ensure_worktree_mapping(project_dir, "epic")
        worktree_path = project_dir / mapping.worktree_path
        worktree_path.mkdir(parents=True)
        (worktree_path / ".git").write_text("gitdir: /tmp\n", encoding="utf-8")

        with patch("atelier.worktrees.exec_util.run_command") as run_command:
            removed = worktrees.remove_git_worktree(project_dir, repo_root, "epic")

        assert removed is True
        assert run_command.called

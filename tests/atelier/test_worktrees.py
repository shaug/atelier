import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import atelier.worktrees as worktrees


def test_derive_changeset_branch_uses_root_branch() -> None:
    assert (
        worktrees.derive_changeset_branch("feat/root", "epic.2") == "feat/root-epic.2"
    )


def test_ensure_changeset_branch_writes_mapping() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp)
        branch, mapping = worktrees.ensure_changeset_branch(
            project_dir, "epic", "epic.1", root_branch="feat/root"
        )
        assert branch == "feat/root-epic.1"
        mapping_file = worktrees.mapping_path(project_dir, "epic")
        assert mapping_file.exists()
        payload = json.loads(mapping_file.read_text(encoding="utf-8"))
        assert payload["epic_id"] == "epic"
        assert payload["root_branch"] == "feat/root"
        assert payload["changesets"]["epic.1"] == "feat/root-epic.1"
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
            patch("atelier.worktrees.git.git_default_branch", return_value="main"),
            patch("atelier.worktrees.git.git_ref_exists", side_effect=fake_ref_exists),
            patch("atelier.worktrees.exec_util.run_command") as run_command,
        ):
            worktree_path = worktrees.ensure_git_worktree(
                project_dir, repo_root, "epic", root_branch="feat/root"
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
        mapping = worktrees.ensure_worktree_mapping(project_dir, "epic", "feat/root")
        worktree_path = project_dir / mapping.worktree_path
        worktree_path.mkdir(parents=True)
        (worktree_path / ".git").write_text("gitdir: /tmp\n", encoding="utf-8")

        with patch("atelier.worktrees.exec_util.run_command") as run_command:
            removed = worktrees.remove_git_worktree(project_dir, repo_root, "epic")

        assert removed is True
        assert run_command.called


def test_ensure_changeset_checkout_creates_branches() -> None:
    worktree_path = Path("/repo/worktree")
    calls: list[list[str]] = []

    def fake_ref_exists(_repo: Path, ref: str, *, git_path: str | None = None) -> bool:
        if ref == "refs/remotes/origin/feat/root":
            return True
        return False

    def fake_run(cmd: list[str]) -> None:
        calls.append(cmd)

    with (
        patch("atelier.worktrees.git.git_default_branch", return_value="main"),
        patch("atelier.worktrees.git.git_ref_exists", side_effect=fake_ref_exists),
        patch("atelier.worktrees.exec_util.run_command", side_effect=fake_run),
        patch("atelier.worktrees.Path.exists", return_value=True),
    ):
        worktrees.ensure_changeset_checkout(
            worktree_path,
            "feat/root-epic.1",
            root_branch="feat/root",
        )

    assert calls
    assert any("checkout" in item for item in calls[0])
    assert any("checkout" in item for item in calls[-1])

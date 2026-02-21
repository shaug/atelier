from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

import pytest

import atelier.integration as integration


def test_integrate_changeset_updates_root_with_cas(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    worktree_path = tmp_path / "worktree"
    repo_root.mkdir(parents=True)
    worktree_path.mkdir(parents=True)
    (worktree_path / ".git").write_text("gitdir: /tmp\n", encoding="utf-8")

    calls: list[list[str]] = []

    def fake_run(cmd: list[str], cwd: Path | None = None, env: dict | None = None) -> None:
        calls.append(cmd)

    def fake_try_run(cmd: list[str], cwd: Path | None = None, env: dict | None = None):
        return CompletedProcess(cmd, 0, "", "")

    def fake_rev_parse(repo: Path, ref: str, *, git_path: str | None = None) -> str | None:
        if ref == "main":
            return "oldsha"
        if ref == "work-branch":
            return "newsha"
        return None

    with (
        patch("atelier.integration.exec_util.run_command", side_effect=fake_run),
        patch("atelier.integration.exec_util.try_run_command", side_effect=fake_try_run),
        patch("atelier.integration.git.git_rev_parse", side_effect=fake_rev_parse),
        patch("atelier.integration.beads.update_changeset_integrated_sha") as update_sha,
    ):
        result = integration.integrate_changeset(
            changeset_id="epic.1",
            worktree_path=worktree_path,
            repo_root=repo_root,
            root_branch="main",
            work_branch="work-branch",
            beads_root=Path("/beads"),
        )

    assert result.integrated_sha == "newsha"
    assert any("rebase" in cmd for cmd in calls)
    update_sha.assert_called_once_with("epic.1", "newsha", beads_root=Path("/beads"), cwd=repo_root)


def test_integrate_changeset_raises_on_cas_mismatch(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    worktree_path = tmp_path / "worktree"
    repo_root.mkdir(parents=True)
    worktree_path.mkdir(parents=True)
    (worktree_path / ".git").write_text("gitdir: /tmp\n", encoding="utf-8")

    def fake_try_run(cmd: list[str], cwd: Path | None = None, env: dict | None = None):
        return CompletedProcess(cmd, 1, "", "")

    def fake_rev_parse(repo: Path, ref: str, *, git_path: str | None = None) -> str | None:
        if ref == "main":
            return "oldsha"
        if ref == "work-branch":
            return "newsha"
        return None

    with (
        patch("atelier.integration.exec_util.run_command"),
        patch("atelier.integration.exec_util.try_run_command", side_effect=fake_try_run),
        patch("atelier.integration.git.git_rev_parse", side_effect=fake_rev_parse),
        patch("atelier.integration.beads.update_changeset_integrated_sha") as update_sha,
    ):
        with pytest.raises(SystemExit):
            integration.integrate_changeset(
                changeset_id="epic.1",
                worktree_path=worktree_path,
                repo_root=repo_root,
                root_branch="main",
                work_branch="work-branch",
                beads_root=Path("/beads"),
            )

    update_sha.assert_not_called()

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

import atelier.git as git


def _run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("github.com/owner/repo", "github.com/owner/repo"),
        ("https://github.com/owner/repo.git", "github.com/owner/repo"),
        ("git@github.com:owner/repo.git", "github.com/owner/repo"),
        ("ssh://git@github.com/owner/repo.git", "github.com/owner/repo"),
    ],
)
def test_normalize_origin_url(value: str, expected: str) -> None:
    assert git.normalize_origin_url(value) == expected


def test_git_is_ancestor_handles_status_codes() -> None:
    with patch(
        "atelier.git._run_git_or_die",
        return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout=""),
    ):
        assert git.git_is_ancestor(Path("/repo"), "a", "b") is True
    with patch(
        "atelier.git._run_git_or_die",
        return_value=subprocess.CompletedProcess(args=[], returncode=1, stdout=""),
    ):
        assert git.git_is_ancestor(Path("/repo"), "a", "b") is False
    with patch(
        "atelier.git._run_git_or_die",
        return_value=subprocess.CompletedProcess(args=[], returncode=128, stdout=""),
    ):
        assert git.git_is_ancestor(Path("/repo"), "a", "b") is None


def test_git_branch_fully_applied_uses_git_cherry_output() -> None:
    with patch(
        "atelier.git._run_git_or_die",
        return_value=subprocess.CompletedProcess(
            args=[], returncode=0, stdout="- abcdef message\n- 123456 message\n"
        ),
    ):
        assert git.git_branch_fully_applied(Path("/repo"), "root", "work") is True
    with patch(
        "atelier.git._run_git_or_die",
        return_value=subprocess.CompletedProcess(
            args=[], returncode=0, stdout="- abcdef message\n+ 123456 message\n"
        ),
    ):
        assert git.git_branch_fully_applied(Path("/repo"), "root", "work") is False
    with patch(
        "atelier.git._run_git_or_die",
        return_value=subprocess.CompletedProcess(args=[], returncode=128, stdout=""),
    ):
        assert git.git_branch_fully_applied(Path("/repo"), "root", "work") is None


def test_resolve_enlistment_path_uses_git_common_dir_parent() -> None:
    with patch(
        "atelier.git._run_git_or_die",
        return_value=subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="/tmp/enlistment/.git\n",
        ),
    ):
        enlistment_path = git.resolve_enlistment_path(Path("/tmp/enlistment/worktrees/at-1"))
        assert Path(enlistment_path) == Path("/tmp/enlistment").resolve()


def test_resolve_enlistment_path_forwards_git_path_to_git_command() -> None:
    with (
        patch("atelier.git.git_command", return_value=["/custom/git"]) as git_command_mock,
        patch(
            "atelier.git._run_git_or_die",
            return_value=subprocess.CompletedProcess(
                args=[],
                returncode=1,
                stdout="",
            ),
        ),
    ):
        git.resolve_enlistment_path(
            Path("/tmp/enlistment/worktrees/at-1"),
            git_path="/usr/local/bin/git",
        )

    git_command_call = git_command_mock.call_args
    assert git_command_call is not None
    assert git_command_call.kwargs["git_path"] == "/usr/local/bin/git"


def test_resolve_repo_enlistment_uses_canonical_path_for_linked_worktree(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True)
    _run_git(repo_root, "init")
    _run_git(repo_root, "config", "user.email", "test@example.com")
    _run_git(repo_root, "config", "user.name", "Test User")
    (repo_root / "README.md").write_text("seed\n", encoding="utf-8")
    _run_git(repo_root, "add", "README.md")
    _run_git(repo_root, "commit", "-m", "seed")

    worktree_root = tmp_path / "linked-worktree"
    _run_git(repo_root, "worktree", "add", "-b", "feature/worktree", str(worktree_root), "HEAD")

    resolved_repo_root, enlistment_path, origin_raw, origin = git.resolve_repo_enlistment(
        worktree_root
    )

    assert resolved_repo_root == worktree_root.resolve()
    assert enlistment_path == str(repo_root.resolve())
    assert origin_raw is None
    assert origin is None


def test_resolve_repo_enlistment_forwards_git_path_to_enlistment_resolution() -> None:
    repo_root = Path("/tmp/repo")
    with (
        patch("atelier.git.git_repo_root", return_value=repo_root),
        patch(
            "atelier.git.resolve_enlistment_path",
            return_value=str(repo_root),
        ) as resolve_enlistment_path,
        patch("atelier.git.git_origin_url", return_value=None),
    ):
        resolved_repo_root, enlistment_path, origin_raw, origin = git.resolve_repo_enlistment(
            Path("/tmp/repo/worktrees/at-1"),
            git_path="/usr/local/bin/git",
        )

    resolve_enlistment_path.assert_called_once_with(
        repo_root,
        git_path="/usr/local/bin/git",
    )
    assert resolved_repo_root == repo_root
    assert enlistment_path == str(repo_root)
    assert origin_raw is None
    assert origin is None

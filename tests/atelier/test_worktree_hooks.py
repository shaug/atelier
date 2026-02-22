from __future__ import annotations

from pathlib import Path
from subprocess import CompletedProcess
from tempfile import TemporaryDirectory
from unittest.mock import patch

from atelier import worktree_hooks


def _git_result(stdout: str) -> CompletedProcess[str]:
    return CompletedProcess(args=["git"], returncode=0, stdout=stdout, stderr="")


def test_bootstrap_conventional_commit_hook_installs_managed_hook() -> None:
    with TemporaryDirectory() as tmp:
        repo_root = Path(tmp) / "repo"
        worktree_path = repo_root / "worktree"
        hooks_dir = repo_root / ".git" / "hooks"
        hooks_dir.mkdir(parents=True)
        worktree_path.mkdir(parents=True)
        (worktree_path / ".git").write_text("gitdir: /tmp/gitdir\n", encoding="utf-8")
        (repo_root / "commitlint.config.cjs").write_text("module.exports = {};\n", encoding="utf-8")
        existing_hook = hooks_dir / "commit-msg"
        existing_hook.write_text("#!/bin/sh\necho legacy\n", encoding="utf-8")

        def fake_try_run(command: list[str], **_kwargs: object) -> CompletedProcess[str] | None:
            if "--show-toplevel" in command:
                return _git_result(f"{repo_root}\n")
            if "--git-path" in command:
                return _git_result(f"{hooks_dir}\n")
            raise AssertionError(f"unexpected command: {command}")

        with patch("atelier.worktree_hooks.exec_util.try_run_command", side_effect=fake_try_run):
            worktree_hooks.bootstrap_conventional_commit_hook(worktree_path, git_path="git")

        legacy_hook = hooks_dir / "commit-msg.atelier-legacy"
        managed_hook = hooks_dir / "commit-msg"
        assert legacy_hook.exists()
        assert managed_hook.exists()
        assert "ATELIER-MANAGED-COMMIT-MSG" in managed_hook.read_text(encoding="utf-8")
        assert managed_hook.stat().st_mode & 0o111


def test_bootstrap_conventional_commit_hook_skips_without_commitlint_config() -> None:
    with TemporaryDirectory() as tmp:
        repo_root = Path(tmp) / "repo"
        worktree_path = repo_root / "worktree"
        hooks_dir = repo_root / ".git" / "hooks"
        hooks_dir.mkdir(parents=True)
        worktree_path.mkdir(parents=True)
        (worktree_path / ".git").write_text("gitdir: /tmp/gitdir\n", encoding="utf-8")
        hook_path = hooks_dir / "commit-msg"
        hook_path.write_text("legacy\n", encoding="utf-8")

        def fake_try_run(command: list[str], **_kwargs: object) -> CompletedProcess[str] | None:
            if "--show-toplevel" in command:
                return _git_result(f"{repo_root}\n")
            if "--git-path" in command:
                return _git_result(f"{hooks_dir}\n")
            raise AssertionError(f"unexpected command: {command}")

        with patch("atelier.worktree_hooks.exec_util.try_run_command", side_effect=fake_try_run):
            worktree_hooks.bootstrap_conventional_commit_hook(worktree_path, git_path="git")

        assert hook_path.read_text(encoding="utf-8") == "legacy\n"
        assert not (hooks_dir / "commit-msg.atelier-legacy").exists()

"""Git hook bootstrap helpers for Atelier-managed worktrees."""

from __future__ import annotations

from pathlib import Path

from . import exec as exec_util
from . import git
from .io import die

_COMMIT_MSG_MARKER = "ATELIER-MANAGED-COMMIT-MSG"
_COMMITLINT_CONFIG_FILES: tuple[str, ...] = (
    "commitlint.config.cjs",
    "commitlint.config.js",
    ".commitlintrc",
    ".commitlintrc.json",
    ".commitlintrc.yaml",
    ".commitlintrc.yml",
)
_MANAGED_COMMIT_MSG_HOOK = f"""#!/bin/sh
# {_COMMIT_MSG_MARKER}
set -eu

HOOK_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
LEGACY_HOOK="$HOOK_DIR/commit-msg.atelier-legacy"

if [ -x "$LEGACY_HOOK" ]; then
  "$LEGACY_HOOK" "$@" || exit $?
fi

if ! command -v atelier >/dev/null 2>&1; then
  echo "Atelier commit-msg hook: 'atelier' command not found in PATH." >&2
  exit 1
fi

if [ "$#" -lt 1 ]; then
  echo "Atelier commit-msg hook expected a commit message file path." >&2
  exit 1
fi

atelier hook commit-msg --message-file "$1"
"""


def _run_git_capture(worktree_path: Path, args: list[str], *, git_path: str | None) -> str:
    command = git.git_command(["-C", str(worktree_path), *args], git_path=git_path)
    result = exec_util.try_run_command(command)
    if result is None:
        die("missing required command: git")
    if result.returncode != 0:
        output = (result.stderr or result.stdout or "").strip()
        details = f"\n{output}" if output else ""
        die(f"command failed: {' '.join(command)}{details}")
    return result.stdout.strip()


def _resolve_git_path_target(worktree_path: Path, suffix: str, *, git_path: str | None) -> Path:
    raw_path = _run_git_capture(
        worktree_path,
        ["rev-parse", "--git-path", suffix],
        git_path=git_path,
    )
    if not raw_path:
        die(f"failed to resolve git path for {suffix!r}")
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return worktree_path / path


def _repo_supports_commitlint(worktree_path: Path, *, git_path: str | None) -> bool:
    repo_root_raw = _run_git_capture(
        worktree_path,
        ["rev-parse", "--show-toplevel"],
        git_path=git_path,
    )
    repo_root = Path(repo_root_raw)
    return any((repo_root / config_name).exists() for config_name in _COMMITLINT_CONFIG_FILES)


def bootstrap_conventional_commit_hook(worktree_path: Path, *, git_path: str | None = None) -> None:
    """Install a managed conventional-commit ``commit-msg`` hook.

    The managed hook composes with an existing ``commit-msg`` hook by moving the
    existing implementation to ``commit-msg.atelier-legacy`` and delegating to
    it before Atelier's validator runs.

    Args:
        worktree_path: Path to the target git worktree.
        git_path: Optional git executable override.

    Returns:
        None.
    """
    if not (worktree_path / ".git").exists():
        return
    if not _repo_supports_commitlint(worktree_path, git_path=git_path):
        return

    hooks_dir = _resolve_git_path_target(worktree_path, "hooks", git_path=git_path)
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hook_path = hooks_dir / "commit-msg"
    legacy_path = hooks_dir / "commit-msg.atelier-legacy"

    if hook_path.exists():
        current = hook_path.read_text(encoding="utf-8")
        if _COMMIT_MSG_MARKER not in current:
            hook_path.replace(legacy_path)

    hook_path.write_text(_MANAGED_COMMIT_MSG_HOOK, encoding="utf-8")
    hook_path.chmod(0o755)

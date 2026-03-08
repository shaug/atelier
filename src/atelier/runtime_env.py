"""Runtime environment sanitization helpers for spawned subprocesses."""

from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Sequence

_WARNING_SAMPLE_LIMIT = 6
_PROJECTED_RUNTIME_SELECTED_ENV = "ATELIER_PROJECTED_RUNTIME_SELECTED"

USER_DEFAULT_ENV_KEYS: frozenset[str] = frozenset(
    {
        "ATELIER_MODE",
        "ATELIER_RUN_MODE",
        "ATELIER_WATCH_INTERVAL",
        "ATELIER_WORK_YES",
        "ATELIER_PLAN_TRACE",
        "ATELIER_WORK_TRACE",
        "ATELIER_WORK_AGENT_TRACE",
        "ATELIER_LOG_LEVEL",
        "ATELIER_NO_COLOR",
        "ATELIER_STARTUP_DEFERRED_EPIC_SCAN_LIMIT",
    }
)


def sanitize_subprocess_environment(
    *,
    base_env: Mapping[str, str] | None = None,
    preserve_keys: Iterable[str] = (),
) -> tuple[dict[str, str], tuple[str, ...]]:
    """Return a subprocess environment without inherited runtime-routing keys.

    Args:
        base_env: Optional source environment map. When omitted, current process
            environment is used.
        preserve_keys: Additional ``ATELIER_*`` keys that must survive
            sanitization.

    Returns:
        Tuple of ``(sanitized_env, removed_keys)`` where ``removed_keys`` are
        the inherited ``ATELIER_*`` runtime-routing variables dropped from the
        environment before launch.
    """
    env = dict(os.environ if base_env is None else base_env)
    allowed = set(USER_DEFAULT_ENV_KEYS)
    allowed.update(str(key) for key in preserve_keys if str(key).strip())
    removed: list[str] = []
    for key in sorted(env):
        if not key.startswith("ATELIER_"):
            continue
        if key in allowed:
            continue
        removed.append(key)
    for key in removed:
        env.pop(key, None)
    return env, tuple(removed)


def format_ambient_env_warning(removed_keys: Iterable[str]) -> str | None:
    """Build a warning for dropped inherited runtime env keys.

    Args:
        removed_keys: Iterable of removed ``ATELIER_*`` key names.

    Returns:
        User-facing warning text when keys were removed; otherwise ``None``.
    """
    unique = sorted({key for key in removed_keys if key})
    if not unique:
        return None
    sample = ", ".join(unique[:_WARNING_SAMPLE_LIMIT])
    suffix = ""
    if len(unique) > _WARNING_SAMPLE_LIMIT:
        suffix = f", +{len(unique) - _WARNING_SAMPLE_LIMIT} more"
    return (
        "Warning: ignored inherited runtime routing env keys "
        f"({sample}{suffix}). "
        "Use explicit launch context (for example --repo-dir or the local "
        "./worktree link) instead of ambient ATELIER_* routing state."
    )


def projected_repo_python_command(
    *,
    repo_root: Path,
    base_env: Mapping[str, str] | None = None,
    current_executable: str | None = None,
) -> tuple[str, ...] | None:
    """Resolve a deterministic Python command for projected source scripts.

    Projected skill scripts can safely bootstrap repo source imports via
    ``sys.path`` edits, but that alone does not guarantee the interpreter's
    dependency set matches the repo checkout. This resolver prefers the repo's
    own ``.venv`` Python, then falls back to ``uv run --project <repo> python``
    when the checkout has a ``pyproject.toml`` and ``uv`` is available.

    Args:
        repo_root: Repo root containing the projected ``src/atelier`` tree.
        base_env: Optional environment map used for command lookup.
        current_executable: Optional active Python executable path.

    Returns:
        ``None`` when the current interpreter already matches the repo runtime
        or when no deterministic repo runtime is available; otherwise a command
        prefix suitable for ``os.execvpe``.
    """
    repo_python = _repo_python_candidate(repo_root)
    current = str(current_executable or sys.executable or "").strip()
    if repo_python is not None:
        if _same_executable_path(current, repo_python):
            return None
        return (str(repo_python),)

    if not (repo_root / "pyproject.toml").is_file():
        return None

    env = dict(os.environ if base_env is None else base_env)
    uv_path = shutil.which("uv", path=env.get("PATH"))
    if not uv_path:
        return None
    return (uv_path, "run", "--project", str(repo_root), "python")


def maybe_reexec_projected_repo_runtime(
    *,
    repo_root: Path | None,
    script_path: Path,
    argv: Sequence[str] | None = None,
    base_env: Mapping[str, str] | None = None,
    current_executable: str | None = None,
) -> None:
    """Re-exec a projected script into the repo runtime when required.

    This is used by projected planner scripts that may be launched with an
    ambient interpreter such as a tool-install Python. In that case the script
    must switch to the repo runtime before importing ``atelier`` modules with
    compiled/runtime dependencies like ``pydantic_core``.

    Args:
        repo_root: Resolved repo root discovered by the standalone bootstrap.
        script_path: Concrete script path that should be re-executed.
        argv: Optional script arguments excluding the interpreter and script
            path. Defaults to ``sys.argv[1:]``.
        base_env: Optional environment map used for the re-exec.
        current_executable: Optional active Python executable path.
    """
    if repo_root is None:
        return

    env = dict(os.environ if base_env is None else base_env)
    if env.get(_PROJECTED_RUNTIME_SELECTED_ENV) == "1":
        return

    command = projected_repo_python_command(
        repo_root=repo_root,
        base_env=env,
        current_executable=current_executable,
    )
    if command is None:
        return

    exec_env = dict(env)
    exec_env[_PROJECTED_RUNTIME_SELECTED_ENV] = "1"
    script_args = list(sys.argv[1:] if argv is None else argv)
    os.execvpe(
        command[0],
        [*command, str(script_path), *script_args],
        exec_env,
    )


def _repo_python_candidate(repo_root: Path) -> Path | None:
    for relative_path in (
        Path(".venv/bin/python3"),
        Path(".venv/bin/python"),
        Path(".venv/Scripts/python.exe"),
    ):
        candidate = repo_root / relative_path
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate.resolve()
    return None


def _same_executable_path(current_executable: str, candidate: Path) -> bool:
    current = current_executable.strip()
    if not current:
        return False
    try:
        return Path(current).resolve() == candidate.resolve()
    except OSError:
        return False

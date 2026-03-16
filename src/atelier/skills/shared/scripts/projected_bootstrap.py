"""Shared bootstrap for projected skill scripts that import ``atelier``."""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

_DEFAULT_REPO_DIR_ENV_VARS: tuple[str, ...] = (
    "ATELIER_PLANNER_WORKTREE",
    "ATELIER_WORKSPACE_DIR",
    "ATELIER_PROJECT",
)


def _repo_dir_from_argv(argv: Sequence[str]) -> Path | None:
    """Return an explicit ``--repo-dir`` argument when present.

    Args:
        argv: Command-line arguments excluding the interpreter and script path.

    Returns:
        Expanded repo path when ``--repo-dir`` is present, otherwise ``None``.
    """
    for index, token in enumerate(argv):
        if token == "--repo-dir" and index + 1 < len(argv):
            value = argv[index + 1].strip()
            if value:
                return Path(value).expanduser()
        if token.startswith("--repo-dir="):
            value = token.split("=", 1)[1].strip()
            if value:
                return Path(value).expanduser()
    return None


def _bootstrap_source_import(
    *,
    script_path: Path,
    argv: Sequence[str],
    env: Mapping[str, str],
    repo_dir_env_vars: Sequence[str],
) -> Path | None:
    candidate_roots: list[Path] = []
    argv_repo_dir = _repo_dir_from_argv(argv)
    if argv_repo_dir is not None:
        candidate_roots.append(argv_repo_dir)

    current_dir = Path.cwd()
    candidate_roots.append(current_dir / "worktree")
    for env_var in repo_dir_env_vars:
        env_repo_dir = str(env.get(env_var, "")).strip()
        if env_repo_dir:
            candidate_roots.append(Path(env_repo_dir).expanduser())
    candidate_roots.append(current_dir)
    candidate_roots.extend(script_path.resolve().parents)

    seen: set[Path] = set()
    for root in candidate_roots:
        resolved = root.expanduser().resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        src_dir = resolved / "src"
        if not (src_dir / "atelier" / "__init__.py").is_file():
            continue
        src_dir_entry = str(src_dir)
        sys.path[:] = [entry for entry in sys.path if entry != src_dir_entry]
        sys.path.insert(0, src_dir_entry)
        return resolved
    return None


def bootstrap_projected_atelier_script(
    *,
    script_path: Path,
    argv: Sequence[str] | None = None,
    env: Mapping[str, str] | None = None,
    repo_dir_env_vars: Sequence[str] = _DEFAULT_REPO_DIR_ENV_VARS,
    require_runtime_health: bool = True,
) -> Path | None:
    """Prepare a projected skill script to import repo ``atelier`` code safely.

    The projected runtime policy for this bootstrap flow is defined by
    ``atelier.runtime_env.projected_runtime_contract``.

    Args:
        script_path: Concrete projected script file path.
        argv: Optional command-line arguments excluding interpreter and script.
            Defaults to ``sys.argv[1:]``.
        env: Optional environment mapping used to resolve repo hints.
            Defaults to ``os.environ``.
        repo_dir_env_vars: Environment keys that may contain a repo/worktree
            path for projected agent homes.
        require_runtime_health: When true, re-exec into the repo runtime when
            required and fail closed if the selected interpreter cannot import
            compiled runtime dependencies.

    Returns:
        Resolved repo root when source bootstrap succeeds, otherwise ``None``.
    """
    resolved_env = dict(os.environ if env is None else env)
    resolved_argv = tuple(sys.argv[1:] if argv is None else argv)
    repo_root = _bootstrap_source_import(
        script_path=script_path,
        argv=resolved_argv,
        env=resolved_env,
        repo_dir_env_vars=repo_dir_env_vars,
    )

    from atelier.runtime_env import (
        ProjectedRuntimeMode,
        ensure_projected_runtime_dependency,
        maybe_reexec_projected_repo_runtime,
        projected_runtime_contract,
        reset_current_process_pythonpath,
        sanitize_pythonpath_environment,
    )

    contract = projected_runtime_contract(repo_root=repo_root)
    resolved_env, removed_pythonpath = sanitize_pythonpath_environment(base_env=resolved_env)
    preserve_paths: tuple[str, ...] = ()
    if contract.preferred_mode is ProjectedRuntimeMode.REPO_SOURCE and repo_root is not None:
        preserve_paths = (str(repo_root / "src"),)
    reset_current_process_pythonpath(
        removed_pythonpath,
        preserve_paths=preserve_paths,
    )

    if require_runtime_health:
        maybe_reexec_projected_repo_runtime(
            repo_root=repo_root,
            script_path=script_path,
            argv=resolved_argv,
            base_env=resolved_env,
        )
        ensure_projected_runtime_dependency(
            repo_root=repo_root,
            script_path=script_path,
            base_env=resolved_env,
        )
    return repo_root

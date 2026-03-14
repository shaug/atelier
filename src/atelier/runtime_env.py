"""Runtime environment sanitization helpers for spawned subprocesses."""

from __future__ import annotations

import importlib
import os
import shutil
import sys
import sysconfig
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

_WARNING_SAMPLE_LIMIT = 6
_PROJECTED_RUNTIME_SELECTED_ENV = "ATELIER_PROJECTED_RUNTIME_SELECTED"
_PROJECTED_RUNTIME_DEPENDENCY = "pydantic_core._pydantic_core"
_PROJECTED_RUNTIME_PROVENANCE_MODULES: tuple[str, ...] = (
    "pydantic",
    "pydantic_core",
    _PROJECTED_RUNTIME_DEPENDENCY,
)
_INSTALLED_TOOL_RUNTIME_MARKERS: tuple[str, ...] = (
    "/.local/share/uv/tools/atelier/",
    "/Library/Application Support/uv/tools/atelier/",
    "/site-packages/atelier/",
)
_PYTHONPATH_ENV = "PYTHONPATH"

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


@dataclass(frozen=True)
class _ProjectedRuntimeProvenanceIssue:
    module_name: str
    module_path: str
    expected_roots: tuple[str, ...]


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


def sanitize_pythonpath_environment(
    *,
    base_env: Mapping[str, str] | None = None,
) -> tuple[dict[str, str], tuple[str, ...]]:
    """Return an environment without inherited ``PYTHONPATH`` entries.

    Atelier-managed agent and projected-skill runtimes do not inherit ambient
    ``PYTHONPATH`` because it can mix a selected interpreter with third-party
    packages from another distribution tree.

    Args:
        base_env: Optional source environment map. When omitted, current process
            environment is used.

    Returns:
        Tuple of ``(sanitized_env, removed_entries)`` where ``removed_entries``
        are the inherited ``PYTHONPATH`` entries that were dropped.
    """
    env = dict(os.environ if base_env is None else base_env)
    removed_entries = _pythonpath_entries(env.get(_PYTHONPATH_ENV))
    env.pop(_PYTHONPATH_ENV, None)
    return env, removed_entries


def format_ambient_pythonpath_warning(removed_entries: Iterable[str]) -> str | None:
    """Build a warning for dropped inherited ``PYTHONPATH`` entries.

    Args:
        removed_entries: Iterable of dropped ``PYTHONPATH`` entries.

    Returns:
        User-facing warning text when entries were removed; otherwise ``None``.
    """
    unique = sorted({entry for entry in removed_entries if entry})
    if not unique:
        return None
    sample = ", ".join(unique[:_WARNING_SAMPLE_LIMIT])
    suffix = ""
    if len(unique) > _WARNING_SAMPLE_LIMIT:
        suffix = f", +{len(unique) - _WARNING_SAMPLE_LIMIT} more"
    return (
        "Warning: ignored inherited PYTHONPATH entries "
        f"({sample}{suffix}). "
        "Atelier-managed runtimes rebuild Python imports from the selected "
        "repo runtime instead of mixing in ambient site-packages."
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


def ensure_projected_runtime_dependency(
    *,
    repo_root: Path | None,
    script_path: Path,
    dependency: str = _PROJECTED_RUNTIME_DEPENDENCY,
    base_env: Mapping[str, str] | None = None,
    current_executable: str | None = None,
) -> None:
    """Fail closed when a projected helper runtime lacks compiled dependencies.

    Projected planner helpers are expected to either re-exec into the repo
    runtime or stop with deterministic guidance before importing heavier
    ``atelier`` modules. This catches the remaining failure mode where the
    selected interpreter cannot import compiled dependencies such as
    ``pydantic_core._pydantic_core``.

    Args:
        repo_root: Resolved repository root, if any.
        script_path: Concrete helper script path for diagnostics.
        dependency: Import path used as the runtime-health probe.
        base_env: Optional environment mapping used for runtime resolution.
        current_executable: Optional interpreter path override for testing.

    Raises:
        SystemExit: If the dependency cannot be imported in the selected
            interpreter.
    """
    try:
        imported_modules = tuple(
            (module_name, importlib.import_module(module_name))
            for module_name in _projected_runtime_dependency_modules(dependency)
        )
    except Exception as exc:
        dependency_error = exc
    else:
        provenance_issues = _projected_runtime_provenance_issues(imported_modules)
        if not provenance_issues:
            return
        provenance_issue = provenance_issues[0]
        command = (
            projected_repo_python_command(
                repo_root=repo_root,
                base_env=base_env,
                current_executable=current_executable or sys.executable,
            )
            if repo_root is not None
            else None
        )
        runtime_label = _projected_runtime_label(
            current_executable=str(current_executable or sys.executable or "").strip(),
            script_path=script_path,
        )
        repo_display = str(repo_root) if repo_root is not None else "(unresolved)"
        print(
            "error: planner helper runtime provenance is mixed before importing atelier modules.",
            file=sys.stderr,
        )
        print(
            "boundary: repo-source bootstrap is separate; this is a dependency "
            "provenance contradiction, not another src-path-ordering regression.",
            file=sys.stderr,
        )
        print(f"script: {script_path}", file=sys.stderr)
        print(
            f"interpreter: {str(current_executable or sys.executable or '').strip() or '(unknown)'}",
            file=sys.stderr,
        )
        print(f"runtime: {runtime_label}", file=sys.stderr)
        print(f"repo_root: {repo_display}", file=sys.stderr)
        print(f"module: {provenance_issue.module_name}", file=sys.stderr)
        print(f"module_path: {provenance_issue.module_path}", file=sys.stderr)
        print(
            "expected_roots: " + ", ".join(provenance_issue.expected_roots or ("(unresolved)",)),
            file=sys.stderr,
        )
        ambient_pythonpath = str(os.environ.get(_PYTHONPATH_ENV, "")).strip()
        if ambient_pythonpath:
            print(f"ambient_pythonpath: {ambient_pythonpath}", file=sys.stderr)
        print(
            "action: "
            + _projected_runtime_recovery_guidance(
                repo_root=repo_root,
                script_path=script_path,
                runtime_label=runtime_label,
                command=command,
            ),
            file=sys.stderr,
        )
        raise SystemExit(1)

    env = dict(os.environ if base_env is None else base_env)
    current = str(current_executable or sys.executable or "").strip()
    command = (
        projected_repo_python_command(
            repo_root=repo_root,
            base_env=env,
            current_executable=current,
        )
        if repo_root is not None
        else None
    )
    runtime_label = _projected_runtime_label(
        current_executable=current,
        script_path=script_path,
    )
    repo_display = str(repo_root) if repo_root is not None else "(unresolved)"
    print(
        "error: planner helper runtime is unhealthy before importing atelier modules.",
        file=sys.stderr,
    )
    print(
        "boundary: repo-source bootstrap is separate; this is an interpreter "
        "dependency failure, not another src-path-ordering regression.",
        file=sys.stderr,
    )
    print(f"script: {script_path}", file=sys.stderr)
    print(f"interpreter: {current or '(unknown)'}", file=sys.stderr)
    print(f"runtime: {runtime_label}", file=sys.stderr)
    print(f"repo_root: {repo_display}", file=sys.stderr)
    print(f"dependency: {dependency}", file=sys.stderr)
    print(
        f"detail: {type(dependency_error).__name__}: {dependency_error}",
        file=sys.stderr,
    )
    print(
        "action: "
        + _projected_runtime_recovery_guidance(
            repo_root=repo_root,
            script_path=script_path,
            runtime_label=runtime_label,
            command=command,
        ),
        file=sys.stderr,
    )
    raise SystemExit(1)


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


def _projected_runtime_label(*, current_executable: str, script_path: Path) -> str:
    candidates = (current_executable, str(script_path))
    for candidate in candidates:
        if any(marker in candidate for marker in _INSTALLED_TOOL_RUNTIME_MARKERS):
            return "installed-tool"
    return "ambient"


def _projected_runtime_recovery_guidance(
    *,
    repo_root: Path | None,
    script_path: Path,
    runtime_label: str,
    command: tuple[str, ...] | None,
) -> str:
    if repo_root is None:
        return (
            "provide --repo-dir <repo-root> or run from an agent home with a "
            "./worktree link so the helper can select the repo runtime."
        )
    if command is not None:
        return (
            "repair the selected repo runtime or rerun explicitly via "
            f"`{' '.join((*command, str(script_path)))}'."
        )
    if runtime_label == "installed-tool":
        return (
            "repair or reinstall the uv tool environment, or rerun the helper "
            f"from the repo runtime (for example `uv run --project {repo_root} "
            f"python {script_path}`)."
        )
    return (
        "repair the selected Python runtime so it can import compiled "
        "dependencies, then rerun the helper."
    )


def _pythonpath_entries(raw_pythonpath: str | None) -> tuple[str, ...]:
    raw = str(raw_pythonpath or "").strip()
    if not raw:
        return ()
    return tuple(entry for entry in raw.split(os.pathsep) if entry)


def reset_current_process_pythonpath(
    entries: Iterable[str],
    *,
    preserve_paths: Iterable[str] = (),
) -> None:
    """Remove inherited ``PYTHONPATH`` entries from the active process state.

    Args:
        entries: ``PYTHONPATH`` entries to drop from ``sys.path``.
        preserve_paths: Explicit paths that must remain in ``sys.path`` even if
            they also appeared in ``entries``.
    """
    os.environ.pop(_PYTHONPATH_ENV, None)
    removed = {entry for entry in entries if entry}
    if not removed:
        return
    preserved = {entry for entry in preserve_paths if entry}
    sys.path[:] = [entry for entry in sys.path if entry not in removed or entry in preserved]


def _projected_runtime_dependency_modules(dependency: str) -> tuple[str, ...]:
    names: list[str] = []
    seen: set[str] = set()
    for module_name in (*_PROJECTED_RUNTIME_PROVENANCE_MODULES, dependency):
        normalized = str(module_name).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        names.append(normalized)
    return tuple(names)


def _projected_runtime_provenance_issues(
    imported_modules: Sequence[tuple[str, object]],
) -> tuple[_ProjectedRuntimeProvenanceIssue, ...]:
    allowed_roots = _current_runtime_dependency_roots()
    expected_roots = tuple(str(root) for root in allowed_roots)
    issues: list[_ProjectedRuntimeProvenanceIssue] = []
    for module_name, module in imported_modules:
        module_path = _module_origin_path(module)
        if module_path is None:
            continue
        if _path_within_roots(module_path, allowed_roots):
            continue
        issues.append(
            _ProjectedRuntimeProvenanceIssue(
                module_name=module_name,
                module_path=str(module_path),
                expected_roots=expected_roots,
            )
        )
    return tuple(issues)


def _current_runtime_dependency_roots() -> tuple[Path, ...]:
    roots: list[Path] = []
    for key in ("purelib", "platlib"):
        raw_path = str(sysconfig.get_path(key) or "").strip()
        if not raw_path:
            continue
        resolved = Path(raw_path).resolve()
        if resolved not in roots:
            roots.append(resolved)
    return tuple(roots)


def _module_origin_path(module: object) -> Path | None:
    raw_path = getattr(module, "__file__", None)
    if not isinstance(raw_path, str) or not raw_path.strip():
        spec = getattr(module, "__spec__", None)
        raw_path = getattr(spec, "origin", None)
    if not isinstance(raw_path, str) or not raw_path.strip():
        return None
    try:
        return Path(raw_path).resolve()
    except OSError:
        return Path(raw_path)


def _path_within_roots(path: Path, roots: Sequence[Path]) -> bool:
    for root in roots:
        try:
            path.relative_to(root)
        except ValueError:
            continue
        return True
    return False

"""Shared bootstrap for projected skill scripts that import ``atelier``."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

_DEFAULT_REPO_DIR_ENV_VARS: tuple[str, ...] = (
    "ATELIER_PLANNER_WORKTREE",
    "ATELIER_WORKSPACE_DIR",
    "ATELIER_PROJECT",
)
_PROJECTED_RUNTIME_DIRNAME = ".atelier-runtime"
_PROJECTED_RUNTIME_MANIFEST_FILENAME = "projected-runtime.json"
_PROJECTED_SUPPORT_MANIFEST_FILENAME = "support-manifest.json"
_AGENT_METADATA_FILENAME = "agent.json"
_PROJECT_CONFIG_SYS_FILENAME = "config.sys.json"
_PROJECT_CONFIG_LEGACY_FILENAME = "config.json"
_WORKTREES_DIRNAME = "worktrees"
_PROJECTED_SUPPORT_RUNTIME_SELECTED_ENV = "ATELIER_PROJECTED_SUPPORT_RUNTIME_SELECTED"
_PROJECTED_SUPPORT_RUNTIME_REPAIR_ATTEMPTED_ENV = (
    "ATELIER_PROJECTED_SUPPORT_RUNTIME_REPAIR_ATTEMPTED"
)
_INSTALLED_TOOL_RUNTIME_MARKERS: tuple[str, ...] = (
    "/.local/share/uv/tools/atelier/",
    "/Library/Application Support/uv/tools/atelier/",
    "/site-packages/atelier/",
)


@dataclass(frozen=True)
class _ProjectedSupportRuntimeResolution:
    status: str
    detail: str
    command: tuple[str, ...] | None = None
    pythonpath_entries: tuple[str, ...] = ()


@dataclass(frozen=True)
class _ProjectedSupportRuntimeManifest:
    helper_session_id: str
    selected_interpreter: str
    import_root: Path
    pythonpath_entries: tuple[str, ...]


@dataclass(frozen=True)
class _ProjectedSupportRuntimeRepairLauncher:
    selected_interpreter: str
    pythonpath_entries: tuple[str, ...]


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
    if argv_repo_dir is None:
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


def _is_project_data_dir(path: Path) -> bool:
    return (
        (path / _PROJECT_CONFIG_SYS_FILENAME).exists()
        or (path / _PROJECT_CONFIG_LEGACY_FILENAME).exists()
        or (path / _WORKTREES_DIRNAME).exists()
        or (path / "skills").is_dir()
    )


def _projected_skill_roots(script_path: Path) -> tuple[Path, ...]:
    resolved_script = script_path.resolve()
    current_skill_root: Path | None = None
    for parent in resolved_script.parents:
        if parent.name == "skills":
            current_skill_root = parent
            break
    if current_skill_root is None:
        return ()

    candidate_roots: list[Path] = []
    agent_home_root = current_skill_root.parent
    if (agent_home_root / _AGENT_METADATA_FILENAME).is_file():
        for ancestor in agent_home_root.parents:
            if ancestor.name != "agents":
                continue
            project_dir = ancestor.parent
            if not _is_project_data_dir(project_dir):
                continue
            canonical_skills_root = project_dir / "skills"
            if canonical_skills_root.is_dir():
                candidate_roots.append(canonical_skills_root)
            break
    candidate_roots.append(current_skill_root)

    ordered: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidate_roots:
        try:
            resolved = candidate.resolve()
        except OSError:
            resolved = candidate
        if resolved in seen:
            continue
        seen.add(resolved)
        ordered.append(resolved)
    return tuple(ordered)


def _preferred_existing_path(candidates: Sequence[Path]) -> Path | None:
    for candidate in candidates:
        if candidate.exists():
            return candidate
    if not candidates:
        return None
    return candidates[0]


def _support_runtime_manifest_path(script_path: Path) -> Path | None:
    candidates = tuple(
        skill_root.parent / _PROJECTED_RUNTIME_DIRNAME / _PROJECTED_RUNTIME_MANIFEST_FILENAME
        for skill_root in _projected_skill_roots(script_path)
    )
    return _preferred_existing_path(candidates)


def _projected_support_manifest_path(script_path: Path) -> Path | None:
    candidates = tuple(
        skill_root / "shared" / _PROJECTED_SUPPORT_MANIFEST_FILENAME
        for skill_root in _projected_skill_roots(script_path)
    )
    return _preferred_existing_path(candidates)


def _same_executable(current_executable: str, selected_interpreter: str) -> bool:
    current = str(current_executable).strip()
    selected = str(selected_interpreter).strip()
    if not current or not selected:
        return False
    try:
        return Path(current).resolve() == Path(selected).resolve()
    except OSError:
        return current == selected


def _runtime_provenance_label(*, current_executable: str) -> str:
    if any(marker in current_executable for marker in _INSTALLED_TOOL_RUNTIME_MARKERS):
        return "installed-tool"
    return "ambient"


def _format_path_entries(entries: Sequence[str]) -> str:
    values = [str(entry).strip() for entry in entries if str(entry).strip()]
    if not values:
        return "(none)"
    return ", ".join(values)


def _prepend_sys_path(entries: Sequence[str]) -> tuple[str, ...]:
    ordered: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        normalized = str(entry).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    if not ordered:
        return ()
    sys.path[:] = [entry for entry in sys.path if entry not in seen]
    sys.path[:0] = ordered
    return tuple(ordered)


def _activate_support_runtime_paths(entries: Sequence[str]) -> tuple[str, ...]:
    ordered = _prepend_sys_path(entries)
    if ordered:
        os.environ["PYTHONPATH"] = os.pathsep.join(ordered)
    else:
        os.environ.pop("PYTHONPATH", None)
    return ordered


def _read_support_runtime_manifest(
    manifest_path: Path,
    *,
    subject: str = "projected support runtime manifest",
) -> tuple[object | None, str | None]:
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8")), None
    except FileNotFoundError:
        return None, f"{subject} missing: {manifest_path}"
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"{subject} is malformed: {exc}"


def _parse_support_runtime_manifest(
    payload: object,
    *,
    subject: str = "projected support runtime manifest",
) -> tuple[_ProjectedSupportRuntimeManifest | None, str | None]:
    if not isinstance(payload, dict):
        return None, f"{subject} is not a JSON object."
    if payload.get("status") != "converged":
        return None, f"{subject} did not prove convergence."
    helper_session_id = str(payload.get("helper_session_id", "")).strip()
    selected_interpreter = str(payload.get("selected_interpreter", "")).strip()
    import_root_raw = str(payload.get("atelier_import_root", "")).strip()
    pythonpath_entries_raw = payload.get("pythonpath_entries")
    if not helper_session_id:
        return None, f"{subject} is missing helper_session_id."
    if not selected_interpreter:
        return None, f"{subject} is missing selected_interpreter."
    if not import_root_raw:
        return None, f"{subject} is missing atelier_import_root."
    if not isinstance(pythonpath_entries_raw, list) or not pythonpath_entries_raw:
        return None, f"{subject} is missing pythonpath_entries."
    try:
        import_root = Path(import_root_raw).expanduser().resolve()
    except OSError as exc:
        return None, f"{subject} import root is invalid: {exc}"
    if not (import_root / "atelier" / "__init__.py").is_file():
        return (
            None,
            f"{subject} does not point at an importable Atelier root: {import_root}",
        )
    pythonpath_entries = tuple(
        str(Path(str(entry).strip()).expanduser())
        for entry in pythonpath_entries_raw
        if str(entry).strip()
    )
    return (
        _ProjectedSupportRuntimeManifest(
            helper_session_id=helper_session_id,
            selected_interpreter=selected_interpreter,
            import_root=import_root,
            pythonpath_entries=pythonpath_entries,
        ),
        None,
    )


def _validate_support_runtime_interpreter(
    selected_interpreter: str,
    *,
    subject: str,
) -> tuple[str | None, str | None]:
    interpreter = str(selected_interpreter).strip()
    if not interpreter:
        return None, f"{subject} is missing selected_interpreter."
    interpreter_path = Path(interpreter).expanduser()
    if not (interpreter_path.is_file() and os.access(interpreter_path, os.X_OK)):
        return (
            None,
            f"{subject} selected_interpreter is not executable: {interpreter}",
        )
    return interpreter, None


def _support_runtime_repair_launcher(
    *,
    script_path: Path,
    manifest_path: Path,
) -> tuple[_ProjectedSupportRuntimeRepairLauncher | None, str | None]:
    support_manifest_path = _projected_support_manifest_path(script_path)
    support_manifest_error: str | None = None
    if support_manifest_path is None:
        support_manifest_error = (
            "projected support manifest path could not be derived from script path."
        )
    else:
        support_payload, support_read_error = _read_support_runtime_manifest(
            support_manifest_path,
            subject="projected support manifest",
        )
        if support_read_error is not None:
            support_manifest_error = support_read_error
        else:
            support_manifest, parsed_support_error = _parse_support_runtime_manifest(
                support_payload,
                subject="projected support manifest",
            )
            if parsed_support_error is not None:
                support_manifest_error = parsed_support_error
            else:
                assert support_manifest is not None
                interpreter, interpreter_error = _validate_support_runtime_interpreter(
                    support_manifest.selected_interpreter,
                    subject="projected support manifest",
                )
                if interpreter_error is not None:
                    support_manifest_error = interpreter_error
                else:
                    assert interpreter is not None
                    return (
                        _ProjectedSupportRuntimeRepairLauncher(
                            selected_interpreter=interpreter,
                            pythonpath_entries=support_manifest.pythonpath_entries,
                        ),
                        None,
                    )

    manifest_payload, manifest_read_error = _read_support_runtime_manifest(
        manifest_path,
        subject="projected support runtime manifest",
    )
    if manifest_read_error is not None:
        if support_manifest_error is None:
            return None, manifest_read_error
        return (
            None,
            "projected support runtime self-heal is unavailable: "
            f"{support_manifest_error}; fallback recorded runtime is unavailable: "
            f"{manifest_read_error}",
        )
    if not isinstance(manifest_payload, dict):
        recorded_manifest_error = "projected support runtime manifest is not a JSON object."
    else:
        interpreter, interpreter_error = _validate_support_runtime_interpreter(
            str(manifest_payload.get("selected_interpreter", "")),
            subject="projected support runtime manifest",
        )
        if interpreter_error is None:
            assert interpreter is not None
            return (
                _ProjectedSupportRuntimeRepairLauncher(
                    selected_interpreter=interpreter,
                    pythonpath_entries=(),
                ),
                None,
            )
        recorded_manifest_error = interpreter_error
    if support_manifest_error is None:
        return None, recorded_manifest_error
    return (
        None,
        "projected support runtime self-heal is unavailable: "
        f"{support_manifest_error}; fallback recorded runtime is unavailable: "
        f"{recorded_manifest_error}",
    )


def _repair_support_runtime_manifest(
    *,
    script_path: Path,
    manifest_path: Path,
    env: Mapping[str, str],
) -> tuple[bool, str | None]:
    if env.get(_PROJECTED_SUPPORT_RUNTIME_REPAIR_ATTEMPTED_ENV) == "1":
        return False, None

    workspace_dir = manifest_path.parent.parent.resolve()
    launcher, launcher_error = _support_runtime_repair_launcher(
        script_path=script_path,
        manifest_path=manifest_path,
    )
    if launcher_error is not None:
        return False, launcher_error
    assert launcher is not None

    helper_env = dict(env)
    helper_env[_PROJECTED_SUPPORT_RUNTIME_REPAIR_ATTEMPTED_ENV] = "1"
    helper_env.pop(_PROJECTED_SUPPORT_RUNTIME_SELECTED_ENV, None)
    if launcher.pythonpath_entries:
        helper_env["PYTHONPATH"] = os.pathsep.join(launcher.pythonpath_entries)
    else:
        helper_env.pop("PYTHONPATH", None)
    repair_program = "\n".join(
        (
            "import json, sys",
            "from pathlib import Path",
            "from atelier import skills",
            "",
            "workspace_dir = Path(sys.argv[1]).expanduser().resolve()",
            "result = skills.sync_project_skills(",
            "    workspace_dir,",
            "    upgrade_policy='always',",
            "    yes=True,",
            "    interactive=False,",
            ")",
            "manifest_path = workspace_dir / '.atelier-runtime' / 'projected-runtime.json'",
            "payload = json.loads(manifest_path.read_text(encoding='utf-8'))",
            "validated = skills._validate_projected_runtime_manifest(payload)",
            "print(",
            "    json.dumps(",
            "        {",
            "            'status': 'converged',",
            "            'workspace_dir': str(workspace_dir),",
            "            'manifest_path': str(manifest_path.resolve()),",
            "            'sync_action': result.action,",
            "            'manifest': validated,",
            "        },",
            "        sort_keys=True,",
            "    )",
            ")",
        )
    )
    try:
        completed = subprocess.run(
            [launcher.selected_interpreter, "-c", repair_program, str(workspace_dir)],
            check=False,
            capture_output=True,
            text=True,
            env=helper_env,
            cwd=workspace_dir,
        )
    except OSError as exc:
        return True, f"projected support runtime self-heal failed to start: {exc}"
    if completed.returncode != 0:
        detail = " ".join(
            chunk.strip()
            for chunk in (completed.stderr, completed.stdout)
            if isinstance(chunk, str) and chunk.strip()
        )
        if not detail:
            detail = f"exit status {completed.returncode}"
        return True, f"projected support runtime self-heal failed: {detail}"

    raw_evidence = (completed.stdout or "").strip()
    if not raw_evidence:
        return (
            True,
            "projected support runtime self-heal did not emit convergence evidence.",
        )
    try:
        evidence = json.loads(raw_evidence)
    except json.JSONDecodeError as exc:
        return (
            True,
            f"projected support runtime self-heal emitted malformed convergence evidence: {exc}",
        )
    if not isinstance(evidence, dict):
        return (
            True,
            "projected support runtime self-heal convergence evidence was not a JSON object.",
        )
    if evidence.get("status") != "converged":
        return (
            True,
            "projected support runtime self-heal convergence evidence did not prove convergence.",
        )
    evidence_workspace = str(evidence.get("workspace_dir", "")).strip()
    if evidence_workspace != str(workspace_dir):
        return (
            True,
            "projected support runtime self-heal convergence evidence referenced "
            f"the wrong workspace: {evidence_workspace or '(missing)'}",
        )
    evidence_manifest = str(evidence.get("manifest_path", "")).strip()
    if evidence_manifest != str(manifest_path.resolve()):
        return (
            True,
            "projected support runtime self-heal convergence evidence referenced "
            f"the wrong manifest: {evidence_manifest or '(missing)'}",
        )
    _manifest, manifest_error = _parse_support_runtime_manifest(
        evidence.get("manifest"),
        subject="projected support runtime self-heal manifest evidence",
    )
    if manifest_error is not None:
        return (
            True,
            "projected support runtime self-heal convergence evidence did not "
            f"prove convergence: {manifest_error}",
        )
    return True, None


def _load_support_runtime_resolution(
    *,
    script_path: Path,
    argv: Sequence[str],
    env: Mapping[str, str],
) -> _ProjectedSupportRuntimeResolution:
    manifest_path = _support_runtime_manifest_path(script_path)
    if manifest_path is None:
        return _ProjectedSupportRuntimeResolution(
            status="unavailable",
            detail="projected support runtime manifest path could not be derived from script path.",
        )
    payload, manifest_read_error = _read_support_runtime_manifest(manifest_path)
    if manifest_read_error is not None:
        return _ProjectedSupportRuntimeResolution(
            status="unavailable",
            detail=manifest_read_error,
        )

    manifest, manifest_error = _parse_support_runtime_manifest(payload)
    if manifest_error is not None:
        attempted_repair, repair_error = _repair_support_runtime_manifest(
            script_path=script_path,
            manifest_path=manifest_path,
            env=env,
        )
        if repair_error is not None:
            return _ProjectedSupportRuntimeResolution(
                status="unavailable",
                detail=repair_error,
            )
        if not attempted_repair:
            return _ProjectedSupportRuntimeResolution(
                status="unavailable",
                detail=manifest_error,
            )
        payload, manifest_read_error = _read_support_runtime_manifest(manifest_path)
        if manifest_read_error is not None:
            return _ProjectedSupportRuntimeResolution(
                status="unavailable",
                detail=(
                    "projected support runtime self-heal completed without readable "
                    f"manifest evidence: {manifest_read_error}"
                ),
            )
        manifest, manifest_error = _parse_support_runtime_manifest(payload)
        if manifest_error is not None:
            return _ProjectedSupportRuntimeResolution(
                status="unavailable",
                detail=(
                    "projected support runtime self-heal completed without "
                    f"converged manifest evidence: {manifest_error}"
                ),
            )

    assert manifest is not None
    if _same_executable(sys.executable, manifest.selected_interpreter):
        activated = _activate_support_runtime_paths(manifest.pythonpath_entries)
        return _ProjectedSupportRuntimeResolution(
            status="active",
            detail=(
                "projected support runtime evidence converged in the current interpreter "
                f"via helper session {manifest.helper_session_id}."
            ),
            command=None,
            pythonpath_entries=activated,
        )
    if env.get(_PROJECTED_SUPPORT_RUNTIME_SELECTED_ENV) == "1":
        return _ProjectedSupportRuntimeResolution(
            status="unavailable",
            detail=(
                "projected support runtime re-exec was already attempted, but the "
                "selected interpreter still did not converge."
            ),
            command=(manifest.selected_interpreter,),
            pythonpath_entries=manifest.pythonpath_entries,
        )
    selected_path = Path(manifest.selected_interpreter).expanduser()
    if not (selected_path.is_file() and os.access(selected_path, os.X_OK)):
        return _ProjectedSupportRuntimeResolution(
            status="unavailable",
            detail=(
                "projected support runtime manifest selected_interpreter is not executable: "
                f"{manifest.selected_interpreter}"
            ),
            command=(manifest.selected_interpreter,),
            pythonpath_entries=manifest.pythonpath_entries,
        )
    exec_env = dict(env)
    exec_env[_PROJECTED_SUPPORT_RUNTIME_SELECTED_ENV] = "1"
    if manifest.pythonpath_entries:
        exec_env["PYTHONPATH"] = os.pathsep.join(manifest.pythonpath_entries)
    else:
        exec_env.pop("PYTHONPATH", None)
    try:
        os.execvpe(
            manifest.selected_interpreter,
            [manifest.selected_interpreter, str(script_path), *argv],
            exec_env,
        )
    except OSError as exc:
        return _ProjectedSupportRuntimeResolution(
            status="unavailable",
            detail=f"projected support runtime re-exec failed: {exc}",
            command=(manifest.selected_interpreter,),
            pythonpath_entries=manifest.pythonpath_entries,
        )
    return _ProjectedSupportRuntimeResolution(
        status="available",
        detail="projected support runtime re-exec was requested.",
        command=(manifest.selected_interpreter,),
        pythonpath_entries=manifest.pythonpath_entries,
    )


def _fail_unresolved_runtime(
    *,
    script_path: Path,
    repo_root: Path | None,
    repo_dir: Path | None,
    support_resolution: _ProjectedSupportRuntimeResolution,
    error: Exception,
) -> NoReturn:
    selected_mode = "repo-source" if repo_root is not None else "active-interpreter"
    selected_interpreter = str(sys.executable or "").strip() or "(unknown)"
    repo_display = str(repo_root) if repo_root is not None else "(unresolved)"
    print(
        "error: planner helper runtime is unhealthy before importing atelier modules.",
        file=sys.stderr,
    )
    print(
        "boundary: projected bootstrap could not resolve an importable Atelier "
        "runtime before loading atelier.runtime_env.",
        file=sys.stderr,
    )
    print(f"script: {script_path}", file=sys.stderr)
    print(f"selected_interpreter: {selected_interpreter}", file=sys.stderr)
    print(f"selected_mode: {selected_mode}", file=sys.stderr)
    print(
        f"runtime_provenance: {_runtime_provenance_label(current_executable=selected_interpreter)}",
        file=sys.stderr,
    )
    print(f"repo_root: {repo_display}", file=sys.stderr)
    if repo_dir is not None:
        print(f"repo_hint: {repo_dir}", file=sys.stderr)
    print(f"repo_runtime_status: {support_resolution.status}", file=sys.stderr)
    print(f"repo_runtime_detail: {support_resolution.detail}", file=sys.stderr)
    if support_resolution.command is not None:
        print("repo_runtime_command: " + " ".join(support_resolution.command), file=sys.stderr)
    print("pythonpath_removed: (none)", file=sys.stderr)
    print(
        "pythonpath_preserved: " + _format_path_entries(support_resolution.pythonpath_entries),
        file=sys.stderr,
    )
    print("dependency: atelier.runtime_env", file=sys.stderr)
    print(f"detail: {type(error).__name__}: {error}", file=sys.stderr)
    print(
        "action: sync projected skills from a converged Atelier runtime or rerun "
        "from an agent home that can prove the runtime explicitly.",
        file=sys.stderr,
    )
    raise SystemExit(1) from error


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
    explicit_repo_dir = _repo_dir_from_argv(resolved_argv)
    repo_root = _bootstrap_source_import(
        script_path=script_path,
        argv=resolved_argv,
        env=resolved_env,
        repo_dir_env_vars=repo_dir_env_vars,
    )
    support_resolution = _ProjectedSupportRuntimeResolution(
        status="not-applicable",
        detail="repo-source bootstrap resolved an importable atelier checkout.",
    )
    if repo_root is None:
        support_resolution = _load_support_runtime_resolution(
            script_path=script_path,
            argv=resolved_argv,
            env=resolved_env,
        )
        if support_resolution.pythonpath_entries:
            resolved_env["PYTHONPATH"] = os.pathsep.join(support_resolution.pythonpath_entries)
        else:
            resolved_env.pop("PYTHONPATH", None)

    try:
        from atelier.runtime_env import (
            ProjectedRuntimeMode,
            collect_projected_bootstrap_diagnostics,
            ensure_projected_runtime_dependency,
            maybe_reexec_projected_repo_runtime,
            projected_runtime_contract,
            reset_current_process_pythonpath,
            sanitize_pythonpath_environment,
        )
    except Exception as exc:
        _fail_unresolved_runtime(
            script_path=script_path,
            repo_root=repo_root,
            repo_dir=explicit_repo_dir,
            support_resolution=support_resolution,
            error=exc,
        )

    contract = projected_runtime_contract(repo_root=repo_root)

    def _set_current_process_pythonpath(paths: Sequence[str]) -> None:
        explicit_paths = tuple(dict.fromkeys(path for path in paths if path))
        if explicit_paths:
            os.environ["PYTHONPATH"] = os.pathsep.join(explicit_paths)
            return
        os.environ.pop("PYTHONPATH", None)

    if require_runtime_health:
        if contract.preferred_mode is ProjectedRuntimeMode.REPO_SOURCE and repo_root is not None:
            resolved_env, removed_pythonpath = sanitize_pythonpath_environment(
                base_env=resolved_env
            )
            preserve_paths = (str(repo_root / "src"),)
            resolved_env["PYTHONPATH"] = os.pathsep.join(preserve_paths)
            bootstrap_diagnostics = collect_projected_bootstrap_diagnostics(
                repo_root=repo_root,
                script_path=script_path,
                base_env=resolved_env,
                current_executable=sys.executable,
                removed_pythonpath_entries=removed_pythonpath,
                preserved_pythonpath_entries=preserve_paths,
            )
            reset_current_process_pythonpath(
                removed_pythonpath,
                preserve_paths=preserve_paths,
            )
            _set_current_process_pythonpath(preserve_paths)
            maybe_reexec_projected_repo_runtime(
                repo_root=repo_root,
                script_path=script_path,
                argv=resolved_argv,
                base_env=resolved_env,
                bootstrap_diagnostics=bootstrap_diagnostics,
            )
            ensure_projected_runtime_dependency(
                repo_root=repo_root,
                script_path=script_path,
                base_env=resolved_env,
                bootstrap_diagnostics=bootstrap_diagnostics,
            )
        else:
            bootstrap_diagnostics = collect_projected_bootstrap_diagnostics(
                repo_root=repo_root,
                script_path=script_path,
                base_env=resolved_env,
                current_executable=sys.executable,
                removed_pythonpath_entries=tuple(
                    entry for entry in resolved_env.get("PYTHONPATH", "").split(os.pathsep) if entry
                ),
            )
            maybe_reexec_projected_repo_runtime(
                repo_root=repo_root,
                script_path=script_path,
                argv=resolved_argv,
                base_env=resolved_env,
                bootstrap_diagnostics=bootstrap_diagnostics,
            )
            preserve_paths = ensure_projected_runtime_dependency(
                repo_root=repo_root,
                script_path=script_path,
                base_env=resolved_env,
                bootstrap_diagnostics=bootstrap_diagnostics,
            )
            resolved_env, removed_pythonpath = sanitize_pythonpath_environment(
                base_env=resolved_env
            )
            if preserve_paths:
                resolved_env["PYTHONPATH"] = os.pathsep.join(preserve_paths)
            reset_current_process_pythonpath(
                removed_pythonpath,
                preserve_paths=preserve_paths,
            )
            _set_current_process_pythonpath(preserve_paths)
    else:
        resolved_env, removed_pythonpath = sanitize_pythonpath_environment(base_env=resolved_env)
        preserve_paths: tuple[str, ...] = ()
        if contract.preferred_mode is ProjectedRuntimeMode.REPO_SOURCE and repo_root is not None:
            preserve_paths = (str(repo_root / "src"),)
            resolved_env["PYTHONPATH"] = os.pathsep.join(preserve_paths)
        reset_current_process_pythonpath(
            removed_pythonpath,
            preserve_paths=preserve_paths,
        )
    return repo_root

"""Skill loading and workspace projection helpers."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from importlib import resources
from importlib.abc import Traversable
from pathlib import Path
from typing import Callable

from . import __version__, paths

try:
    import fcntl
except ImportError:  # pragma: no cover - platform fallback
    fcntl = None

_SKILLS_LOCK_DIRNAME = ".locks"
_SKILLS_LOCK_FILENAME = "skills-sync.lock"
_SKILLS_LOCK_GUARD = threading.Lock()
_SKILLS_LOCAL_LOCKS: dict[str, threading.RLock] = {}
_PACKAGED_SUPPORT_TREE_NAMES = frozenset({"shared"})
_PROJECTED_RUNTIME_DIRNAME = ".atelier-runtime"
_PROJECTED_RUNTIME_MANIFEST_FILENAME = "projected-runtime.json"
_PROJECTED_SUPPORT_MANIFEST_FILENAME = "support-manifest.json"
_INSTALLED_RUNTIME_REPAIR_STATE_FILENAME = "projected-runtime-repair-state.json"


@dataclass(frozen=True)
class SkillDefinition:
    name: str
    files: dict[str, bytes]
    digest: str


@dataclass(frozen=True)
class SkillWorkspaceState:
    needs_install: bool
    needs_metadata: bool
    unmodified: bool
    missing: list[str]
    modified: list[str]
    extra: list[str]


@dataclass(frozen=True)
class ProjectSkillsSyncResult:
    skills_dir: Path
    action: str
    detail: str | None = None


@dataclass(frozen=True)
class InstalledProjectRuntimeRepairResult:
    action: str
    scanned_projects: tuple[Path, ...]
    updated_projects: tuple[Path, ...]
    failed_projects: tuple[tuple[Path, str], ...]


def _skills_lock_path(workspace_dir: Path) -> Path:
    return workspace_dir / _SKILLS_LOCK_DIRNAME / _SKILLS_LOCK_FILENAME


def _local_skills_lock(lock_path: Path) -> threading.RLock:
    key = str(lock_path.resolve())
    with _SKILLS_LOCK_GUARD:
        lock = _SKILLS_LOCAL_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _SKILLS_LOCAL_LOCKS[key] = lock
        return lock


def _acquire_file_lock(handle) -> None:
    if fcntl is None:  # pragma: no cover - no-op on unsupported platforms
        return
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)


def _release_file_lock(handle) -> None:
    if fcntl is None:  # pragma: no cover - no-op on unsupported platforms
        return
    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def _skills_write_lock(workspace_dir: Path):
    lock_path = _skills_lock_path(workspace_dir)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    local_lock = _local_skills_lock(lock_path)
    local_lock.acquire()
    handle = None
    try:
        handle = lock_path.open("a+", encoding="utf-8")
        _acquire_file_lock(handle)
        yield
    finally:
        if handle is not None:
            try:
                _release_file_lock(handle)
            except OSError:
                pass
            handle.close()
        local_lock.release()


def _remove_path(path: Path) -> None:
    if not path.exists() and not path.is_symlink():
        return
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
        return
    shutil.rmtree(path)


def _stage_skills_tree(
    workspace_dir: Path,
    definitions: dict[str, SkillDefinition],
) -> Path:
    staging_dir = workspace_dir / f".skills-staging-{os.getpid()}-{time.time_ns()}"
    staging_dir.mkdir(parents=True, exist_ok=False)
    for definition in definitions.values():
        for rel_path, payload in definition.files.items():
            dest = staging_dir / definition.name / rel_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(payload)
    return staging_dir


def _verify_skills_tree(
    skills_dir: Path,
    definitions: dict[str, SkillDefinition],
) -> bool:
    if not skills_dir.exists() or not skills_dir.is_dir():
        return False
    expected = set(definitions.keys())
    actual = {entry.name for entry in skills_dir.iterdir() if entry.is_dir()}
    if actual != expected:
        return False
    for name, definition in definitions.items():
        skill_dir = skills_dir / name
        if "SKILL.md" in definition.files and not (skill_dir / "SKILL.md").is_file():
            return False
        if (
            _hash_dir(
                skill_dir,
                ignored_relpaths=_generated_skill_relpaths(name),
            )
            != definition.digest
        ):
            return False
    return True


def _install_staged_skills(
    workspace_dir: Path,
    skills_dir: Path,
    staging_dir: Path,
    definitions: dict[str, SkillDefinition],
) -> None:
    backup_path = workspace_dir / f".skills-backup-{os.getpid()}-{time.time_ns()}"
    has_backup = False
    try:
        if skills_dir.exists() or skills_dir.is_symlink():
            os.replace(skills_dir, backup_path)
            has_backup = True
        os.replace(staging_dir, skills_dir)
        if not _verify_skills_tree(skills_dir, definitions):
            raise OSError("skills install verification failed")
        if has_backup:
            _remove_path(backup_path)
            has_backup = False
    except OSError:
        if has_backup:
            try:
                _remove_path(skills_dir)
                os.replace(backup_path, skills_dir)
                has_backup = False
            except OSError:
                pass
        raise
    finally:
        if has_backup and backup_path.exists():
            _remove_path(backup_path)
        if staging_dir.exists():
            _remove_path(staging_dir)


def _normalize_skill_name(value: str) -> str:
    """Return a canonical skill-name key for metadata lookups."""
    return value.strip().lower().replace("_", "-")


def _skills_root() -> Traversable:
    return resources.files("atelier").joinpath("skills")


def _load_definition(name: str, root: Traversable) -> SkillDefinition:
    files = _collect_files(root, Path())
    digest = _hash_files(files)
    return SkillDefinition(name=name, files=files, digest=digest)


def _packaged_skill_tree_definitions() -> dict[str, SkillDefinition]:
    """Return packaged skill trees, including internal support directories."""
    root = _skills_root()
    definitions: dict[str, SkillDefinition] = {}
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        is_user_skill = entry.joinpath("SKILL.md").is_file()
        if not is_user_skill and entry.name not in _PACKAGED_SUPPORT_TREE_NAMES:
            continue
        definitions[entry.name] = _load_definition(entry.name, entry)
    return definitions


def list_packaged_skills() -> list[str]:
    root = _skills_root()
    if not root.is_dir():
        return []
    names: list[str] = []
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        skill_doc = entry.joinpath("SKILL.md")
        if skill_doc.is_file():
            names.append(entry.name)
    return sorted(names)


def _collect_files(root: Traversable, prefix: Path) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for entry in root.iterdir():
        name = entry.name
        rel_path = prefix / name
        if entry.is_dir():
            files.update(_collect_files(entry, rel_path))
        elif entry.is_file():
            files[rel_path.as_posix()] = entry.read_bytes()
    return files


def _hash_files(files: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    for rel_path in sorted(files.keys()):
        digest.update(rel_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(files[rel_path])
        digest.update(b"\0")
    return digest.hexdigest()


def load_packaged_skills() -> dict[str, SkillDefinition]:
    root = _skills_root()
    definitions: dict[str, SkillDefinition] = {}
    for name in list_packaged_skills():
        definitions[name] = _load_definition(name, root.joinpath(name))
    return definitions


def packaged_skill_metadata() -> dict[str, dict[str, str]]:
    definitions = _packaged_skill_tree_definitions()
    return {
        name: {"version": __version__, "hash": definition.digest}
        for name, definition in definitions.items()
    }


def _generated_skill_relpaths(skill_name: str) -> frozenset[str]:
    if skill_name == "shared":
        return frozenset({_PROJECTED_SUPPORT_MANIFEST_FILENAME})
    return frozenset()


def _hash_dir(root: Path, *, ignored_relpaths: frozenset[str] = frozenset()) -> str:
    files: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel_path = path.relative_to(root).as_posix()
        if rel_path in ignored_relpaths:
            continue
        files[rel_path] = path.read_bytes()
    return _hash_files(files)


def workspace_skill_state(
    workspace_dir: Path,
    stored_metadata: dict[str, object] | None,
) -> SkillWorkspaceState:
    definitions = _packaged_skill_tree_definitions()
    packaged_meta = packaged_skill_metadata()
    raw_stored = stored_metadata or {}
    stored: dict[str, dict[str, str | None]] = {}
    for name, entry in raw_stored.items():
        canonical_name = _normalize_skill_name(str(name))
        payload: dict[str, object] = {}
        if isinstance(entry, dict):
            payload = entry
        else:
            model_dump = getattr(entry, "model_dump", None)
            if callable(model_dump):
                dumped = model_dump()
                if isinstance(dumped, dict):
                    payload = dumped
        if not payload and (hasattr(entry, "version") or hasattr(entry, "hash")):
            payload = {
                "version": getattr(entry, "version", None),
                "hash": getattr(entry, "hash", None),
            }
        version = payload.get("version")
        digest = payload.get("hash")
        if version is None and digest is None:
            continue
        stored[canonical_name] = {
            "version": str(version) if version is not None else None,
            "hash": str(digest) if digest is not None else None,
        }
    skills_dir = workspace_dir / paths.SKILLS_DIRNAME
    actual_dirs: set[str] = set()
    if skills_dir.exists():
        for entry in skills_dir.iterdir():
            if entry.is_dir():
                actual_dirs.add(entry.name)
    packaged_names = set(definitions.keys())
    missing = sorted(packaged_names - actual_dirs)
    extra = sorted(actual_dirs - packaged_names)
    modified: list[str] = []
    unmodified = True
    needs_install = False

    for name, definition in definitions.items():
        skill_dir = skills_dir / name
        if not skill_dir.exists():
            needs_install = True
            continue
        actual_hash = _hash_dir(
            skill_dir,
            ignored_relpaths=_generated_skill_relpaths(name),
        )
        packaged_hash = definition.digest
        stored_entry = stored.get(name)
        stored_hash = stored_entry.get("hash") if stored_entry else None
        if actual_hash != packaged_hash:
            needs_install = True
        if stored_hash is not None:
            if actual_hash != stored_hash:
                unmodified = False
                modified.append(name)
        else:
            if actual_hash != packaged_hash:
                unmodified = False
                modified.append(name)

    if extra:
        needs_install = True
        unmodified = False
        modified.extend(extra)

    needs_metadata = False
    if unmodified and not needs_install:
        if packaged_meta != stored:
            needs_metadata = True

    return SkillWorkspaceState(
        needs_install=needs_install,
        needs_metadata=needs_metadata,
        unmodified=unmodified,
        missing=missing,
        modified=sorted(set(modified)),
        extra=extra,
    )


def install_workspace_skills(workspace_dir: Path) -> dict[str, dict[str, str]]:
    definitions = _packaged_skill_tree_definitions()
    skills_dir = workspace_dir / paths.SKILLS_DIRNAME
    with _skills_write_lock(workspace_dir):
        staging_dir = _stage_skills_tree(workspace_dir, definitions)
        _install_staged_skills(
            workspace_dir,
            skills_dir,
            staging_dir,
            definitions,
        )
        _write_projected_support_manifest(workspace_dir)
        _write_projected_runtime_manifest(workspace_dir)
    return {
        name: {"version": __version__, "hash": definition.digest}
        for name, definition in definitions.items()
    }


def ensure_project_skills(project_dir: Path) -> Path:
    """Ensure packaged skills are installed in the project data directory."""
    skills_dir = paths.project_skills_dir(project_dir)
    if skills_dir.exists():
        return skills_dir
    install_workspace_skills(project_dir)
    return skills_dir


def sync_project_skills(
    project_dir: Path,
    *,
    upgrade_policy: str = "ask",
    yes: bool = False,
    interactive: bool = False,
    prompt_update: Callable[[str], bool] | None = None,
    dry_run: bool = False,
) -> ProjectSkillsSyncResult:
    """Reconcile project skills with packaged skills.

    Project skills are Atelier-managed artifacts and are always synchronized
    to the packaged version when drift is detected.
    """
    skills_dir = paths.project_skills_dir(project_dir)
    if not skills_dir.exists():
        if dry_run:
            return ProjectSkillsSyncResult(
                skills_dir=skills_dir,
                action="would_install",
                detail="project skills missing",
            )
        install_workspace_skills(project_dir)
        return ProjectSkillsSyncResult(skills_dir=skills_dir, action="installed")

    state = workspace_skill_state(project_dir, None)
    if not state.needs_install:
        if dry_run and (
            _projected_support_manifest_requires_backfill(project_dir)
            or _projected_runtime_manifest_requires_backfill(project_dir)
        ):
            return ProjectSkillsSyncResult(
                skills_dir=skills_dir,
                action="would_update",
                detail="projected support manifest or runtime manifest missing or invalid",
            )
        repaired_support, repaired_runtime = _repair_projected_runtime_manifests(project_dir)
        if repaired_support or repaired_runtime:
            return ProjectSkillsSyncResult(
                skills_dir=skills_dir,
                action="updated",
                detail="projected support manifest or runtime manifest repaired",
            )
        return ProjectSkillsSyncResult(skills_dir=skills_dir, action="up_to_date")
    if dry_run:
        return ProjectSkillsSyncResult(
            skills_dir=skills_dir,
            action="would_update",
        )
    install_workspace_skills(project_dir)
    return ProjectSkillsSyncResult(skills_dir=skills_dir, action="updated")


def _installed_runtime_repair_state_path() -> Path:
    return paths.atelier_data_dir() / _INSTALLED_RUNTIME_REPAIR_STATE_FILENAME


def _load_installed_runtime_repair_state() -> dict[str, object] | None:
    state_path = _installed_runtime_repair_state_path()
    if not state_path.is_file():
        return None
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _installed_runtime_repair_state_is_current() -> bool:
    payload = _load_installed_runtime_repair_state()
    if payload is None:
        return False
    version = str(payload.get("atelier_version", "")).strip()
    return payload.get("schema_version") == 1 and version == __version__


def _write_installed_runtime_repair_state() -> None:
    state_path = _installed_runtime_repair_state_path()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = (
        json.dumps(
            {
                "schema_version": 1,
                "atelier_version": __version__,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=state_path.parent,
            prefix=f".{state_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(serialized)
            handle.flush()
            tmp_path = Path(handle.name)
        tmp_path.replace(state_path)
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


def _installed_runtime_repair_candidates() -> tuple[Path, ...]:
    project_dirs_root = paths.projects_root()
    if not project_dirs_root.exists():
        return ()
    candidates: list[Path] = []
    for candidate in sorted(project_dirs_root.iterdir()):
        if not candidate.is_dir():
            continue
        if not (
            paths.project_config_sys_path(candidate).exists()
            or paths.project_config_legacy_path(candidate).exists()
        ):
            continue
        if not (
            paths.project_skills_dir(candidate).exists()
            or _projected_runtime_manifest_path(candidate).exists()
        ):
            continue
        candidates.append(candidate)
    return tuple(candidates)


def repair_installed_project_skills_for_current_version() -> InstalledProjectRuntimeRepairResult:
    """Repair projected runtime state for already-installed project skill trees.

    Returns:
        Summary of the version-gated repair pass. ``action`` is ``"skipped"``
        when the current Atelier version already scanned installed projects,
        otherwise ``"repaired"`` after the repair pass runs.
    """
    if _installed_runtime_repair_state_is_current():
        return InstalledProjectRuntimeRepairResult(
            action="skipped",
            scanned_projects=(),
            updated_projects=(),
            failed_projects=(),
        )

    scanned_projects = _installed_runtime_repair_candidates()
    updated_projects: list[Path] = []
    failed_projects: list[tuple[Path, str]] = []
    for project_dir in scanned_projects:
        try:
            result = sync_project_skills(
                project_dir,
                upgrade_policy="always",
                yes=True,
                interactive=False,
            )
        except OSError as exc:
            failed_projects.append((project_dir, str(exc)))
            continue
        if result.action != "up_to_date":
            updated_projects.append(project_dir)

    if not failed_projects:
        _write_installed_runtime_repair_state()

    return InstalledProjectRuntimeRepairResult(
        action="repaired",
        scanned_projects=scanned_projects,
        updated_projects=tuple(updated_projects),
        failed_projects=tuple(failed_projects),
    )


def _projected_runtime_manifest_path(workspace_dir: Path) -> Path:
    return workspace_dir / _PROJECTED_RUNTIME_DIRNAME / _PROJECTED_RUNTIME_MANIFEST_FILENAME


def _projected_support_manifest_path(workspace_dir: Path) -> Path:
    return workspace_dir / paths.SKILLS_DIRNAME / "shared" / _PROJECTED_SUPPORT_MANIFEST_FILENAME


def _projected_runtime_helper_session_id() -> str:
    for env_key in ("ATELIER_AGENT_SESSION", "ATELIER_AGENT_ID"):
        value = str(os.environ.get(env_key, "")).strip()
        if value:
            return value
    try:
        resolved = Path(sys.executable).resolve()
    except OSError:
        resolved = Path(sys.executable)
    return f"installer:{resolved}"


def _projected_runtime_pythonpath_entries() -> tuple[str, ...]:
    module_names = (
        "atelier",
        "atelier.runtime_env",
        "pydantic",
        "pydantic_core",
        "pydantic_core._pydantic_core",
        "platformdirs",
        "questionary",
        "rich",
        "typer",
    )
    roots: list[str] = []
    seen: set[str] = set()
    for module_name in module_names:
        module = __import__(module_name, fromlist=["*"])
        raw_origin = getattr(module, "__file__", None)
        if not isinstance(raw_origin, str) or not raw_origin.strip():
            spec = getattr(module, "__spec__", None)
            raw_origin = getattr(spec, "origin", None)
        if not isinstance(raw_origin, str) or not raw_origin.strip():
            continue
        try:
            module_path = Path(raw_origin).resolve()
        except OSError:
            module_path = Path(raw_origin)
        import_root = module_path
        if module_path.name == "__init__.py" or module_path.name.startswith("__init__."):
            import_root = module_path.parent
        for _ in module_name.split("."):
            import_root = import_root.parent
        normalized = str(import_root)
        if normalized in seen:
            continue
        seen.add(normalized)
        roots.append(normalized)
    return tuple(roots)


def _projected_runtime_manifest_payload() -> dict[str, object]:
    atelier_import_root = Path(__file__).resolve().parent.parent
    package_init = atelier_import_root / "atelier" / "__init__.py"
    if not package_init.is_file():
        raise OSError(
            "projected runtime manifest could not prove the Atelier import root "
            f"at {atelier_import_root}"
        )
    try:
        selected_interpreter = str(Path(sys.executable).resolve())
    except OSError:
        selected_interpreter = str(sys.executable)
    pythonpath_entries = _projected_runtime_pythonpath_entries()
    if not pythonpath_entries:
        pythonpath_entries = (str(atelier_import_root),)
    return {
        "schema_version": 1,
        "status": "converged",
        "helper_session_id": _projected_runtime_helper_session_id(),
        "selected_interpreter": selected_interpreter,
        "atelier_import_root": str(atelier_import_root),
        "pythonpath_entries": list(pythonpath_entries),
    }


def _validate_projected_runtime_manifest(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise OSError("projected runtime manifest readback was not a JSON object")
    if payload.get("status") != "converged":
        raise OSError("projected runtime manifest readback did not prove convergence")
    helper_session_id = str(payload.get("helper_session_id", "")).strip()
    selected_interpreter = str(payload.get("selected_interpreter", "")).strip()
    import_root = str(payload.get("atelier_import_root", "")).strip()
    pythonpath_entries = payload.get("pythonpath_entries")
    if not helper_session_id:
        raise OSError("projected runtime manifest readback is missing helper_session_id")
    if not selected_interpreter:
        raise OSError("projected runtime manifest readback is missing selected_interpreter")
    if not import_root:
        raise OSError("projected runtime manifest readback is missing atelier_import_root")
    if not isinstance(pythonpath_entries, list) or not pythonpath_entries:
        raise OSError("projected runtime manifest readback is missing pythonpath_entries")
    package_init = Path(import_root) / "atelier" / "__init__.py"
    if not package_init.is_file():
        raise OSError(
            "projected runtime manifest readback does not point at an importable "
            f"Atelier root: {import_root}"
        )
    return payload


def _write_projected_runtime_manifest(workspace_dir: Path) -> None:
    manifest_path = _projected_runtime_manifest_path(workspace_dir)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    payload = _projected_runtime_manifest_payload()
    serialized = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=manifest_path.parent,
            prefix=f".{manifest_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(serialized)
            handle.flush()
            tmp_path = Path(handle.name)
        tmp_path.replace(manifest_path)
        readback = json.loads(manifest_path.read_text(encoding="utf-8"))
        _validate_projected_runtime_manifest(readback)
    except Exception as exc:
        if tmp_path is not None:
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise OSError(f"projected runtime manifest write failed: {exc}") from exc


def _write_projected_support_manifest(workspace_dir: Path) -> None:
    manifest_path = _projected_support_manifest_path(workspace_dir)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    payload = _projected_runtime_manifest_payload()
    serialized = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=manifest_path.parent,
            prefix=f".{manifest_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(serialized)
            handle.flush()
            tmp_path = Path(handle.name)
        tmp_path.replace(manifest_path)
        readback = json.loads(manifest_path.read_text(encoding="utf-8"))
        _validate_projected_runtime_manifest(readback)
    except Exception as exc:
        if tmp_path is not None:
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise OSError(f"projected support manifest write failed: {exc}") from exc


def _projected_support_manifest_requires_backfill(workspace_dir: Path) -> bool:
    manifest_path = _projected_support_manifest_path(workspace_dir)
    if not manifest_path.is_file():
        return True
    try:
        readback = json.loads(manifest_path.read_text(encoding="utf-8"))
        _validate_projected_runtime_manifest(readback)
    except Exception:
        return True
    return False


def _projected_runtime_manifest_requires_backfill(workspace_dir: Path) -> bool:
    manifest_path = _projected_runtime_manifest_path(workspace_dir)
    if not manifest_path.is_file():
        return True
    try:
        readback = json.loads(manifest_path.read_text(encoding="utf-8"))
        _validate_projected_runtime_manifest(readback)
    except Exception:
        return True
    return False


def _repair_projected_runtime_manifests(workspace_dir: Path) -> tuple[bool, bool]:
    with _skills_write_lock(workspace_dir):
        repaired_support = False
        repaired_runtime = False
        if _projected_support_manifest_requires_backfill(workspace_dir):
            _write_projected_support_manifest(workspace_dir)
            repaired_support = True
        if _projected_runtime_manifest_requires_backfill(workspace_dir):
            _write_projected_runtime_manifest(workspace_dir)
            repaired_runtime = True
        return repaired_support, repaired_runtime

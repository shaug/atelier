"""Skill loading and workspace projection helpers."""

from __future__ import annotations

import hashlib
import os
import shutil
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
        if not (skill_dir / "SKILL.md").is_file():
            return False
        if _hash_dir(skill_dir) != definition.digest:
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
        skill_root = root.joinpath(name)
        files = _collect_files(skill_root, Path())
        digest = _hash_files(files)
        definitions[name] = SkillDefinition(name=name, files=files, digest=digest)
    return definitions


def packaged_skill_metadata() -> dict[str, dict[str, str]]:
    definitions = load_packaged_skills()
    return {
        name: {"version": __version__, "hash": definition.digest}
        for name, definition in definitions.items()
    }


def _hash_dir(root: Path) -> str:
    files: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel_path = path.relative_to(root).as_posix()
        files[rel_path] = path.read_bytes()
    return _hash_files(files)


def workspace_skill_state(
    workspace_dir: Path,
    stored_metadata: dict[str, object] | None,
) -> SkillWorkspaceState:
    definitions = load_packaged_skills()
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
        actual_hash = _hash_dir(skill_dir)
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
    definitions = load_packaged_skills()
    skills_dir = workspace_dir / paths.SKILLS_DIRNAME
    with _skills_write_lock(workspace_dir):
        staging_dir = _stage_skills_tree(workspace_dir, definitions)
        _install_staged_skills(
            workspace_dir,
            skills_dir,
            staging_dir,
            definitions,
        )
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
        return ProjectSkillsSyncResult(skills_dir=skills_dir, action="up_to_date")
    if dry_run:
        return ProjectSkillsSyncResult(
            skills_dir=skills_dir,
            action="would_update",
        )
    install_workspace_skills(project_dir)
    return ProjectSkillsSyncResult(skills_dir=skills_dir, action="updated")

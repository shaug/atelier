"""Skill loading and workspace projection helpers."""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from . import __version__, paths


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


def _skills_root() -> resources.abc.Traversable:
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


def _collect_files(root: resources.abc.Traversable, prefix: Path) -> dict[str, bytes]:
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
        payload: dict[str, object] = {}
        if isinstance(entry, dict):
            payload = entry
        elif hasattr(entry, "model_dump"):
            payload = entry.model_dump()
        elif hasattr(entry, "version") or hasattr(entry, "hash"):
            payload = {
                "version": getattr(entry, "version", None),
                "hash": getattr(entry, "hash", None),
            }
        version = payload.get("version")
        digest = payload.get("hash")
        if version is None and digest is None:
            continue
        stored[name] = {
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
    if skills_dir.exists():
        if skills_dir.is_symlink() or skills_dir.is_file():
            skills_dir.unlink()
        else:
            shutil.rmtree(skills_dir)
    for definition in definitions.values():
        for rel_path, payload in definition.files.items():
            dest = skills_dir / definition.name / rel_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(payload)
    return {
        name: {"version": __version__, "hash": definition.digest}
        for name, definition in definitions.items()
    }

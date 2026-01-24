"""Implementation for the ``atelier remove`` command."""

from __future__ import annotations

import shutil
from pathlib import Path

from .. import config, git, paths
from ..io import confirm, die, say, warn


def _confirm_remove_project(name: str) -> bool:
    return confirm(f"Delete project {name}?", default=False)


def _confirm_remove_all() -> bool:
    return confirm("Delete all Atelier projects?", default=False)


def _confirm_remove_installed() -> bool:
    return confirm(
        "Delete the entire Atelier data directory (projects + templates)?",
        default=False,
    )


def _project_dirs(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return [path for path in sorted(root.iterdir()) if path.is_dir()]


def _safe_load_json(path: Path) -> dict | None:
    try:
        return config.load_json(path)
    except Exception as exc:
        warn(f"failed to read {path}: {exc}")
        return None


def _project_enlistment(project_dir: Path) -> str | None:
    candidates = [
        paths.project_config_sys_path(project_dir),
        paths.project_config_legacy_path(project_dir),
    ]
    for path in candidates:
        if not path.exists():
            continue
        payload = _safe_load_json(path)
        if not payload:
            continue
        project = payload.get("project")
        if not isinstance(project, dict):
            continue
        enlistment = project.get("enlistment")
        if isinstance(enlistment, str):
            enlistment = enlistment.strip()
        if enlistment:
            return enlistment
    return None


def _project_orphan_reason(project_dir: Path) -> str | None:
    sys_path = paths.project_config_sys_path(project_dir)
    legacy_path = paths.project_config_legacy_path(project_dir)
    if not sys_path.exists() and not legacy_path.exists():
        return "missing config"
    enlistment = _project_enlistment(project_dir)
    if not enlistment:
        return "missing enlistment"
    if not Path(enlistment).exists():
        return "enlistment missing"
    return None


def _collect_orphaned_projects(project_dirs: list[Path]) -> list[tuple[Path, str]]:
    orphaned: list[tuple[Path, str]] = []
    for project_dir in project_dirs:
        reason = _project_orphan_reason(project_dir)
        if reason:
            orphaned.append((project_dir, reason))
    return orphaned


def _fuzzy_match(name: str, candidates: list[str]) -> list[str]:
    needle = name.strip().lower()
    if not needle:
        return []
    return [candidate for candidate in candidates if needle in candidate.lower()]


def _resolve_project_from_enlistment(
    enlistment_path: str, origin: str | None, project_dirs: list[Path]
) -> Path | None:
    expected = paths.project_dir_for_enlistment(enlistment_path, origin)
    if expected.exists():
        return expected
    normalized_target = str(Path(enlistment_path).resolve())
    matches = []
    for project_dir in project_dirs:
        enlistment = _project_enlistment(project_dir)
        if not enlistment:
            continue
        if str(Path(enlistment).resolve()) == normalized_target:
            matches.append(project_dir)
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        die(
            "multiple project entries match this enlistment; "
            "use an explicit project directory name"
        )
    return None


def _delete_project(project_dir: Path) -> None:
    try:
        shutil.rmtree(project_dir)
    except OSError as exc:
        warn(f"failed to delete project {project_dir.name}: {exc}")
        return
    say(f"Deleted project {project_dir.name}")


def remove_projects(args: object) -> None:
    """Remove projects from the Atelier data directory."""
    project_name = getattr(args, "project", None)
    all_projects = bool(getattr(args, "all", False))
    installed = bool(getattr(args, "installed", False))
    orphans = bool(getattr(args, "orphans", False))

    if installed and (project_name or all_projects or orphans):
        die("cannot combine --installed with other remove options")
    if all_projects and (project_name or orphans):
        die("cannot combine --all with other remove options")
    if orphans and project_name:
        die("cannot combine --orphans with a project name")

    data_dir = paths.atelier_data_dir()
    projects_root = paths.projects_root()
    project_dirs = _project_dirs(projects_root)

    if installed:
        if not data_dir.exists():
            say("No Atelier data directory found.")
            return
        if not _confirm_remove_installed():
            say("Aborted.")
            return
        try:
            shutil.rmtree(data_dir)
        except OSError as exc:
            warn(f"failed to delete Atelier data directory: {exc}")
            return
        say("Deleted Atelier data directory.")
        return

    if all_projects:
        if not project_dirs:
            say("No projects found.")
            return
        if not _confirm_remove_all():
            say("Aborted.")
            return
        for project_dir in project_dirs:
            _delete_project(project_dir)
        return

    if orphans:
        if not project_dirs:
            say("No projects found.")
            return
        orphaned = _collect_orphaned_projects(project_dirs)
        if not orphaned:
            say("No orphaned projects found.")
            return
        for project_dir, reason in orphaned:
            if not _confirm_remove_project(f"{project_dir.name} ({reason})"):
                say(f"Skipped project {project_dir.name}")
                continue
            _delete_project(project_dir)
        return

    if project_name:
        if "/" in project_name or "\\" in project_name:
            die("project name must be a directory name, not a path")
        names = [path.name for path in project_dirs]
        if project_name in names:
            target = projects_root / project_name
            if not _confirm_remove_project(project_name):
                say(f"Skipped project {project_name}")
                return
            _delete_project(target)
            return
        matches = _fuzzy_match(project_name, names)
        if len(matches) == 1:
            match = matches[0]
            if not _confirm_remove_project(f"{match} (matched from {project_name})"):
                say(f"Skipped project {match}")
                return
            _delete_project(projects_root / match)
            return
        if matches:
            die(
                "no exact match found; multiple fuzzy matches: "
                + ", ".join(sorted(matches))
            )
        die(f"project not found: {project_name}")

    try:
        _, enlistment_path, _, origin = git.resolve_repo_enlistment(Path.cwd())
    except SystemExit:
        die("project name required when not in a git repository")
    target = _resolve_project_from_enlistment(enlistment_path, origin, project_dirs)
    if not target:
        say("No project entry found for this repo.")
        return
    if not _confirm_remove_project(target.name):
        say(f"Skipped project {target.name}")
        return
    _delete_project(target)

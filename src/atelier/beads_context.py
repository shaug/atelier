"""Shared Beads-root resolution helpers for skill scripts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import config, git
from .commands.resolve import resolve_current_project_with_repo_root, resolve_project_for_enlistment


@dataclass(frozen=True)
class BeadsContext:
    """Resolved Beads/runtime context for startup and planning scripts."""

    beads_root: Path
    project_beads_root: Path
    repo_root: Path
    override_warning: str | None = None


def _resolve_project_context(*, repo_dir: str | None) -> tuple[Path, config.ProjectConfig, Path]:
    repo_hint = str(repo_dir or "").strip()
    if not repo_hint:
        project_root, project_config, _enlistment, repo_root = (
            resolve_current_project_with_repo_root()
        )
        return project_root, project_config, repo_root

    repo_root_hint = Path(repo_hint).expanduser().resolve()
    repo_root, enlistment_path, _origin_raw, origin = git.resolve_repo_enlistment(repo_root_hint)
    project_root, project_config, _resolved_enlistment = resolve_project_for_enlistment(
        enlistment_path, origin
    )
    return project_root, project_config, repo_root


def resolve_skill_beads_context(
    *, beads_dir: str | None, repo_dir: str | None = None
) -> BeadsContext:
    """Resolve script Beads context with project root as the default source.

    Args:
        beads_dir: Optional explicit ``--beads-dir`` value.
        repo_dir: Optional explicit repository directory (for ``ATELIER_PROJECT``).

    Returns:
        Resolved Beads context. Defaults to the project-scoped Beads root and
        emits an override warning only when an explicit non-project override is
        supplied.
    """
    project_root, project_config, repo_root = _resolve_project_context(repo_dir=repo_dir)
    project_data_dir = config.resolve_project_data_dir(project_root, project_config)
    project_beads_root = config.resolve_beads_root(project_data_dir, repo_root)

    beads_dir_value = str(beads_dir or "").strip()
    if not beads_dir_value:
        return BeadsContext(
            beads_root=project_beads_root,
            project_beads_root=project_beads_root,
            repo_root=repo_root,
            override_warning=None,
        )

    override_root = Path(beads_dir_value).expanduser().resolve()
    warning = None
    if override_root != project_beads_root:
        warning = (
            "warning: explicit --beads-dir override points at a non-project Beads store.\n"
            f"project_beads_root={project_beads_root}\n"
            f"override_beads_root={override_root}"
        )

    return BeadsContext(
        beads_root=override_root,
        project_beads_root=project_beads_root,
        repo_root=repo_root,
        override_warning=warning,
    )

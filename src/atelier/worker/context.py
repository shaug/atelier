"""Typed worker runtime contexts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .. import config


@dataclass(frozen=True)
class WorkerProjectContext:
    """Project-scoped values shared by worker services."""

    project_root: Path
    project_data_dir: Path
    repo_root: Path
    beads_root: Path
    git_path: str | None
    project_config: config.ProjectConfig
    repo_slug: str | None


@dataclass(frozen=True)
class WorkerRunContext:
    """Execution values for one worker run loop iteration."""

    mode: str
    dry_run: bool
    session_key: str


@dataclass(frozen=True)
class ChangesetSelectionContext:
    """Inputs needed to resolve the next changeset."""

    selected_epic: str
    startup_changeset_id: str | None
    beads_root: Path
    repo_root: Path
    repo_slug: str | None
    branch_pr: bool
    branch_pr_strategy: object
    git_path: str | None

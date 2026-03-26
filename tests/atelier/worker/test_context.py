from __future__ import annotations

from pathlib import Path

import pytest

from atelier import config
from atelier.worker.context import (
    ChangesetSelectionContext,
    WorkerProjectContext,
    WorkerRunContext,
)


def test_worker_project_context_tracks_repo_and_beads_roots() -> None:
    payload = WorkerProjectContext(
        project_root=Path("/project"),
        project_data_dir=Path("/project/.atelier"),
        repo_root=Path("/repo"),
        beads_root=Path("/project/.beads"),
        git_path="git",
        project_config=config.ProjectConfig(),
        repo_slug="org/repo",
    )

    assert payload.project_root == Path("/project")
    assert payload.repo_root == Path("/repo")
    assert payload.beads_root == Path("/project/.beads")
    assert payload.repo_slug == "org/repo"


def test_worker_run_context_is_frozen() -> None:
    payload = WorkerRunContext(mode="auto", dry_run=False, session_key="worker-1")

    with pytest.raises(AttributeError):
        payload.mode = "prompt"  # type: ignore[misc]


def test_changeset_selection_context_captures_startup_override() -> None:
    payload = ChangesetSelectionContext(
        selected_epic="at-epic",
        startup_changeset_id="at-epic.2",
    )

    assert payload.selected_epic == "at-epic"
    assert payload.startup_changeset_id == "at-epic.2"

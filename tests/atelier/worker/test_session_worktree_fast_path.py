from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from atelier import worktrees
from atelier.worker.session import worktree_fast_path


def _context(
    tmp_path: Path, *, changeset_id: str = "at-epic.1"
) -> worktree_fast_path.SelectedScopeValidationContext:
    return worktree_fast_path.SelectedScopeValidationContext(
        project_data_dir=tmp_path,
        repo_root=Path("/repo"),
        beads_root=Path("/beads"),
        selected_epic="at-epic",
        changeset_id=changeset_id,
        root_branch="feat/root",
        git_path="git",
    )


def _issue(*, root_branch: str | None = None, work_branch: str | None = None) -> dict[str, object]:
    lines: list[str] = []
    if root_branch is not None:
        lines.append(f"changeset.root_branch: {root_branch}")
    if work_branch is not None:
        lines.append(f"changeset.work_branch: {work_branch}")
    return {"id": "at-epic.1", "description": "\n".join(lines)}


def test_validate_selected_scope_reports_safe_reuse_for_coherent_local_state(
    tmp_path: Path,
) -> None:
    worktrees.write_mapping(
        worktrees.mapping_path(tmp_path, "at-epic"),
        worktrees.WorktreeMapping(
            epic_id="at-epic",
            worktree_path="worktrees/at-epic",
            root_branch="feat/root",
            changesets={"at-epic.1": "feat/root-at-epic.1"},
            changeset_worktrees={"at-epic.1": "worktrees/at-epic.1"},
        ),
    )
    selected_worktree = tmp_path / "worktrees" / "at-epic.1"
    selected_worktree.mkdir(parents=True)
    (selected_worktree / ".git").write_text("gitdir: /tmp/gitdir", encoding="utf-8")

    with (
        patch(
            "atelier.worker.session.worktree_fast_path.beads.run_bd_json",
            return_value=[_issue(root_branch="feat/root", work_branch="feat/root-at-epic.1")],
        ),
        patch(
            "atelier.worker.session.worktree_fast_path.git.git_current_branch",
            return_value="feat/root-at-epic.1",
        ),
    ):
        result = worktree_fast_path.validate_selected_scope(context=_context(tmp_path))

    assert result.outcome is worktree_fast_path.SelectedScopeValidationOutcome.SAFE_REUSE
    assert result.safe_reuse is True
    assert result.mapping_epic_id == "at-epic"
    assert result.worktree_path == selected_worktree
    assert result.expected_work_branch == "feat/root-at-epic.1"
    assert result.checked_out_branch == "feat/root-at-epic.1"
    assert result.signals[0].code == "selected-scope-reusable"


def test_validate_selected_scope_reports_local_create_when_selected_mapping_has_no_lineage(
    tmp_path: Path,
) -> None:
    worktrees.write_mapping(
        worktrees.mapping_path(tmp_path, "at-epic"),
        worktrees.WorktreeMapping(
            epic_id="at-epic",
            worktree_path="worktrees/at-epic",
            root_branch="feat/root",
            changesets={},
            changeset_worktrees={},
        ),
    )

    with patch(
        "atelier.worker.session.worktree_fast_path.beads.run_bd_json",
        return_value=[_issue()],
    ):
        result = worktree_fast_path.validate_selected_scope(context=_context(tmp_path))

    assert result.outcome is worktree_fast_path.SelectedScopeValidationOutcome.LOCAL_CREATE
    assert result.mapping_epic_id == "at-epic"
    assert result.worktree_path == tmp_path / "worktrees" / "at-epic.1"
    assert result.expected_work_branch == "feat/root-at-epic.1"
    assert result.checked_out_branch is None
    assert result.signals[0].code == "selected-scope-create-locally"


def test_validate_selected_scope_requires_fallback_when_metadata_exists_without_mapping(
    tmp_path: Path,
) -> None:
    with patch(
        "atelier.worker.session.worktree_fast_path.beads.run_bd_json",
        return_value=[_issue(root_branch="feat/root", work_branch="feat/root-at-epic.1")],
    ):
        result = worktree_fast_path.validate_selected_scope(context=_context(tmp_path))

    assert (
        result.outcome is worktree_fast_path.SelectedScopeValidationOutcome.REQUIRES_FALLBACK_REPAIR
    )
    assert result.mapping_epic_id is None
    assert result.signals[0].code == "selected-scope-metadata-without-mapping"


def test_validate_selected_scope_requires_fallback_when_mapped_worktree_is_missing(
    tmp_path: Path,
) -> None:
    worktrees.write_mapping(
        worktrees.mapping_path(tmp_path, "at-epic"),
        worktrees.WorktreeMapping(
            epic_id="at-epic",
            worktree_path="worktrees/at-epic",
            root_branch="feat/root",
            changesets={"at-epic.1": "feat/root-at-epic.1"},
            changeset_worktrees={"at-epic.1": "worktrees/at-epic.1"},
        ),
    )

    with patch(
        "atelier.worker.session.worktree_fast_path.beads.run_bd_json",
        return_value=[_issue(root_branch="feat/root", work_branch="feat/root-at-epic.1")],
    ):
        result = worktree_fast_path.validate_selected_scope(context=_context(tmp_path))

    assert (
        result.outcome is worktree_fast_path.SelectedScopeValidationOutcome.REQUIRES_FALLBACK_REPAIR
    )
    assert result.signals[0].code == "selected-scope-mapped-worktree-missing"


def test_validate_selected_scope_reports_ambiguous_when_selected_mapping_points_at_other_epic(
    tmp_path: Path,
) -> None:
    worktrees.write_mapping(
        worktrees.mapping_path(tmp_path, "at-epic"),
        worktrees.WorktreeMapping(
            epic_id="at-shadow",
            worktree_path="worktrees/at-shadow",
            root_branch="feat/root",
            changesets={"at-epic.1": "feat/root-at-shadow"},
            changeset_worktrees={"at-epic.1": "worktrees/at-shadow.1"},
        ),
    )

    with patch(
        "atelier.worker.session.worktree_fast_path.beads.run_bd_json",
        return_value=[_issue(root_branch="feat/root", work_branch="feat/root-at-epic.1")],
    ):
        result = worktree_fast_path.validate_selected_scope(context=_context(tmp_path))

    assert result.outcome is worktree_fast_path.SelectedScopeValidationOutcome.AMBIGUOUS
    assert result.mapping_epic_id == "at-shadow"
    assert result.signals[0].code == "selected-scope-mapping-epic-mismatch"

"""Selected-scope validation helpers for worker worktree fast-path reuse."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from ... import beads, changeset_fields, git, worktrees


class SelectedScopeValidationOutcome(str, Enum):
    """Validation outcomes for selected-scope worktree preparation."""

    SAFE_REUSE = "safe_reuse"
    LOCAL_CREATE = "local_create"
    REQUIRES_FALLBACK_REPAIR = "requires_fallback_repair"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class SelectedScopeValidationSignal:
    """A deterministic reason emitted by selected-scope validation."""

    code: str
    summary: str
    details: dict[str, str]


@dataclass(frozen=True)
class SelectedScopeValidationContext:
    """Read-only inputs used to validate selected-scope local state."""

    project_data_dir: Path
    repo_root: Path
    beads_root: Path
    selected_epic: str
    changeset_id: str
    root_branch: str
    git_path: str | None


@dataclass(frozen=True)
class SelectedScopeValidation:
    """Selected-scope local-state decision for worktree preparation."""

    outcome: SelectedScopeValidationOutcome
    mapping_epic_id: str | None
    worktree_path: Path
    expected_work_branch: str
    checked_out_branch: str | None
    signals: tuple[SelectedScopeValidationSignal, ...]

    @property
    def safe_reuse(self) -> bool:
        """Return whether the selected scope can be reused without repair."""

        return self.outcome is SelectedScopeValidationOutcome.SAFE_REUSE


def _normalize_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized or normalized.lower() == "null":
        return None
    return normalized


def _signal(code: str, summary: str, **details: str | None) -> SelectedScopeValidationSignal:
    return SelectedScopeValidationSignal(
        code=code,
        summary=summary,
        details={
            key: value
            for key, raw_value in details.items()
            if (value := _normalize_text(raw_value)) is not None
        },
    )


def _default_selected_worktree_path(
    project_data_dir: Path, *, epic_id: str, changeset_id: str
) -> Path:
    if changeset_id == epic_id:
        return worktrees.worktree_dir(project_data_dir, epic_id)
    return project_data_dir / worktrees.changeset_worktree_relpath(changeset_id)


def _validate_selected_issue(
    *,
    beads_root: Path,
    repo_root: Path,
    changeset_id: str,
) -> tuple[dict[str, object] | None, SelectedScopeValidationSignal | None]:
    try:
        issues = beads.run_bd_json(["show", changeset_id], beads_root=beads_root, cwd=repo_root)
    except SystemExit as exc:
        code = str(exc.code if isinstance(exc.code, int) else 1)
        return None, _signal(
            "selected-changeset-metadata-unreadable",
            "selected changeset metadata could not be read",
            changeset_id=changeset_id,
            bd_exit_code=code,
        )
    if not issues:
        return None, _signal(
            "selected-changeset-metadata-missing",
            "selected changeset metadata is missing",
            changeset_id=changeset_id,
        )
    return issues[0], None


def _resolve_worktree_path(project_data_dir: Path, relpath: str) -> Path:
    candidate = Path(relpath)
    if candidate.is_absolute():
        return candidate
    return project_data_dir / candidate


def validate_selected_scope(*, context: SelectedScopeValidationContext) -> SelectedScopeValidation:
    """Classify selected-scope local state for fast-path worktree preparation.

    The validator is intentionally read-only. It inspects the selected
    changeset's bead metadata, the selected epic mapping, the mapped worktree
    path, and the currently checked out branch to decide whether the worker can
    reuse the selected scope directly, should create missing local state, needs
    fallback repair, or must fail closed due to ambiguity.

    Args:
        context: Selected-scope inputs for the validation check.

    Returns:
        A deterministic validation result with the outcome, expected local
        branch/path, and one or more reason signals.
    """

    selected_epic = context.selected_epic.strip()
    changeset_id = context.changeset_id.strip()
    expected_root = _normalize_text(context.root_branch)
    default_worktree_path = worktrees.worktrees_root(context.project_data_dir)
    if selected_epic:
        if changeset_id == selected_epic:
            default_worktree_path = worktrees.worktree_dir(context.project_data_dir, selected_epic)
        elif changeset_id:
            default_worktree_path = _default_selected_worktree_path(
                context.project_data_dir,
                epic_id=selected_epic,
                changeset_id=changeset_id,
            )
    expected_work_branch = ""
    if expected_root is not None:
        if changeset_id == selected_epic:
            expected_work_branch = expected_root
        elif changeset_id:
            expected_work_branch = worktrees.derive_changeset_branch(expected_root, changeset_id)
    if not selected_epic or not changeset_id or expected_root is None:
        return SelectedScopeValidation(
            outcome=SelectedScopeValidationOutcome.AMBIGUOUS,
            mapping_epic_id=None,
            worktree_path=default_worktree_path,
            expected_work_branch=expected_work_branch,
            checked_out_branch=None,
            signals=(
                _signal(
                    "selected-scope-input-invalid",
                    "selected epic, changeset, or root branch is missing",
                    selected_epic=selected_epic,
                    changeset_id=changeset_id,
                    root_branch=context.root_branch,
                ),
            ),
        )

    issue, issue_error = _validate_selected_issue(
        beads_root=context.beads_root,
        repo_root=context.repo_root,
        changeset_id=changeset_id,
    )
    if issue_error is not None:
        return SelectedScopeValidation(
            outcome=SelectedScopeValidationOutcome.AMBIGUOUS,
            mapping_epic_id=None,
            worktree_path=default_worktree_path,
            expected_work_branch=expected_work_branch,
            checked_out_branch=None,
            signals=(issue_error,),
        )

    metadata_root = _normalize_text(changeset_fields.root_branch(issue or {}))
    metadata_work = _normalize_text(changeset_fields.work_branch(issue or {}))
    selected_mapping_path = worktrees.mapping_path(context.project_data_dir, selected_epic)
    mapping = worktrees.load_mapping(selected_mapping_path)
    if selected_mapping_path.exists() and mapping is None:
        return SelectedScopeValidation(
            outcome=SelectedScopeValidationOutcome.AMBIGUOUS,
            mapping_epic_id=None,
            worktree_path=default_worktree_path,
            expected_work_branch=expected_work_branch,
            checked_out_branch=None,
            signals=(
                _signal(
                    "selected-scope-mapping-invalid",
                    "selected epic mapping file exists but could not be parsed",
                    selected_epic=selected_epic,
                ),
            ),
        )

    if mapping is not None and mapping.epic_id != selected_epic:
        return SelectedScopeValidation(
            outcome=SelectedScopeValidationOutcome.AMBIGUOUS,
            mapping_epic_id=mapping.epic_id,
            worktree_path=default_worktree_path,
            expected_work_branch=expected_work_branch,
            checked_out_branch=None,
            signals=(
                _signal(
                    "selected-scope-mapping-epic-mismatch",
                    "selected epic mapping file points at a different epic",
                    selected_epic=selected_epic,
                    mapping_epic_id=mapping.epic_id,
                ),
            ),
        )

    if mapping is None:
        if metadata_root is not None or metadata_work is not None:
            return SelectedScopeValidation(
                outcome=SelectedScopeValidationOutcome.REQUIRES_FALLBACK_REPAIR,
                mapping_epic_id=None,
                worktree_path=default_worktree_path,
                expected_work_branch=expected_work_branch,
                checked_out_branch=None,
                signals=(
                    _signal(
                        "selected-scope-metadata-without-mapping",
                        "changeset branch metadata exists without a selected mapping",
                        selected_epic=selected_epic,
                        changeset_id=changeset_id,
                        metadata_root=metadata_root,
                        metadata_work=metadata_work,
                    ),
                ),
            )
        if default_worktree_path.exists():
            if (default_worktree_path / ".git").exists():
                return SelectedScopeValidation(
                    outcome=SelectedScopeValidationOutcome.REQUIRES_FALLBACK_REPAIR,
                    mapping_epic_id=None,
                    worktree_path=default_worktree_path,
                    expected_work_branch=expected_work_branch,
                    checked_out_branch=None,
                    signals=(
                        _signal(
                            "selected-scope-unmapped-worktree-exists",
                            "an unmapped worktree already exists for the selected scope",
                            worktree_path=str(default_worktree_path),
                        ),
                    ),
                )
            return SelectedScopeValidation(
                outcome=SelectedScopeValidationOutcome.AMBIGUOUS,
                mapping_epic_id=None,
                worktree_path=default_worktree_path,
                expected_work_branch=expected_work_branch,
                checked_out_branch=None,
                signals=(
                    _signal(
                        "selected-scope-untracked-path-not-git",
                        "the selected-scope path exists but is not a git worktree",
                        worktree_path=str(default_worktree_path),
                    ),
                ),
            )
        return SelectedScopeValidation(
            outcome=SelectedScopeValidationOutcome.LOCAL_CREATE,
            mapping_epic_id=None,
            worktree_path=default_worktree_path,
            expected_work_branch=expected_work_branch,
            checked_out_branch=None,
            signals=(
                _signal(
                    "selected-scope-create-locally",
                    "no selected-scope mapping or worktree exists yet",
                    selected_epic=selected_epic,
                    changeset_id=changeset_id,
                ),
            ),
        )

    mapped_root = _normalize_text(mapping.root_branch)
    if mapped_root is not None and mapped_root != expected_root:
        return SelectedScopeValidation(
            outcome=SelectedScopeValidationOutcome.REQUIRES_FALLBACK_REPAIR,
            mapping_epic_id=mapping.epic_id,
            worktree_path=default_worktree_path,
            expected_work_branch=expected_work_branch,
            checked_out_branch=None,
            signals=(
                _signal(
                    "selected-scope-root-branch-mismatch",
                    "selected mapping root branch disagrees with the selected root branch",
                    mapping_root_branch=mapped_root,
                    selected_root_branch=expected_root,
                ),
            ),
        )

    if metadata_root is not None and metadata_root != expected_root:
        return SelectedScopeValidation(
            outcome=SelectedScopeValidationOutcome.REQUIRES_FALLBACK_REPAIR,
            mapping_epic_id=mapping.epic_id,
            worktree_path=default_worktree_path,
            expected_work_branch=expected_work_branch,
            checked_out_branch=None,
            signals=(
                _signal(
                    "selected-scope-metadata-root-mismatch",
                    "changeset metadata root branch disagrees with the selected root branch",
                    metadata_root_branch=metadata_root,
                    selected_root_branch=expected_root,
                ),
            ),
        )

    if changeset_id == selected_epic:
        expected_work_branch = expected_root
        worktree_relpath = _normalize_text(mapping.worktree_path)
    else:
        mapped_branch = _normalize_text(mapping.changesets.get(changeset_id))
        mapped_relpath = _normalize_text(mapping.changeset_worktrees.get(changeset_id))
        expected_work_branch = mapped_branch or expected_work_branch
        worktree_relpath = mapped_relpath
        if mapped_branch is None and mapped_relpath is None:
            return SelectedScopeValidation(
                outcome=SelectedScopeValidationOutcome.LOCAL_CREATE,
                mapping_epic_id=mapping.epic_id,
                worktree_path=default_worktree_path,
                expected_work_branch=expected_work_branch,
                checked_out_branch=None,
                signals=(
                    _signal(
                        "selected-scope-create-locally",
                        "selected mapping exists but has no local lineage entry yet",
                        selected_epic=selected_epic,
                        changeset_id=changeset_id,
                    ),
                ),
            )
        if mapped_branch is None or mapped_relpath is None:
            return SelectedScopeValidation(
                outcome=SelectedScopeValidationOutcome.REQUIRES_FALLBACK_REPAIR,
                mapping_epic_id=mapping.epic_id,
                worktree_path=default_worktree_path,
                expected_work_branch=expected_work_branch,
                checked_out_branch=None,
                signals=(
                    _signal(
                        "selected-scope-partial-lineage-entry",
                        "selected mapping has only a partial changeset lineage entry",
                        mapped_branch=mapped_branch,
                        mapped_relpath=mapped_relpath,
                    ),
                ),
            )

    if metadata_work is not None and metadata_work != expected_work_branch:
        return SelectedScopeValidation(
            outcome=SelectedScopeValidationOutcome.REQUIRES_FALLBACK_REPAIR,
            mapping_epic_id=mapping.epic_id,
            worktree_path=default_worktree_path,
            expected_work_branch=expected_work_branch,
            checked_out_branch=None,
            signals=(
                _signal(
                    "selected-scope-metadata-work-mismatch",
                    "changeset metadata work branch disagrees with the selected mapping",
                    metadata_work_branch=metadata_work,
                    expected_work_branch=expected_work_branch,
                ),
            ),
        )

    expected_worktree_path = _resolve_worktree_path(
        context.project_data_dir, worktree_relpath or ""
    )
    if not expected_worktree_path.exists():
        return SelectedScopeValidation(
            outcome=SelectedScopeValidationOutcome.REQUIRES_FALLBACK_REPAIR,
            mapping_epic_id=mapping.epic_id,
            worktree_path=expected_worktree_path,
            expected_work_branch=expected_work_branch,
            checked_out_branch=None,
            signals=(
                _signal(
                    "selected-scope-mapped-worktree-missing",
                    "selected mapping points at a missing worktree path",
                    worktree_path=str(expected_worktree_path),
                ),
            ),
        )

    if not (expected_worktree_path / ".git").exists():
        return SelectedScopeValidation(
            outcome=SelectedScopeValidationOutcome.AMBIGUOUS,
            mapping_epic_id=mapping.epic_id,
            worktree_path=expected_worktree_path,
            expected_work_branch=expected_work_branch,
            checked_out_branch=None,
            signals=(
                _signal(
                    "selected-scope-mapped-path-not-git",
                    "selected mapping path exists but is not a git worktree",
                    worktree_path=str(expected_worktree_path),
                ),
            ),
        )

    checked_out_branch = _normalize_text(
        git.git_current_branch(expected_worktree_path, git_path=context.git_path)
    )
    if checked_out_branch is None or checked_out_branch == "HEAD":
        return SelectedScopeValidation(
            outcome=SelectedScopeValidationOutcome.AMBIGUOUS,
            mapping_epic_id=mapping.epic_id,
            worktree_path=expected_worktree_path,
            expected_work_branch=expected_work_branch,
            checked_out_branch=checked_out_branch,
            signals=(
                _signal(
                    "selected-scope-branch-unresolved",
                    "selected worktree is detached or branch detection failed",
                    worktree_path=str(expected_worktree_path),
                    checked_out_branch=checked_out_branch,
                ),
            ),
        )

    if checked_out_branch != expected_work_branch:
        return SelectedScopeValidation(
            outcome=SelectedScopeValidationOutcome.REQUIRES_FALLBACK_REPAIR,
            mapping_epic_id=mapping.epic_id,
            worktree_path=expected_worktree_path,
            expected_work_branch=expected_work_branch,
            checked_out_branch=checked_out_branch,
            signals=(
                _signal(
                    "selected-scope-checked-out-branch-mismatch",
                    "selected worktree branch disagrees with the selected mapping",
                    checked_out_branch=checked_out_branch,
                    expected_work_branch=expected_work_branch,
                ),
            ),
        )

    return SelectedScopeValidation(
        outcome=SelectedScopeValidationOutcome.SAFE_REUSE,
        mapping_epic_id=mapping.epic_id,
        worktree_path=expected_worktree_path,
        expected_work_branch=expected_work_branch,
        checked_out_branch=checked_out_branch,
        signals=(
            _signal(
                "selected-scope-reusable",
                "selected mapping, worktree, and branch state are coherent",
                selected_epic=selected_epic,
                changeset_id=changeset_id,
                worktree_path=str(expected_worktree_path),
                expected_work_branch=expected_work_branch,
            ),
        ),
    )

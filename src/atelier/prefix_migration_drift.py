"""Detect prefix-migration drift across metadata and git worktree state."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from . import beads, changeset_fields, git, prs, worktrees
from . import exec as exec_util


class _PrLookupResult(Protocol):
    @property
    def found(self) -> bool: ...

    @property
    def failed(self) -> bool: ...

    @property
    def payload(self) -> dict[str, object] | None: ...


PrLookupStatus = Callable[[str, str], _PrLookupResult]


@dataclass(frozen=True)
class _GitWorktreeEntry:
    path_key: str
    branch: str | None


@dataclass(frozen=True)
class _GitWorktreeIndex:
    path_to_branch: dict[str, str]
    branch_to_paths: dict[str, tuple[str, ...]]


@dataclass(frozen=True)
class PrefixMigrationRepairAction:
    """Plan or applied repair details for one drifted changeset."""

    epic_id: str
    changeset_id: str
    drift_classes: tuple[str, ...]
    canonical_root_branch: str
    canonical_work_branch: str
    work_branch_source: str
    canonical_worktree_path: str
    worktree_path_source: str
    pr_head_ref: str | None
    pr_lookup_branch: str | None
    update_workspace_root_branch: bool
    update_changeset_metadata: bool
    update_changeset_worktree_path: bool
    update_mapping: bool
    applied: bool

    @property
    def changed(self) -> bool:
        """Return whether this action changes any persisted state."""
        return (
            self.update_workspace_root_branch
            or self.update_changeset_metadata
            or self.update_changeset_worktree_path
            or self.update_mapping
        )

    def as_dict(self) -> dict[str, object]:
        """Serialize this action for status/doctor JSON payloads."""
        return {
            "epic_id": self.epic_id,
            "changeset_id": self.changeset_id,
            "drift_classes": list(self.drift_classes),
            "canonical_root_branch": self.canonical_root_branch,
            "canonical_work_branch": self.canonical_work_branch,
            "work_branch_source": self.work_branch_source,
            "canonical_worktree_path": self.canonical_worktree_path,
            "worktree_path_source": self.worktree_path_source,
            "pr_head_ref": self.pr_head_ref,
            "pr_lookup_branch": self.pr_lookup_branch,
            "changed": self.changed,
            "update_workspace_root_branch": self.update_workspace_root_branch,
            "update_changeset_metadata": self.update_changeset_metadata,
            "update_changeset_worktree_path": self.update_changeset_worktree_path,
            "update_mapping": self.update_mapping,
            "applied": self.applied,
        }


def _normalize_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned or cleaned.lower() == "null":
        return None
    return cleaned


def _normalize_worktree_path(value: object, *, project_data_dir: Path) -> str | None:
    normalized = _normalize_text(value)
    if normalized is None:
        return None
    candidate = Path(normalized)
    if candidate.is_absolute():
        try:
            candidate = candidate.relative_to(project_data_dir)
        except ValueError:
            return candidate.as_posix()
    return candidate.as_posix().lstrip("./")


def _normalize_branch_ref(value: object) -> str | None:
    normalized = _normalize_text(value)
    if normalized is None:
        return None
    prefix = "refs/heads/"
    if normalized.startswith(prefix):
        normalized = normalized[len(prefix) :]
    return normalized


def _parse_git_worktree_entries(raw: str, *, project_data_dir: Path) -> list[_GitWorktreeEntry]:
    entries: list[_GitWorktreeEntry] = []
    current_path: str | None = None
    current_branch: str | None = None

    def flush() -> None:
        nonlocal current_path, current_branch
        if current_path is not None:
            entries.append(_GitWorktreeEntry(path_key=current_path, branch=current_branch))
        current_path = None
        current_branch = None

    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            flush()
            continue
        if stripped.startswith("worktree "):
            current_path = _normalize_worktree_path(
                stripped.split(" ", 1)[1],
                project_data_dir=project_data_dir,
            )
            continue
        if stripped.startswith("branch "):
            current_branch = _normalize_branch_ref(stripped.split(" ", 1)[1])
            continue
    flush()
    return entries


def _collect_git_worktree_index(
    *,
    repo_root: Path,
    project_data_dir: Path,
    git_path: str | None,
) -> _GitWorktreeIndex:
    cmd = git.git_command(
        ["-C", str(repo_root), "worktree", "list", "--porcelain"],
        git_path=git_path,
    )
    result = exec_util.try_run_command(cmd)
    if result is None or result.returncode != 0:
        return _GitWorktreeIndex(path_to_branch={}, branch_to_paths={})
    entries = _parse_git_worktree_entries(result.stdout or "", project_data_dir=project_data_dir)
    path_to_branch: dict[str, str] = {}
    branch_to_paths: dict[str, set[str]] = {}
    for entry in entries:
        if entry.path_key and entry.branch:
            path_to_branch[entry.path_key] = entry.branch
            branch_to_paths.setdefault(entry.branch, set()).add(entry.path_key)
    stable_branch_index = {
        branch: tuple(sorted(paths))
        for branch, paths in sorted(branch_to_paths.items(), key=lambda item: item[0])
    }
    return _GitWorktreeIndex(
        path_to_branch=dict(sorted(path_to_branch.items(), key=lambda item: item[0])),
        branch_to_paths=stable_branch_index,
    )


def _mapped_worktree_lineage(
    *,
    project_data_dir: Path,
    mapping: worktrees.WorktreeMapping | None,
    changeset_id: str,
    git_path: str | None,
) -> tuple[str | None, str | None]:
    if mapping is None:
        return None, None
    mapped_relpath = _normalize_worktree_path(
        mapping.changeset_worktrees.get(changeset_id),
        project_data_dir=project_data_dir,
    )
    if mapped_relpath is None:
        return None, None
    mapped_path_raw = Path(mapped_relpath)
    mapped_path = (
        mapped_path_raw if mapped_path_raw.is_absolute() else project_data_dir / mapped_path_raw
    )
    if not mapped_path.exists() or not (mapped_path / ".git").exists():
        return None, mapped_relpath
    branch = _normalize_text(git.git_current_branch(mapped_path, git_path=git_path))
    if branch is None or branch == "HEAD":
        return None, mapped_relpath
    return branch, mapped_relpath


def _distinct_values(*values: str | None) -> tuple[str, ...]:
    return tuple(sorted({value for value in values if value is not None}))


def _changesets_for_epic(
    epic_id: str,
    *,
    epic_issue: dict[str, object],
    beads_root: Path,
    repo_root: Path,
) -> list[dict[str, object]]:
    descendants = beads.list_descendant_changesets(
        epic_id,
        beads_root=beads_root,
        cwd=repo_root,
        include_closed=True,
    )
    if descendants:
        return descendants
    work_children = beads.list_work_children(
        epic_id,
        beads_root=beads_root,
        cwd=repo_root,
        include_closed=True,
    )
    if work_children:
        return []
    return [epic_issue]


def _lookup_pr_head_branch(
    *,
    repo_slug: str | None,
    candidate_branches: tuple[str, ...],
    lookup_pr_status: PrLookupStatus,
) -> tuple[str | None, str | None]:
    if not repo_slug:
        return None, None
    for branch in candidate_branches:
        lookup = lookup_pr_status(repo_slug, branch)
        if lookup.failed or not lookup.found:
            continue
        payload = lookup.payload if isinstance(lookup.payload, dict) else None
        if payload is None:
            continue
        head = _normalize_branch_ref(payload.get("headRefName"))
        if head:
            return head, branch
    return None, None


def _record(
    *,
    epic_id: str,
    changeset_id: str,
    drift_class: str,
    values: dict[str, str | None],
) -> dict[str, object]:
    return {
        "epic_id": epic_id,
        "changeset_id": changeset_id,
        "drift_class": drift_class,
        "values": {key: values[key] for key in sorted(values)},
    }


def _canonical_root_branch(*values: str | None) -> str | None:
    for value in values:
        if value is not None:
            return value
    return None


def _drift_classes_by_changeset(
    records: list[dict[str, object]],
) -> dict[tuple[str, str], tuple[str, ...]]:
    grouped: dict[tuple[str, str], set[str]] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        epic_id = _normalize_text(record.get("epic_id"))
        changeset_id = _normalize_text(record.get("changeset_id"))
        drift_class = _normalize_text(record.get("drift_class"))
        if epic_id is None or changeset_id is None or drift_class is None:
            continue
        grouped.setdefault((epic_id, changeset_id), set()).add(drift_class)
    return {
        key: tuple(sorted(values))
        for key, values in sorted(grouped.items(), key=lambda item: item[0])
    }


def _resolve_repair_action(
    *,
    project_data_dir: Path,
    repo_slug: str | None,
    epic_id: str,
    epic_issue: dict[str, object],
    changeset_id: str,
    changeset_issue: dict[str, object],
    mapping: worktrees.WorktreeMapping | None,
    git_index: _GitWorktreeIndex,
    drift_classes: tuple[str, ...],
    lookup_pr_status: PrLookupStatus,
    git_path: str | None,
) -> PrefixMigrationRepairAction | None:
    metadata_fields = changeset_fields.issue_fields(changeset_issue)
    metadata_root_branch = _normalize_text(
        changeset_fields.normalized_field(metadata_fields, "changeset.root_branch")
    )
    metadata_work_branch = _normalize_text(
        changeset_fields.normalized_field(metadata_fields, "changeset.work_branch")
    )
    metadata_worktree_path = _normalize_worktree_path(
        metadata_fields.get("worktree_path"),
        project_data_dir=project_data_dir,
    )
    epic_root_branch = _normalize_text(beads.extract_workspace_root_branch(epic_issue))
    mapping_root_branch = _normalize_text(mapping.root_branch) if mapping is not None else None
    mapping_work_branch = (
        _normalize_text(mapping.changesets.get(changeset_id)) if mapping is not None else None
    )
    mapping_worktree_path = (
        _normalize_worktree_path(
            mapping.changeset_worktrees.get(changeset_id),
            project_data_dir=project_data_dir,
        )
        if mapping is not None
        else None
    )
    mapped_branch, mapped_relpath = _mapped_worktree_lineage(
        project_data_dir=project_data_dir,
        mapping=mapping,
        changeset_id=changeset_id,
        git_path=git_path,
    )
    canonical_root = _canonical_root_branch(
        epic_root_branch,
        mapping_root_branch,
        metadata_root_branch,
        metadata_work_branch,
    )
    if canonical_root is None:
        return None

    derived_work_branch = worktrees.derive_changeset_branch(canonical_root, changeset_id)
    pr_head_ref: str | None = None
    pr_lookup_branch: str | None = None
    if changeset_id != epic_id:
        candidate_branches = tuple(
            sorted(
                {
                    value
                    for value in (
                        metadata_work_branch,
                        mapping_work_branch,
                        derived_work_branch,
                        mapped_branch,
                    )
                    if value is not None
                }
            )
        )
        pr_head_ref, pr_lookup_branch = _lookup_pr_head_branch(
            repo_slug=repo_slug,
            candidate_branches=candidate_branches,
            lookup_pr_status=lookup_pr_status,
        )

    filesystem_path_for_metadata_branch = None
    if metadata_work_branch is not None:
        paths = git_index.branch_to_paths.get(metadata_work_branch)
        if paths:
            filesystem_path_for_metadata_branch = paths[0]
    filesystem_path_for_canonical_branch = None
    if changeset_id == epic_id:
        canonical_branch_paths = git_index.branch_to_paths.get(canonical_root)
        if canonical_branch_paths:
            filesystem_path_for_canonical_branch = canonical_branch_paths[0]

    if changeset_id == epic_id:
        canonical_work_branch = canonical_root
        work_branch_source = "epic-root"
        if mapped_branch is not None and mapped_relpath is not None:
            canonical_worktree = mapped_relpath
            worktree_source = "checked-out-worktree"
        elif filesystem_path_for_canonical_branch is not None:
            canonical_worktree = filesystem_path_for_canonical_branch
            worktree_source = "filesystem-canonical-branch"
        elif mapping_worktree_path is not None:
            canonical_worktree = mapping_worktree_path
            worktree_source = "mapping"
        else:
            canonical_worktree = worktrees.changeset_worktree_relpath(changeset_id)
            worktree_source = "default"
    else:
        if pr_head_ref is not None:
            canonical_work_branch = pr_head_ref
            work_branch_source = "open-pr-head"
        elif mapped_branch is not None:
            canonical_work_branch = mapped_branch
            work_branch_source = "checked-out-worktree"
        elif mapping_work_branch is not None:
            canonical_work_branch = mapping_work_branch
            work_branch_source = "mapping"
        elif metadata_work_branch is not None:
            canonical_work_branch = metadata_work_branch
            work_branch_source = "metadata"
        else:
            canonical_work_branch = derived_work_branch
            work_branch_source = "derived"

        canonical_branch_paths = git_index.branch_to_paths.get(canonical_work_branch)
        if canonical_branch_paths:
            filesystem_path_for_canonical_branch = canonical_branch_paths[0]

        if mapped_branch is not None and mapped_relpath is not None:
            canonical_worktree = mapped_relpath
            worktree_source = "checked-out-worktree"
        elif filesystem_path_for_canonical_branch is not None:
            canonical_worktree = filesystem_path_for_canonical_branch
            worktree_source = "filesystem-canonical-branch"
        elif filesystem_path_for_metadata_branch is not None:
            canonical_worktree = filesystem_path_for_metadata_branch
            worktree_source = "filesystem-metadata-branch"
        elif mapping_worktree_path is not None:
            canonical_worktree = mapping_worktree_path
            worktree_source = "mapping"
        elif metadata_worktree_path is not None:
            canonical_worktree = metadata_worktree_path
            worktree_source = "metadata"
        else:
            canonical_worktree = worktrees.changeset_worktree_relpath(changeset_id)
            worktree_source = "default"

    update_workspace_root_branch = epic_root_branch is None
    update_changeset_metadata = (
        metadata_root_branch != canonical_root or metadata_work_branch != canonical_work_branch
    )
    update_changeset_worktree_path = (
        metadata_worktree_path is not None and metadata_worktree_path != canonical_worktree
    )
    update_mapping = mapping is not None and (
        mapping_root_branch != canonical_root
        or mapping_work_branch != canonical_work_branch
        or mapping_worktree_path != canonical_worktree
    )
    return PrefixMigrationRepairAction(
        epic_id=epic_id,
        changeset_id=changeset_id,
        drift_classes=drift_classes,
        canonical_root_branch=canonical_root,
        canonical_work_branch=canonical_work_branch,
        work_branch_source=work_branch_source,
        canonical_worktree_path=canonical_worktree,
        worktree_path_source=worktree_source,
        pr_head_ref=pr_head_ref,
        pr_lookup_branch=pr_lookup_branch,
        update_workspace_root_branch=update_workspace_root_branch,
        update_changeset_metadata=update_changeset_metadata,
        update_changeset_worktree_path=update_changeset_worktree_path,
        update_mapping=update_mapping,
        applied=False,
    )


def _update_mapping_lineage(
    *,
    project_data_dir: Path,
    epic_id: str,
    changeset_id: str,
    canonical_root_branch: str,
    canonical_work_branch: str,
    canonical_worktree_path: str,
) -> tuple[worktrees.WorktreeMapping | None, bool]:
    with worktrees.worktree_state_lock(project_data_dir):
        path = worktrees.mapping_path(project_data_dir, epic_id)
        current = worktrees.load_mapping(path)
        if current is None:
            return None, False
        updated = worktrees.WorktreeMapping(
            epic_id=current.epic_id,
            worktree_path=current.worktree_path,
            root_branch=canonical_root_branch,
            changesets={
                **current.changesets,
                changeset_id: canonical_work_branch,
            },
            changeset_worktrees={
                **current.changeset_worktrees,
                changeset_id: canonical_worktree_path,
            },
        )
        if updated == current:
            return current, False
        worktrees.write_mapping(path, updated)
        return updated, True


def repair_prefix_migration_drift(
    *,
    project_data_dir: Path,
    beads_root: Path,
    repo_root: Path,
    apply: bool = False,
    repo_slug: str | None = None,
    git_path: str | None = None,
    lookup_pr_status: PrLookupStatus = prs.lookup_github_pr_status,
) -> list[PrefixMigrationRepairAction]:
    """Plan or apply deterministic repairs for prefix-migration drift.

    Args:
        project_data_dir: Project data directory with worktree metadata.
        beads_root: Project-scoped Beads store.
        repo_root: Repository root used for Beads and git lookups.
        apply: When ``True``, persist canonical repairs. Default is read-only.
        repo_slug: Optional GitHub ``owner/name`` for PR-head evidence.
        git_path: Optional git executable override.
        lookup_pr_status: PR lookup adapter for tests and runtime injection.

    Returns:
        Planned or applied actions for drifted changesets, sorted
        deterministically by changeset id and drift class set.
    """
    drift_records = scan_prefix_migration_drift(
        project_data_dir=project_data_dir,
        beads_root=beads_root,
        repo_root=repo_root,
        repo_slug=repo_slug,
        git_path=git_path,
        lookup_pr_status=lookup_pr_status,
    )
    drift_classes = _drift_classes_by_changeset(drift_records)
    if not drift_classes:
        return []

    git_index = _collect_git_worktree_index(
        repo_root=repo_root,
        project_data_dir=project_data_dir,
        git_path=git_path,
    )
    actions: list[PrefixMigrationRepairAction] = []
    epics = beads.list_epics(beads_root=beads_root, cwd=repo_root, include_closed=True)
    for epic_issue in sorted(epics, key=lambda issue: str(issue.get("id") or "")):
        epic_id = _normalize_text(epic_issue.get("id"))
        if epic_id is None:
            continue
        mapping = worktrees.load_mapping(worktrees.mapping_path(project_data_dir, epic_id))
        changesets = _changesets_for_epic(
            epic_id,
            epic_issue=epic_issue,
            beads_root=beads_root,
            repo_root=repo_root,
        )
        for changeset in sorted(changesets, key=lambda issue: str(issue.get("id") or "")):
            changeset_id = _normalize_text(changeset.get("id"))
            if changeset_id is None:
                continue
            key = (epic_id, changeset_id)
            if key not in drift_classes:
                continue
            action = _resolve_repair_action(
                project_data_dir=project_data_dir,
                repo_slug=repo_slug,
                epic_id=epic_id,
                epic_issue=epic_issue,
                changeset_id=changeset_id,
                changeset_issue=changeset,
                mapping=mapping,
                git_index=git_index,
                drift_classes=drift_classes[key],
                lookup_pr_status=lookup_pr_status,
                git_path=git_path,
            )
            if action is None:
                continue

            applied = False
            if apply and action.changed:
                if action.update_workspace_root_branch:
                    beads.update_workspace_root_branch(
                        epic_id,
                        action.canonical_root_branch,
                        beads_root=beads_root,
                        cwd=repo_root,
                        allow_override=True,
                    )
                if action.update_changeset_metadata:
                    beads.update_changeset_branch_metadata(
                        changeset_id,
                        root_branch=action.canonical_root_branch,
                        parent_branch=None,
                        work_branch=action.canonical_work_branch,
                        beads_root=beads_root,
                        cwd=repo_root,
                        allow_override=True,
                    )
                if action.update_changeset_worktree_path:
                    beads.update_worktree_path(
                        changeset_id,
                        action.canonical_worktree_path,
                        beads_root=beads_root,
                        cwd=repo_root,
                        allow_override=True,
                    )
                if action.update_mapping:
                    mapping, _changed = _update_mapping_lineage(
                        project_data_dir=project_data_dir,
                        epic_id=epic_id,
                        changeset_id=changeset_id,
                        canonical_root_branch=action.canonical_root_branch,
                        canonical_work_branch=action.canonical_work_branch,
                        canonical_worktree_path=action.canonical_worktree_path,
                    )
                applied = True

            actions.append(
                PrefixMigrationRepairAction(
                    epic_id=action.epic_id,
                    changeset_id=action.changeset_id,
                    drift_classes=action.drift_classes,
                    canonical_root_branch=action.canonical_root_branch,
                    canonical_work_branch=action.canonical_work_branch,
                    work_branch_source=action.work_branch_source,
                    canonical_worktree_path=action.canonical_worktree_path,
                    worktree_path_source=action.worktree_path_source,
                    pr_head_ref=action.pr_head_ref,
                    pr_lookup_branch=action.pr_lookup_branch,
                    update_workspace_root_branch=action.update_workspace_root_branch,
                    update_changeset_metadata=action.update_changeset_metadata,
                    update_changeset_worktree_path=action.update_changeset_worktree_path,
                    update_mapping=action.update_mapping,
                    applied=applied,
                )
            )
    return sorted(
        actions,
        key=lambda action: (
            action.changeset_id,
            ",".join(action.drift_classes),
            action.epic_id,
        ),
    )


def scan_prefix_migration_drift(
    *,
    project_data_dir: Path,
    beads_root: Path,
    repo_root: Path,
    repo_slug: str | None = None,
    git_path: str | None = None,
    lookup_pr_status: PrLookupStatus = prs.lookup_github_pr_status,
) -> list[dict[str, object]]:
    """Scan for changeset drift caused by post-migration metadata split-brain.

    Args:
        project_data_dir: Project data directory with worktree metadata.
        beads_root: Project-scoped Beads store.
        repo_root: Repository root used for Beads and git lookups.
        repo_slug: Optional GitHub ``owner/name`` for PR-head evidence.
        git_path: Optional git executable override.
        lookup_pr_status: PR lookup adapter for tests and runtime injection.

    Returns:
        Deterministically ordered drift records.
    """
    worktree_index = _collect_git_worktree_index(
        repo_root=repo_root,
        project_data_dir=project_data_dir,
        git_path=git_path,
    )
    epics = beads.list_epics(beads_root=beads_root, cwd=repo_root, include_closed=True)
    records: list[dict[str, object]] = []
    for epic in sorted(epics, key=lambda issue: str(issue.get("id") or "")):
        epic_id = _normalize_text(epic.get("id"))
        if epic_id is None:
            continue
        epic_root_branch = _normalize_text(beads.extract_workspace_root_branch(epic))
        mapping = worktrees.load_mapping(worktrees.mapping_path(project_data_dir, epic_id))
        mapping_root_branch = _normalize_text(mapping.root_branch) if mapping else None
        changesets = _changesets_for_epic(
            epic_id,
            epic_issue=epic,
            beads_root=beads_root,
            repo_root=repo_root,
        )
        for changeset in sorted(changesets, key=lambda issue: str(issue.get("id") or "")):
            changeset_id = _normalize_text(changeset.get("id"))
            if changeset_id is None:
                continue
            metadata_fields = changeset_fields.issue_fields(changeset)
            metadata_root_branch = _normalize_text(
                changeset_fields.normalized_field(metadata_fields, "changeset.root_branch")
            )
            metadata_work_branch = _normalize_text(
                changeset_fields.normalized_field(metadata_fields, "changeset.work_branch")
            )
            metadata_worktree_path = _normalize_worktree_path(
                metadata_fields.get("worktree_path"),
                project_data_dir=project_data_dir,
            )
            mapping_work_branch = (
                _normalize_text(mapping.changesets.get(changeset_id))
                if mapping is not None
                else None
            )
            mapping_worktree_path = (
                _normalize_worktree_path(
                    mapping.changeset_worktrees.get(changeset_id),
                    project_data_dir=project_data_dir,
                )
                if mapping is not None
                else None
            )
            filesystem_branch_at_mapping_path = (
                _normalize_text(worktree_index.path_to_branch.get(mapping_worktree_path))
                if mapping_worktree_path is not None
                else None
            )
            filesystem_path_for_metadata_branch = None
            if metadata_work_branch is not None:
                paths = worktree_index.branch_to_paths.get(metadata_work_branch)
                if paths:
                    filesystem_path_for_metadata_branch = paths[0]
            filesystem_path_for_mapping_branch = None
            if mapping_work_branch is not None:
                paths = worktree_index.branch_to_paths.get(mapping_work_branch)
                if paths:
                    filesystem_path_for_mapping_branch = paths[0]

            root_conflict = _distinct_values(
                epic_root_branch,
                mapping_root_branch,
                metadata_root_branch,
            )
            if len(root_conflict) > 1:
                records.append(
                    _record(
                        epic_id=epic_id,
                        changeset_id=changeset_id,
                        drift_class="root-branch-conflict",
                        values={
                            "epic.workspace.root_branch": epic_root_branch,
                            "mapping.root_branch": mapping_root_branch,
                            "metadata.changeset.root_branch": metadata_root_branch,
                        },
                    )
                )

            work_branch_conflict = _distinct_values(
                metadata_work_branch,
                mapping_work_branch,
                filesystem_branch_at_mapping_path,
            )
            pr_head_branch: str | None = None
            pr_lookup_branch: str | None = None
            if len(work_branch_conflict) > 1:
                candidate_branches = tuple(
                    sorted(
                        {
                            value
                            for value in (metadata_work_branch, mapping_work_branch)
                            if value is not None
                        }
                    )
                )
                pr_head_branch, pr_lookup_branch = _lookup_pr_head_branch(
                    repo_slug=repo_slug,
                    candidate_branches=candidate_branches,
                    lookup_pr_status=lookup_pr_status,
                )
                records.append(
                    _record(
                        epic_id=epic_id,
                        changeset_id=changeset_id,
                        drift_class="work-branch-conflict",
                        values={
                            "metadata.changeset.work_branch": metadata_work_branch,
                            "mapping.work_branch": mapping_work_branch,
                            "filesystem.worktree_branch": filesystem_branch_at_mapping_path,
                            "pr.head_ref": pr_head_branch,
                            "pr.lookup_branch": pr_lookup_branch,
                        },
                    )
                )

            path_conflict = _distinct_values(
                metadata_worktree_path,
                mapping_worktree_path,
                filesystem_path_for_metadata_branch,
                filesystem_path_for_mapping_branch,
            )
            if len(path_conflict) > 1:
                records.append(
                    _record(
                        epic_id=epic_id,
                        changeset_id=changeset_id,
                        drift_class="worktree-path-conflict",
                        values={
                            "metadata.worktree_path": metadata_worktree_path,
                            "mapping.worktree_path": mapping_worktree_path,
                            "filesystem.path_for_metadata_branch": (
                                filesystem_path_for_metadata_branch
                            ),
                            "filesystem.path_for_mapping_branch": filesystem_path_for_mapping_branch,
                        },
                    )
                )

    return sorted(
        records,
        key=lambda record: (
            str(record.get("changeset_id") or ""),
            str(record.get("drift_class") or ""),
            str(record.get("epic_id") or ""),
        ),
    )


__all__ = [
    "PrefixMigrationRepairAction",
    "repair_prefix_migration_drift",
    "scan_prefix_migration_drift",
]

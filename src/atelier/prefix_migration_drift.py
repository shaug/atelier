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


__all__ = ["scan_prefix_migration_drift"]

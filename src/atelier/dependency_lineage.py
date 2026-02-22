"""Resolve changeset parent lineage from explicit and dependency metadata."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from . import changeset_fields
from .worker.models_boundary import parse_issue_boundary

Issue = dict[str, object]
LookupIssueFn = Callable[[str], Issue | None]


def _normalize_branch(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned or cleaned.lower() == "null":
        return None
    return cleaned


def _dependency_parent_hint(issue: Issue) -> str | None:
    dependencies = issue.get("dependencies")
    if not isinstance(dependencies, list):
        return None
    for entry in dependencies:
        if not isinstance(entry, dict):
            continue
        relation = str(entry.get("relation") or "").strip().lower()
        if relation != "parent-child":
            continue
        dep_id = str(entry.get("id") or "").strip()
        if dep_id:
            return dep_id
        nested = entry.get("issue")
        if isinstance(nested, dict):
            nested_id = str(nested.get("id") or "").strip()
            if nested_id:
                return nested_id
    return None


def _dependency_id_from_entry(entry: object) -> str | None:
    if isinstance(entry, str):
        cleaned = entry.strip()
        return cleaned or None
    if not isinstance(entry, dict):
        return None
    relation = str(entry.get("relation") or "").strip().lower()
    if relation == "parent-child":
        return None
    dep_id = str(entry.get("id") or "").strip()
    if dep_id:
        return dep_id
    nested = entry.get("issue")
    if isinstance(nested, dict):
        nested_id = str(nested.get("id") or "").strip()
        if nested_id:
            return nested_id
    return None


def _dependency_ids(issue: Issue) -> tuple[str, ...]:
    dependencies = issue.get("dependencies")
    if isinstance(dependencies, list):
        resolved: list[str] = []
        seen: set[str] = set()
        for entry in dependencies:
            dependency_id = _dependency_id_from_entry(entry)
            if not dependency_id or dependency_id in seen:
                continue
            seen.add(dependency_id)
            resolved.append(dependency_id)
        if resolved:
            return tuple(resolved)
    try:
        boundary = parse_issue_boundary(issue, source="dependency_lineage:dependency_ids")
    except ValueError:
        return ()
    dependency_ids = tuple(dep for dep in boundary.dependency_ids if dep)
    if dependency_ids:
        return dependency_ids
    parent_hint = _dependency_parent_hint(issue)
    if parent_hint:
        return (parent_hint,)
    return ()


@dataclass(frozen=True)
class ParentLineageResolution:
    """Resolved parent lineage details for a changeset issue."""

    root_branch: str | None
    explicit_parent_branch: str | None
    effective_parent_branch: str | None
    dependency_ids: tuple[str, ...]
    dependency_parent_id: str | None
    dependency_parent_branch: str | None
    used_dependency_parent: bool
    blocked: bool
    blocker_reason: str | None
    diagnostics: tuple[str, ...]

    @property
    def has_dependency_lineage(self) -> bool:
        return bool(self.dependency_ids)


def resolve_parent_lineage(
    issue: Issue,
    *,
    root_branch: str | None,
    lookup_issue: LookupIssueFn | None = None,
) -> ParentLineageResolution:
    """Resolve a changeset parent branch from metadata and dependencies.

    When ``changeset.parent_branch`` is missing or collapsed to the root branch,
    this function attempts to resolve an effective parent from dependency
    changesets. Multi-dependency lineages fail closed when no deterministic
    parent can be selected.
    """
    lookup = lookup_issue or (lambda _issue_id: None)
    normalized_root = _normalize_branch(root_branch) or _normalize_branch(
        changeset_fields.root_branch(issue)
    )
    explicit_parent = _normalize_branch(changeset_fields.parent_branch(issue))
    dependency_ids = _dependency_ids(issue)
    dependency_parent_hint = _dependency_parent_hint(issue)

    diagnostics: list[str] = []
    dependency_candidates: dict[str, str] = {}
    missing_dependencies: list[str] = []
    missing_branches: list[str] = []

    for dependency_id in dependency_ids:
        dependency_issue = lookup(dependency_id)
        if dependency_issue is None:
            missing_dependencies.append(dependency_id)
            continue
        work_branch = _normalize_branch(changeset_fields.work_branch(dependency_issue))
        if work_branch is None:
            missing_branches.append(dependency_id)
            continue
        dependency_candidates[dependency_id] = work_branch

    dependency_parent_id: str | None = None
    dependency_parent_branch: str | None = None
    if dependency_parent_hint and dependency_parent_hint in dependency_candidates:
        dependency_parent_id = dependency_parent_hint
        dependency_parent_branch = dependency_candidates[dependency_parent_hint]
    elif len(dependency_candidates) == 1:
        dependency_parent_id, dependency_parent_branch = next(iter(dependency_candidates.items()))
    elif len(dependency_candidates) > 1:
        dependency_pairs = ", ".join(
            f"{issue_id}->{branch}" for issue_id, branch in sorted(dependency_candidates.items())
        )
        diagnostics.append(f"ambiguous dependency parent branches: {dependency_pairs}")

    if missing_dependencies:
        diagnostics.append(
            "dependency issues unavailable: " + ", ".join(sorted(missing_dependencies))
        )
    if missing_branches:
        diagnostics.append(
            "dependency work branches missing: " + ", ".join(sorted(missing_branches))
        )

    needs_dependency_parent = bool(dependency_ids) and (
        explicit_parent is None
        or (normalized_root is not None and explicit_parent == normalized_root)
    )

    blocked = False
    blocker_reason: str | None = None
    used_dependency_parent = False
    effective_parent = explicit_parent
    if needs_dependency_parent:
        if dependency_parent_branch:
            effective_parent = dependency_parent_branch
            used_dependency_parent = True
        else:
            blocked = True
            if len(dependency_candidates) > 1:
                blocker_reason = "dependency-lineage-ambiguous"
            else:
                blocker_reason = "dependency-parent-unresolved"
            effective_parent = None

    if effective_parent is None:
        effective_parent = normalized_root

    if (
        used_dependency_parent
        and explicit_parent is not None
        and explicit_parent != dependency_parent_branch
    ):
        diagnostics.append(
            f"updated collapsed parent lineage {explicit_parent!r} -> {dependency_parent_branch!r}"
        )

    return ParentLineageResolution(
        root_branch=normalized_root,
        explicit_parent_branch=explicit_parent,
        effective_parent_branch=effective_parent,
        dependency_ids=dependency_ids,
        dependency_parent_id=dependency_parent_id,
        dependency_parent_branch=dependency_parent_branch,
        used_dependency_parent=used_dependency_parent,
        blocked=blocked,
        blocker_reason=blocker_reason,
        diagnostics=tuple(diagnostics),
    )

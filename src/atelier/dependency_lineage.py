"""Resolve changeset parent lineage from explicit and dependency metadata."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from . import changeset_fields
from .worker.models_boundary import parse_issue_boundary

Issue = dict[str, object]
LookupIssueFn = Callable[[str], Issue | None]
_PARENT_CHILD_KEY = "dependency_type"
_PARENT_CHILD_PATTERN = re.compile(r"parent[\s_-]*child", re.IGNORECASE)


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
        if not _is_parent_child_relation(entry):
            continue
        if not isinstance(entry, dict):
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


def _is_parent_child_relation(value: object) -> bool:
    if isinstance(value, dict):
        relation = value.get(_PARENT_CHILD_KEY)
        return isinstance(relation, str) and bool(_PARENT_CHILD_PATTERN.search(relation.strip()))
    return isinstance(value, str) and bool(_PARENT_CHILD_PATTERN.search(value))


def _dependency_id_from_entry(entry: object) -> str | None:
    if _is_parent_child_relation(entry):
        return None
    if isinstance(entry, str):
        cleaned = entry.strip()
        return cleaned or None
    if not isinstance(entry, dict):
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


def _dependency_transitive_closure(
    issue_id: str,
    *,
    lookup_issue: LookupIssueFn,
    closure_cache: dict[str, frozenset[str]],
    visiting: set[str],
) -> frozenset[str]:
    cached = closure_cache.get(issue_id)
    if cached is not None:
        return cached
    if issue_id in visiting:
        return frozenset()

    visiting.add(issue_id)
    try:
        dependency_issue = lookup_issue(issue_id)
        if dependency_issue is None:
            closure = frozenset()
        else:
            direct_dependency_ids = _dependency_ids(dependency_issue)
            expanded: set[str] = set(direct_dependency_ids)
            for direct_dependency_id in direct_dependency_ids:
                expanded.update(
                    _dependency_transitive_closure(
                        direct_dependency_id,
                        lookup_issue=lookup_issue,
                        closure_cache=closure_cache,
                        visiting=visiting,
                    )
                )
            closure = frozenset(expanded)
    finally:
        visiting.remove(issue_id)

    closure_cache[issue_id] = closure
    return closure


def _transitive_dependency_frontier(
    candidate_ids: tuple[str, ...],
    *,
    lookup_issue: LookupIssueFn,
) -> tuple[str, ...]:
    closure_cache: dict[str, frozenset[str]] = {}
    covered_ids: set[str] = set()
    candidate_set = set(candidate_ids)

    for candidate_id in candidate_ids:
        closure = _dependency_transitive_closure(
            candidate_id,
            lookup_issue=lookup_issue,
            closure_cache=closure_cache,
            visiting=set(),
        )
        covered_ids.update(
            dependency_id
            for dependency_id in closure
            if dependency_id in candidate_set and dependency_id != candidate_id
        )

    return tuple(candidate_id for candidate_id in candidate_ids if candidate_id not in covered_ids)


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
    issue_cache: dict[str, Issue | None] = {}

    def lookup_cached_issue(issue_id: str) -> Issue | None:
        if issue_id not in issue_cache:
            issue_cache[issue_id] = lookup(issue_id)
        return issue_cache[issue_id]

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
        dependency_issue = lookup_cached_issue(dependency_id)
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
        candidate_ids = tuple(dependency_candidates)
        frontier_ids = _transitive_dependency_frontier(
            candidate_ids, lookup_issue=lookup_cached_issue
        )
        if len(frontier_ids) == 1:
            dependency_parent_id = frontier_ids[0]
            dependency_parent_branch = dependency_candidates[dependency_parent_id]
        else:
            unresolved_ids = sorted(frontier_ids) if frontier_ids else sorted(dependency_candidates)
            dependency_pairs = ", ".join(
                f"{issue_id}->{dependency_candidates[issue_id]}" for issue_id in unresolved_ids
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

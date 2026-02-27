"""Planner startup overview helpers."""

from __future__ import annotations

import re
from pathlib import Path

from . import beads, lifecycle


def list_epics(*, beads_root: Path, repo_root: Path) -> list[dict[str, object]]:
    """List epic beads for planner overview rendering.

    Args:
        beads_root: Root directory for the Beads planning store.
        repo_root: Repository root used as the working directory for `bd`.

    Returns:
        Epic issue payloads from Beads. Non-dict entries are discarded.
    """
    return beads.list_epics(beads_root=beads_root, cwd=repo_root, include_closed=False)


def render_epics(issues: list[dict[str, object]], *, show_drafts: bool) -> str:
    """Render epics in stable `epic_list --show-drafts` format.

    Args:
        issues: Beads epic issue payloads.
        show_drafts: Include deferred epics when true.

    Returns:
        Deterministic plain-text listing grouped by epic state buckets.
    """
    buckets: dict[str, list[dict[str, object]]] = {
        "draft": [],
        "open": [],
        "in_progress": [],
        "blocked": [],
        "other": [],
    }
    for issue in issues:
        bucket = _status_bucket(issue, show_drafts=show_drafts)
        if bucket is None:
            continue
        buckets[bucket].append(issue)

    lines: list[str] = ["Epics by state:"]
    sections = [
        ("Draft epics:", buckets["draft"]),
        ("Open epics:", buckets["open"]),
        ("In-progress epics:", buckets["in_progress"]),
        ("Blocked epics:", buckets["blocked"]),
        ("Other active epics:", buckets["other"]),
    ]

    rendered_any = False
    for heading, entries in sections:
        if not entries:
            continue
        rendered_any = True
        lines.append("")
        lines.append(heading)
        for issue in sorted(entries, key=_sort_key):
            _append_issue(lines, issue)

    if not rendered_any:
        lines.append("- (none)")
    return "\n".join(lines)


def _labels(issue: dict[str, object]) -> set[str]:
    labels = issue.get("labels")
    if not isinstance(labels, list):
        return set()
    return {str(label) for label in labels if label is not None}


def _parse_description_fields(description: str | None) -> dict[str, str]:
    if not description:
        return {}
    fields: dict[str, str] = {}
    for line in description.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        if not key:
            continue
        fields[key] = value.strip()
    return fields


def _normalize_status(value: object) -> str:
    return str(value or "").strip().lower()


def _dependency_id_status(dep: object) -> tuple[str | None, str | None]:
    if isinstance(dep, dict):
        dep_id = str(dep.get("id") or "").strip() or None
        status = _normalize_status(dep.get("status")) or None
        return dep_id, status
    if isinstance(dep, str):
        text = dep.strip()
        if not text:
            return None, None
        match = re.match(r"^(?P<id>[^\s(]+)(?:\s*\((?P<meta>[^)]*)\))?$", text)
        if not match:
            return text, None
        dep_id = (match.group("id") or "").strip() or None
        meta = (match.group("meta") or "").strip()
        if not meta:
            return dep_id, None
        status = _normalize_status(meta.split(",", 1)[0])
        return dep_id, status or None
    return None, None


def _blocking_dependencies(issue: dict[str, object]) -> list[str]:
    deps = issue.get("dependencies")
    if not isinstance(deps, list):
        return []
    blockers: list[str] = []
    for dep in deps:
        dep_id, status = _dependency_id_status(dep)
        if not dep_id:
            continue
        canonical_status = lifecycle.canonical_lifecycle_status(status)
        if canonical_status == "closed":
            continue
        blockers.append(f"{dep_id} [{canonical_status or status or 'unknown'}]")
    return blockers


def _status_bucket(issue: dict[str, object], *, show_drafts: bool) -> str | None:
    labels = _labels(issue)
    role = lifecycle.infer_work_role(
        labels=labels,
        issue_type=lifecycle.issue_payload_type(issue),
        parent_id=issue.get("parent"),
        has_work_children=False,
    )
    if not role.is_epic:
        return None
    status = lifecycle.canonical_lifecycle_status(issue.get("status"))
    if status == "closed":
        return None
    if status == "deferred":
        return "draft" if show_drafts else None
    if status in {"open", "in_progress"} and _blocking_dependencies(issue):
        return "blocked"
    if status == "blocked":
        return "blocked"
    if status == "in_progress":
        return "in_progress"
    if status == "open":
        return "open"
    if status is None:
        return "draft" if show_drafts else None
    return "other"


def _sort_key(issue: dict[str, object]) -> tuple[str, str]:
    issue_id = str(issue.get("id") or "").strip()
    title = str(issue.get("title") or "").strip()
    return (issue_id, title)


def _append_issue(lines: list[str], issue: dict[str, object]) -> None:
    issue_id = str(issue.get("id") or "").strip() or "(unknown)"
    labels = _labels(issue)
    canonical_status = lifecycle.canonical_lifecycle_status(issue.get("status"))
    raw_status = str(issue.get("status") or "unknown").strip() or "unknown"
    status = canonical_status or raw_status
    title = str(issue.get("title") or "").strip() or "(untitled)"
    description = issue.get("description")
    fields = _parse_description_fields(description if isinstance(description, str) else None)
    root_branch = fields.get("workspace.root_branch") or "unset"
    assignee = str(issue.get("assignee") or "").strip() or "unassigned"
    blockers = _blocking_dependencies(issue)
    lines.append(f"- {issue_id} [{status}] {title}")
    lines.append(f"  root: {root_branch} | assignee: {assignee}")
    if blockers:
        lines.append(f"  blockers: {', '.join(blockers)}")

#!/usr/bin/env python3
"""Render epics in a stable, glanceable format for planner/overseer use."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path


def _run_bd_list(beads_dir: str | None) -> list[dict[str, object]]:
    cmd = ["bd", "list", "--label", "at:epic", "--json"]
    env = dict(os.environ)
    if beads_dir:
        env["BEADS_DIR"] = beads_dir
    try:
        result = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
    except FileNotFoundError:
        print("error: missing required command: bd", file=sys.stderr)
        raise SystemExit(1)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        print(f"error: failed to list epics: {detail}", file=sys.stderr)
        raise SystemExit(1)
    raw = (result.stdout or "").strip()
    if not raw:
        return []
    payload = json.loads(raw)
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


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
        if status in {"closed", "done"}:
            continue
        blockers.append(f"{dep_id} [{status or 'unknown'}]")
    return blockers


def _status_bucket(issue: dict[str, object], *, show_drafts: bool) -> str | None:
    labels = _labels(issue)
    if "at:draft" in labels:
        return "draft" if show_drafts else None
    status = _normalize_status(issue.get("status"))
    if status in {"closed", "done"}:
        return None
    if _blocking_dependencies(issue):
        return "blocked"
    if status in {"blocked"}:
        return "blocked"
    if status in {"in_progress", "hooked"}:
        return "in_progress"
    if status in {"", "open", "ready"}:
        return "open"
    return "other"


def _sort_key(issue: dict[str, object]) -> tuple[str, str]:
    issue_id = str(issue.get("id") or "").strip()
    title = str(issue.get("title") or "").strip()
    return (issue_id, title)


def _append_issue(lines: list[str], issue: dict[str, object]) -> None:
    issue_id = str(issue.get("id") or "").strip() or "(unknown)"
    status = str(issue.get("status") or "unknown").strip() or "unknown"
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


def _render_epics(issues: list[dict[str, object]], *, show_drafts: bool) -> str:
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--show-drafts",
        action="store_true",
        help="include draft epics alongside active non-closed epics",
    )
    parser.add_argument(
        "--beads-dir",
        default=os.environ.get("BEADS_DIR", ""),
        help="beads root path (defaults to BEADS_DIR env var)",
    )
    args = parser.parse_args()

    beads_dir = str(args.beads_dir).strip() or None
    if beads_dir and not Path(beads_dir).exists():
        print(f"error: beads dir not found: {beads_dir}", file=sys.stderr)
        raise SystemExit(1)
    issues = _run_bd_list(beads_dir)
    print(_render_epics(issues, show_drafts=bool(args.show_drafts)))


if __name__ == "__main__":
    main()

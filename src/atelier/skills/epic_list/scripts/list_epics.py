#!/usr/bin/env python3
"""Render epics in a stable, glanceable format for planner/overseer use."""

from __future__ import annotations

import argparse
import json
import os
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


def _render_epics(issues: list[dict[str, object]], *, show_drafts: bool) -> str:
    filtered: list[dict[str, object]] = []
    for issue in issues:
        labels = _labels(issue)
        if not show_drafts and "at:draft" in labels:
            continue
        filtered.append(issue)

    heading = "Draft epics:" if show_drafts else "Epics:"
    if not filtered:
        return f"{heading}\n- (none)"

    lines: list[str] = [heading]
    for issue in filtered:
        issue_id = str(issue.get("id") or "").strip() or "(unknown)"
        status = str(issue.get("status") or "unknown").strip() or "unknown"
        title = str(issue.get("title") or "").strip() or "(untitled)"
        description = issue.get("description")
        fields = _parse_description_fields(
            description if isinstance(description, str) else None
        )
        root_branch = fields.get("workspace.root_branch") or "unset"
        assignee = str(issue.get("assignee") or "").strip() or "unassigned"
        lines.append(f"- {issue_id} [{status}] {title}")
        lines.append(f"  root: {root_branch} | assignee: {assignee}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--show-drafts",
        action="store_true",
        help="include draft epics",
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

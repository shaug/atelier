#!/usr/bin/env python3
"""Render epics in a stable, glanceable format for planner/overseer use."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from atelier import planner_overview

# Re-exported for tests that load this script directly.
_status_bucket = planner_overview._status_bucket  # pyright: ignore[reportPrivateUsage]
_render_epics = planner_overview.render_epics


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

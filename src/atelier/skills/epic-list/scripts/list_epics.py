#!/usr/bin/env python3
"""Render epics in a stable, glanceable format for planner/overseer use."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from atelier import config, planner_overview
from atelier.commands.resolve import resolve_current_project_with_repo_root

# Re-exported for tests that load this script directly.
_status_bucket = planner_overview._status_bucket  # pyright: ignore[reportPrivateUsage]
_render_epics = planner_overview.render_epics


def _resolve_context(*, beads_dir: str | None) -> tuple[Path, Path]:
    repo_env = os.environ.get("ATELIER_PROJECT", "").strip()
    repo_root = Path(repo_env).resolve() if repo_env else Path.cwd()
    beads_env = str(beads_dir or "").strip() or os.environ.get("BEADS_DIR", "").strip()
    if beads_env:
        return Path(beads_env).expanduser().resolve(), repo_root
    project_root, project_config, _enlistment, repo_root = resolve_current_project_with_repo_root()
    project_data_dir = config.resolve_project_data_dir(project_root, project_config)
    return config.resolve_beads_root(project_data_dir, repo_root), repo_root


def _run_bd_list(beads_dir: str | None) -> list[dict[str, object]]:
    beads_root, repo_root = _resolve_context(beads_dir=beads_dir)
    return planner_overview.list_epics(beads_root=beads_root, repo_root=repo_root)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--show-drafts",
        action="store_true",
        help="include deferred epics alongside active non-closed epics",
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

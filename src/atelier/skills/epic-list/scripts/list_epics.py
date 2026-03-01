#!/usr/bin/env python3
"""Render epics in a stable, glanceable format for planner/overseer use."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from atelier import planner_overview
from atelier.beads_context import resolve_skill_beads_context

# Re-exported for tests that load this script directly.
_status_bucket = planner_overview._status_bucket  # pyright: ignore[reportPrivateUsage]
_render_epics = planner_overview.render_epics


def _resolve_context(*, beads_dir: str | None) -> tuple[Path, Path, str | None]:
    context = resolve_skill_beads_context(
        beads_dir=beads_dir,
        repo_dir=os.environ.get("ATELIER_PROJECT", "").strip() or None,
    )
    return context.beads_root, context.repo_root, context.override_warning


def _run_bd_list(beads_dir: str | None) -> list[dict[str, object]]:
    beads_root, repo_root, _override_warning = _resolve_context(beads_dir=beads_dir)
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
        default="",
        help="explicit beads root override (defaults to project-scoped store)",
    )
    args = parser.parse_args()

    beads_dir = str(args.beads_dir).strip() or None
    beads_root, repo_root, override_warning = _resolve_context(beads_dir=beads_dir)
    if override_warning:
        print(override_warning, file=sys.stderr)
    if not beads_root.exists():
        print(f"error: beads dir not found: {beads_root}", file=sys.stderr)
        raise SystemExit(1)
    issues = planner_overview.list_epics(beads_root=beads_root, repo_root=repo_root)
    print(_render_epics(issues, show_drafts=bool(args.show_drafts)))


if __name__ == "__main__":
    main()

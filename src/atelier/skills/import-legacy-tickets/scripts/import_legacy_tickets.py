#!/usr/bin/env python3
"""Run startup legacy-ticket migration/import and print explicit diagnostics."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from atelier import beads, config
from atelier.commands.resolve import resolve_current_project_with_repo_root

_MISSING_DOLT = "missing_dolt_with_legacy_sqlite"
_INSUFFICIENT_DOLT = "insufficient_dolt_vs_legacy_data"
_HEALTHY_DOLT = "healthy_dolt"


def _resolve_context(*, beads_dir: str | None) -> tuple[Path, Path]:
    repo_env = os.environ.get("ATELIER_PROJECT", "").strip()
    beads_env = str(beads_dir or "").strip() or os.environ.get("BEADS_DIR", "").strip()
    repo_root = Path(repo_env).resolve() if repo_env else Path.cwd()
    if beads_env:
        return Path(beads_env).expanduser().resolve(), repo_root
    project_root, project_config, _enlistment, repo_root = resolve_current_project_with_repo_root()
    project_data_dir = config.resolve_project_data_dir(project_root, project_config)
    return config.resolve_beads_root(project_data_dir, repo_root), repo_root


def _status_reason(state: beads.StartupBeadsState) -> str:
    if not state.has_legacy_sqlite:
        return "no recoverable legacy SQLite startup state detected"
    if state.classification == _MISSING_DOLT:
        return "legacy SQLite data exists but Dolt backend is missing"
    if state.classification == _INSUFFICIENT_DOLT:
        dolt_total = state.dolt_issue_total if state.dolt_issue_total is not None else "unavailable"
        legacy_total = (
            state.legacy_issue_total if state.legacy_issue_total is not None else "unavailable"
        )
        return f"active Dolt issue count ({dolt_total}) is below legacy SQLite issue count ({legacy_total})"
    if state.classification == _HEALTHY_DOLT:
        return "active Dolt issue count already covers legacy SQLite issue count"
    return "no recoverable legacy SQLite startup state detected"


def _migration_verified(
    *,
    before: beads.StartupBeadsState,
    after: beads.StartupBeadsState,
) -> bool:
    if after.classification != _HEALTHY_DOLT or after.migration_eligible:
        return False
    if after.dolt_issue_total is None:
        return False
    if before.legacy_issue_total is None:
        return True
    return after.dolt_issue_total >= before.legacy_issue_total


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--beads-dir",
        default="",
        help="beads root path (defaults to BEADS_DIR env var or project config)",
    )
    args = parser.parse_args()

    beads_root, repo_root = _resolve_context(beads_dir=args.beads_dir)
    if not beads_root.exists():
        print(f"error: beads dir not found: {beads_root}", file=sys.stderr)
        raise SystemExit(1)

    before = beads.detect_startup_beads_state(beads_root=beads_root, cwd=repo_root)
    beads.run_bd_command(["prime"], beads_root=beads_root, cwd=repo_root)
    after = beads.detect_startup_beads_state(beads_root=beads_root, cwd=repo_root)

    if before.migration_eligible and _migration_verified(before=before, after=after):
        status = "migrated"
        reason = _status_reason(before)
    elif before.migration_eligible:
        status = "blocked"
        reason = "legacy migration remained unresolved after startup prime"
    else:
        status = "skipped"
        reason = _status_reason(before)

    print(f"Beads startup auto-upgrade {status}: {reason}")
    print("before=" + beads.format_startup_beads_diagnostics(before))
    print("after=" + beads.format_startup_beads_diagnostics(after))


if __name__ == "__main__":
    main()

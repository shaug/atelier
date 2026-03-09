#!/usr/bin/env python3
"""Retry or manually run ticket export for an existing bead."""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

_SHARED_SCRIPTS_ROOT = Path(__file__).resolve().parents[2] / "shared" / "scripts"
if str(_SHARED_SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_SHARED_SCRIPTS_ROOT))

from projected_bootstrap import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    bootstrap_projected_atelier_script,
)

_BOOTSTRAP_REPO_ROOT = bootstrap_projected_atelier_script(
    script_path=Path(__file__).resolve(),
    argv=sys.argv[1:],
    require_runtime_health=__name__ == "__main__",
)

from atelier import auto_export  # noqa: E402
from atelier.beads_context import resolve_runtime_repo_dir_hint  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issue-id", required=True, help="Bead id to export")
    parser.add_argument("--provider", default="", help="Optional provider override")
    parser.add_argument(
        "--beads-dir",
        default="",
        help="Beads directory override (defaults to project config)",
    )
    parser.add_argument(
        "--repo-dir",
        default="",
        help="Repo root override (defaults to ./worktree, then cwd)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Bypass project auto-export toggle",
    )
    args = parser.parse_args()

    repo_hint_raw, runtime_warning = resolve_runtime_repo_dir_hint(
        repo_dir=str(args.repo_dir).strip() or None
    )
    if runtime_warning:
        print(runtime_warning, file=sys.stderr)
    context = auto_export.resolve_auto_export_context(
        repo_hint=Path(repo_hint_raw) if repo_hint_raw else None
    )
    beads_dir = str(args.beads_dir).strip()
    if beads_dir:
        context = replace(context, beads_root=Path(beads_dir))

    result = auto_export.auto_export_issue(
        args.issue_id,
        context=context,
        provider_slug=str(args.provider).strip() or None,
        force=bool(args.force),
    )
    print(f"{result.status}: {result.message}")
    if result.retry_command:
        print(f"retry: {result.retry_command}", file=sys.stderr)
    if result.status == "failed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()

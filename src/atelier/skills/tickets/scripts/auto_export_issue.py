#!/usr/bin/env python3
"""Retry or manually run ticket export for an existing bead."""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path


def _bootstrap_source_import() -> None:
    src_dir = Path(__file__).resolve().parents[4]
    if src_dir.is_dir() and str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))


_bootstrap_source_import()

from atelier import auto_export  # noqa: E402


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
        "--force",
        action="store_true",
        help="Bypass project auto-export toggle",
    )
    args = parser.parse_args()

    context = auto_export.resolve_auto_export_context()
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

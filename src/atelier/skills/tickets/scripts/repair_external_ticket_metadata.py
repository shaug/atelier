#!/usr/bin/env python3
"""Repair missing external_tickets metadata from Beads event history."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def _bootstrap_source_import() -> None:
    src_dir = Path(__file__).resolve().parents[4]
    if src_dir.is_dir() and str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))


_bootstrap_source_import()

from atelier import beads  # noqa: E402


def _render_result(result: beads.ExternalTicketMetadataRepairResult) -> str:
    providers = ",".join(result.providers) if result.providers else "unknown"
    if result.repaired:
        return (
            f"{result.issue_id}: repaired ({result.ticket_count} ticket(s), providers={providers})"
        )
    if result.recovered:
        return (
            f"{result.issue_id}: recoverable ({result.ticket_count} ticket(s), "
            f"providers={providers})"
        )
    return f"{result.issue_id}: unrecoverable (providers={providers})"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--issue-id",
        action="append",
        default=[],
        help="Specific issue id to inspect (repeatable). Defaults to all issues.",
    )
    parser.add_argument(
        "--beads-dir",
        default="",
        help="Beads directory override (defaults to current project context).",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply repairs in-place. Without this flag the script only reports.",
    )
    args = parser.parse_args()

    beads_root_arg = str(args.beads_dir).strip()
    if beads_root_arg:
        beads_root = Path(beads_root_arg).resolve()
    else:
        beads_root = (
            Path(os.environ.get("BEADS_DIR", "")).resolve()
            if os.environ.get("BEADS_DIR")
            else Path.cwd() / ".beads"
        )
    results = beads.repair_external_ticket_metadata_from_history(
        beads_root=beads_root,
        cwd=Path.cwd(),
        issue_ids=[issue_id for issue_id in args.issue_id if issue_id.strip()] or None,
        apply=bool(args.apply),
    )

    if not results:
        print("No ext:* metadata gaps found.")
        return

    repaired = sum(1 for result in results if result.repaired)
    recoverable = sum(1 for result in results if result.recovered and not result.repaired)
    unrecoverable = sum(1 for result in results if not result.recovered)
    mode = "applied" if args.apply else "dry-run"
    print(
        f"external_tickets repair ({mode}): "
        f"total={len(results)} repaired={repaired} "
        f"recoverable={recoverable} unrecoverable={unrecoverable}"
    )
    for result in results:
        print(f"- {_render_result(result)}")


if __name__ == "__main__":
    main()

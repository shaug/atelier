#!/usr/bin/env python3
"""Close an epic and clear the current worker hook."""

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


def close_epic(
    *,
    epic_id: str,
    agent_bead_id: str,
    beads_root: Path,
    cwd: Path,
    direct_close: bool,
) -> bool:
    """Close an epic and clear the worker hook.

    Args:
        epic_id: Epic bead id to close.
        agent_bead_id: Agent bead id that currently owns the hook.
        beads_root: Beads data directory.
        cwd: Working directory for `bd` commands.
        direct_close: When true, skip completion checks and close immediately.

    Returns:
        `True` when the epic was closed during this call.
    """
    if direct_close:
        beads.close_issue(epic_id, beads_root=beads_root, cwd=cwd)
        beads.clear_agent_hook(
            agent_bead_id,
            beads_root=beads_root,
            cwd=cwd,
            expected_hook=epic_id,
        )
        return True
    return beads.close_epic_if_complete(
        epic_id,
        agent_bead_id,
        beads_root=beads_root,
        cwd=cwd,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--epic-id", required=True, help="Epic bead id")
    parser.add_argument("--agent-bead-id", required=True, help="Agent bead id")
    parser.add_argument(
        "--direct-close",
        action="store_true",
        help="Close immediately without checking descendant changeset completion",
    )
    parser.add_argument(
        "--beads-dir",
        default="",
        help="Beads directory override (defaults to BEADS_DIR or repo .beads)",
    )
    args = parser.parse_args()

    beads_dir = str(args.beads_dir).strip() or None
    if beads_dir:
        beads_root = Path(beads_dir).expanduser().resolve()
    else:
        beads_root = Path(os.environ.get("BEADS_DIR", str(Path.cwd() / ".beads"))).expanduser()
        beads_root = beads_root.resolve()
    if not beads_root.exists():
        print(f"error: beads dir not found: {beads_root}", file=sys.stderr)
        raise SystemExit(1)

    closed = close_epic(
        epic_id=args.epic_id.strip(),
        agent_bead_id=args.agent_bead_id.strip(),
        beads_root=beads_root,
        cwd=Path.cwd(),
        direct_close=bool(args.direct_close),
    )
    if not closed:
        print(
            (
                "error: epic is not ready to close; ensure descendant changesets "
                "are terminal or rerun with --direct-close"
            ),
            file=sys.stderr,
        )
        raise SystemExit(1)
    print(f"closed_epic: {args.epic_id.strip()}")
    print(f"cleared_hook: {args.agent_bead_id.strip()}")


if __name__ == "__main__":
    main()

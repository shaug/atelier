#!/usr/bin/env python3
"""Close an epic and clear the current worker hook."""

from __future__ import annotations

import argparse
import importlib
import os
import sys
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
    runtime = _load_epic_close_runtime_for_execution()
    if direct_close:
        runtime.direct_close_epic(
            epic_id,
            agent_bead_id,
            beads_root=beads_root,
            repo_root=cwd,
        )
        return True
    return runtime.close_epic_if_complete(
        epic_id,
        agent_bead_id,
        beads_root=beads_root,
        repo_root=cwd,
    )


def _ensure_selected_beads_runtime() -> None:
    """Import the selected Beads runtime after projected bootstrap.

    Projected skill `--help` exits before the close path imports
    `atelier.worker.epic_close`, but the bootstrap tests still need one explicit
    import probe that shows which `atelier.*` runtime won after `sys.path`
    reordering. Keeping that probe here makes the bootstrap workaround named and
    localized instead of a hidden module-import side effect.
    """
    importlib.import_module("atelier.beads")


def _load_epic_close_runtime_for_execution():
    """Load the worker close runtime only for actual close execution.

    The projected script's `--help` path intentionally stops after bootstrap
    and argument parsing. Importing `atelier.worker.epic_close` eagerly would
    force that heavier runtime onto help-only invocations and break the split
    runtime bootstrap contract that the projected tests exercise.
    """
    from atelier.worker import epic_close

    return epic_close


def main() -> None:
    _ensure_selected_beads_runtime()
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

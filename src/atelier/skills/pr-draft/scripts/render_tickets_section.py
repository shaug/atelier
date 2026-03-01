#!/usr/bin/env python3
"""Render a PR ``Tickets`` section from a changeset bead."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from atelier.bd_invocation import with_bd_mode
from atelier.worker import publish as worker_publish


def render_ticket_section(issue: dict[str, object]) -> str:
    """Render markdown for the PR ``Tickets`` section."""
    lines = worker_publish.render_pr_ticket_lines(issue)
    if not lines:
        lines = ["- None"]
    return "\n".join(["## Tickets", *lines])


def load_issue(changeset_id: str, *, beads_dir: Path, repo_path: Path) -> dict[str, object]:
    """Load a changeset issue payload from Beads."""
    env = os.environ.copy()
    env["BEADS_DIR"] = str(beads_dir)
    command = with_bd_mode("show", changeset_id, "--json", beads_dir=str(beads_dir), env=env)
    result = subprocess.run(
        command,
        cwd=repo_path,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "bd show failed"
        raise RuntimeError(message)
    try:
        payload = json.loads(result.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"failed to parse bd show output: {exc}") from exc
    if not isinstance(payload, list) or not payload:
        raise RuntimeError(f"changeset not found: {changeset_id}")
    issue = payload[0]
    if not isinstance(issue, dict):
        raise RuntimeError(f"unexpected issue payload for {changeset_id}")
    return issue


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--changeset-id", required=True, help="Changeset bead id")
    parser.add_argument(
        "--beads-dir",
        default=os.environ.get("BEADS_DIR", "beads"),
        help="Beads data directory (default: BEADS_DIR or ./beads)",
    )
    parser.add_argument(
        "--repo-path",
        default=".",
        help="Repository path for running bd commands (default: .)",
    )
    return parser.parse_args()


def main() -> int:
    """Entrypoint."""
    args = parse_args()
    try:
        issue = load_issue(
            args.changeset_id,
            beads_dir=Path(args.beads_dir).expanduser(),
            repo_path=Path(args.repo_path).expanduser(),
        )
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    section = render_ticket_section(issue)
    if section:
        print(section)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

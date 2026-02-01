"""Beads CLI helpers for Atelier."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from . import exec
from .io import die


def beads_env(beads_root: Path) -> dict[str, str]:
    """Return an environment mapping with BEADS_DIR set."""
    env = os.environ.copy()
    env["BEADS_DIR"] = str(beads_root)
    return env


def run_bd_command(
    args: list[str],
    *,
    beads_root: Path,
    cwd: Path,
    allow_failure: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run a bd command and return the CompletedProcess.

    Raises a user-facing error when bd is missing or returns a non-zero status
    unless allow_failure is True.
    """
    cmd = ["bd", *args]
    result = exec.try_run_command(cmd, cwd=cwd, env=beads_env(beads_root))
    if result is None:
        die("missing required command: bd")
    if result.returncode != 0 and not allow_failure:
        die(f"command failed: {' '.join(cmd)}")
    return result


def run_bd_json(
    args: list[str], *, beads_root: Path, cwd: Path
) -> list[dict[str, object]]:
    """Run a bd command with --json and return parsed output."""
    cmd = list(args)
    if "--json" not in cmd:
        cmd.append("--json")
    result = run_bd_command(cmd, beads_root=beads_root, cwd=cwd)
    raw = result.stdout.strip() if result.stdout else ""
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        die(f"failed to parse bd json output: {exc}")
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        return [payload]
    return []

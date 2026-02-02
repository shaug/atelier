"""Beads CLI helpers for Atelier."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from tempfile import NamedTemporaryFile

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


def _normalize_description(description: str | None) -> str:
    if not description:
        return ""
    return description.rstrip("\n")


def _update_description_field(
    description: str | None, *, key: str, value: str | None
) -> str:
    target = _normalize_description(description)
    lines = target.splitlines() if target else []
    updated: list[str] = []
    needle = f"{key}:"
    found = False
    for line in lines:
        if line.strip().startswith(needle):
            if not found:
                replacement = value if value is not None else "null"
                updated.append(f"{key}: {replacement}")
                found = True
            continue
        updated.append(line)
    if not found:
        replacement = value if value is not None else "null"
        updated.append(f"{key}: {replacement}")
    return "\n".join(updated).rstrip("\n") + "\n"


def _update_issue_description(
    issue_id: str,
    description: str,
    *,
    beads_root: Path,
    cwd: Path,
) -> None:
    with NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
        handle.write(description)
        temp_path = Path(handle.name)
    try:
        run_bd_command(
            ["update", issue_id, "--body-file", str(temp_path)],
            beads_root=beads_root,
            cwd=cwd,
        )
    finally:
        temp_path.unlink(missing_ok=True)


def find_agent_bead(
    agent_id: str, *, beads_root: Path, cwd: Path
) -> dict[str, object] | None:
    """Find an agent bead by agent identity."""
    issues = run_bd_json(
        ["list", "--label", "at:agent", "--title-contains", agent_id],
        beads_root=beads_root,
        cwd=cwd,
    )
    return issues[0] if issues else None


def ensure_agent_bead(
    agent_id: str,
    *,
    beads_root: Path,
    cwd: Path,
    role: str | None = None,
) -> dict[str, object]:
    """Ensure an agent bead exists for the given identity."""
    existing = find_agent_bead(agent_id, beads_root=beads_root, cwd=cwd)
    if existing:
        return existing
    description = f"agent_id: {agent_id}\n"
    if role:
        description += f"role: {role}\n"
    result = run_bd_command(
        [
            "create",
            "--type",
            "agent",
            "--label",
            "at:agent",
            "--title",
            agent_id,
            "--description",
            description,
            "--silent",
        ],
        beads_root=beads_root,
        cwd=cwd,
    )
    issue_id = result.stdout.strip() if result.stdout else ""
    if not issue_id:
        die("failed to create agent bead")
    issues = run_bd_json(["show", issue_id], beads_root=beads_root, cwd=cwd)
    if issues:
        return issues[0]
    return {"id": issue_id, "title": agent_id}


def claim_epic(
    epic_id: str,
    agent_id: str,
    *,
    beads_root: Path,
    cwd: Path,
) -> dict[str, object]:
    """Claim an epic by assigning it to the agent."""
    issues = run_bd_json(["show", epic_id], beads_root=beads_root, cwd=cwd)
    if not issues:
        die(f"epic not found: {epic_id}")
    issue = issues[0]
    labels = issue.get("labels") if isinstance(issue.get("labels"), list) else []
    if "at:draft" in labels:
        die(f"epic {epic_id} is marked as draft")
    if issue.get("assignee"):
        die(f"epic {epic_id} already has an assignee")
    run_bd_command(
        [
            "update",
            epic_id,
            "--assignee",
            agent_id,
            "--status",
            "in_progress",
            "--add-label",
            "at:hooked",
        ],
        beads_root=beads_root,
        cwd=cwd,
    )
    refreshed = run_bd_json(["show", epic_id], beads_root=beads_root, cwd=cwd)
    return refreshed[0] if refreshed else issue


def set_agent_hook(
    agent_bead_id: str,
    epic_id: str,
    *,
    beads_root: Path,
    cwd: Path,
) -> None:
    """Store the hooked epic id on the agent bead description."""
    issues = run_bd_json(["show", agent_bead_id], beads_root=beads_root, cwd=cwd)
    if not issues:
        die(f"agent bead not found: {agent_bead_id}")
    issue = issues[0]
    description = issue.get("description")
    updated = _update_description_field(
        description if isinstance(description, str) else "",
        key="hook_bead",
        value=epic_id,
    )
    _update_issue_description(
        agent_bead_id, updated, beads_root=beads_root, cwd=cwd
    )

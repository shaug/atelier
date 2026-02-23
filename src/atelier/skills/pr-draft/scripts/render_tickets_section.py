#!/usr/bin/env python3
"""Render a PR ``Tickets`` section from a changeset bead."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TicketRef:
    """Minimal external ticket reference used for PR ticket lines."""

    provider: str
    ticket_id: str
    relation: str | None = None


def parse_description_fields(description: str | None) -> dict[str, str]:
    """Parse key/value fields from a bead description."""
    fields: dict[str, str] = {}
    if not description:
        return fields
    for line in description.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        if not key:
            continue
        fields[key] = value.strip()
    return fields


def parse_external_tickets(description: str | None) -> list[TicketRef]:
    """Parse external ticket references from a bead description."""
    fields = parse_description_fields(description)
    raw = fields.get("external_tickets")
    if not raw or raw.lower() == "null":
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    tickets: list[TicketRef] = []
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        provider = str(entry.get("provider") or "").strip().lower()
        ticket_id = str(entry.get("id") or entry.get("ticket_id") or "").strip()
        relation = str(entry.get("relation") or "").strip().lower() or None
        if not provider or not ticket_id:
            continue
        tickets.append(TicketRef(provider=provider, ticket_id=ticket_id, relation=relation))
    return tickets


def format_ticket_reference(ticket: TicketRef) -> str:
    """Format the ticket identifier for a PR body."""
    if ticket.provider == "github":
        if ticket.ticket_id.startswith("#"):
            return ticket.ticket_id
        if ticket.ticket_id.isdigit():
            return f"#{ticket.ticket_id}"
    return ticket.ticket_id


def ticket_action_verb(ticket: TicketRef) -> str:
    """Resolve the ticket verb for a PR line."""
    if ticket.relation == "context":
        return "Addresses"
    return "Fixes"


def render_ticket_section(issue: dict[str, object]) -> str:
    """Render markdown for the PR ``Tickets`` section."""
    description = issue.get("description")
    tickets = parse_external_tickets(description if isinstance(description, str) else None)
    lines: list[str] = []
    seen: set[tuple[str, str]] = set()
    for ticket in tickets:
        reference = format_ticket_reference(ticket).strip()
        if not reference:
            continue
        dedupe_key = (ticket.provider, reference.lower())
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        lines.append(f"- {ticket_action_verb(ticket)} {reference}")
    if not lines:
        return ""
    return "\n".join(["## Tickets", *lines])


def _bd_command(*args: str) -> list[str]:
    command = ["bd", *args]
    if "--no-daemon" not in command:
        command.append("--no-daemon")
    return command


def load_issue(changeset_id: str, *, beads_dir: Path, repo_path: Path) -> dict[str, object]:
    """Load a changeset issue payload from Beads."""
    env = os.environ.copy()
    env["BEADS_DIR"] = str(beads_dir)
    command = _bd_command("show", changeset_id, "--json")
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

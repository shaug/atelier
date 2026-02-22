#!/usr/bin/env python3
"""Render a read-only planner startup overview for the current session."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from atelier import beads, config, planner_overview
from atelier.commands.resolve import resolve_current_project_with_repo_root


def _issue_sort_key(issue: dict[str, object]) -> tuple[str, str]:
    issue_id = str(issue.get("id") or "").strip()
    title = str(issue.get("title") or "").strip()
    return (issue_id, title)


def _queue_claim_state(issue: dict[str, object]) -> str:
    claimed_by = issue.get("claimed_by")
    if isinstance(claimed_by, str) and claimed_by.strip():
        return f"claimed by {claimed_by.strip()}"
    return "unclaimed"


def _resolve_agent_id(requested_agent_id: str | None) -> str:
    candidate = str(requested_agent_id or "").strip()
    if candidate:
        return candidate
    env_agent_id = os.environ.get("ATELIER_AGENT_ID", "").strip()
    if env_agent_id:
        return env_agent_id
    raise ValueError("planner overview requires --agent-id or ATELIER_AGENT_ID in the environment")


def _resolve_context(*, beads_dir: str | None) -> tuple[Path, Path]:
    repo_env = os.environ.get("ATELIER_PROJECT", "").strip()
    beads_env = str(beads_dir or "").strip() or os.environ.get("BEADS_DIR", "").strip()
    repo_root = Path(repo_env).resolve() if repo_env else Path.cwd()
    if beads_env:
        return Path(beads_env).expanduser().resolve(), repo_root
    project_root, project_config, _enlistment, repo_root = resolve_current_project_with_repo_root()
    project_data_dir = config.resolve_project_data_dir(project_root, project_config)
    return config.resolve_beads_root(project_data_dir, repo_root), repo_root


def _render_startup_overview(agent_id: str, *, beads_root: Path, repo_root: Path) -> str:
    lines: list[str] = ["Planner startup overview"]

    inbox = beads.list_inbox_messages(
        agent_id, beads_root=beads_root, cwd=repo_root, unread_only=True
    )
    if inbox:
        lines.append("Unread messages:")
        for issue in sorted(inbox, key=_issue_sort_key):
            lines.append(f"- {issue.get('id') or ''} {issue.get('title') or ''}")
    else:
        lines.append("No unread messages.")

    queued = beads.list_queue_messages(
        beads_root=beads_root,
        cwd=repo_root,
        unread_only=True,
        unclaimed_only=False,
    )
    if queued:
        lines.append("Queued messages:")
        for issue in sorted(queued, key=_issue_sort_key):
            lines.append(
                f"- {issue.get('id') or ''} [{issue.get('queue') or 'queue'}] "
                f"{issue.get('title') or ''} | claim: {_queue_claim_state(issue)}"
            )
    else:
        lines.append("No queued messages.")

    epics = planner_overview.list_epics(beads_root=beads_root, repo_root=repo_root)
    lines.extend(planner_overview.render_epics(epics, show_drafts=True).splitlines())
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--agent-id",
        default="",
        help="planner agent id (defaults to ATELIER_AGENT_ID)",
    )
    parser.add_argument(
        "--beads-dir",
        default="",
        help="beads root path (defaults to BEADS_DIR env var or project config)",
    )
    args = parser.parse_args()

    try:
        agent_id = _resolve_agent_id(args.agent_id)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    beads_root, repo_root = _resolve_context(beads_dir=args.beads_dir)
    if not beads_root.exists():
        print(f"error: beads dir not found: {beads_root}", file=sys.stderr)
        raise SystemExit(1)

    print(_render_startup_overview(agent_id, beads_root=beads_root, repo_root=repo_root))


if __name__ == "__main__":
    main()

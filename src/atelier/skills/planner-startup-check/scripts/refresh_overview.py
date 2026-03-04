#!/usr/bin/env python3
"""Render a read-only planner startup overview for the current session."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from atelier import lifecycle, planner_overview
from atelier.beads_context import resolve_runtime_repo_dir_hint, resolve_skill_beads_context
from atelier.planner_startup_check import (
    StartupBeadsInvocationHelper,
    StartupCommandResult,
    build_startup_triage_failure_model,
    build_startup_triage_model,
    execute_startup_command_plan,
    render_startup_triage_markdown,
)

DEFAULT_DEFERRED_EPIC_SCAN_LIMIT = 25


def _issue_sort_key(issue: dict[str, object]) -> tuple[str, str]:
    issue_id = str(issue.get("id") or "").strip()
    title = str(issue.get("title") or "").strip()
    return (issue_id, title)


def _deferred_descendant_changesets(
    epics: list[dict[str, object]],
    *,
    helper: StartupBeadsInvocationHelper,
) -> tuple[list[tuple[dict[str, object], list[dict[str, object]]]], int, int]:
    scan_limit = _deferred_epic_scan_limit()
    groups: list[tuple[dict[str, object], list[dict[str, object]]]] = []
    active_epics = []
    for epic in sorted(epics, key=_issue_sort_key):
        if lifecycle.canonical_lifecycle_status(epic.get("status")) not in {
            "open",
            "in_progress",
            "blocked",
        }:
            continue
        if not str(epic.get("id") or "").strip():
            continue
        active_epics.append(epic)

    scanned_epics = active_epics[:scan_limit]
    skipped_epics = max(0, len(active_epics) - len(scanned_epics))
    for epic in scanned_epics:
        epic_id = str(epic.get("id") or "").strip()
        descendants = helper.list_descendant_changesets(
            epic_id,
            include_closed=False,
        )
        deferred = [
            issue
            for issue in descendants
            if lifecycle.canonical_lifecycle_status(issue.get("status")) == "deferred"
        ]
        if deferred:
            groups.append((epic, sorted(deferred, key=_issue_sort_key)))
    return groups, skipped_epics, scan_limit


def _deferred_epic_scan_limit() -> int:
    raw_value = os.environ.get("ATELIER_STARTUP_DEFERRED_EPIC_SCAN_LIMIT", "").strip()
    if not raw_value:
        return DEFAULT_DEFERRED_EPIC_SCAN_LIMIT
    try:
        parsed_limit = int(raw_value)
    except ValueError:
        return DEFAULT_DEFERRED_EPIC_SCAN_LIMIT
    return max(0, parsed_limit)


def _resolve_agent_id(requested_agent_id: str | None) -> str:
    candidate = str(requested_agent_id or "").strip()
    if candidate:
        return candidate
    env_agent_id = os.environ.get("ATELIER_AGENT_ID", "").strip()
    if env_agent_id:
        return env_agent_id
    raise ValueError("planner overview requires --agent-id or ATELIER_AGENT_ID in the environment")


def _merge_warnings(*messages: str | None) -> str | None:
    lines = [message for message in messages if isinstance(message, str) and message.strip()]
    if not lines:
        return None
    return "\n".join(lines)


def _resolve_context(
    *, beads_dir: str | None, repo_dir: str | None
) -> tuple[Path, Path, str | None]:
    repo_hint, runtime_warning = resolve_runtime_repo_dir_hint(repo_dir=repo_dir)
    context = resolve_skill_beads_context(
        beads_dir=beads_dir,
        repo_dir=repo_hint,
    )
    return (
        context.beads_root,
        context.repo_root,
        _merge_warnings(
            runtime_warning,
            context.override_warning,
        ),
    )


def _startup_helper(*, beads_root: Path, repo_root: Path) -> StartupBeadsInvocationHelper:
    return StartupBeadsInvocationHelper(beads_root=beads_root, cwd=repo_root)


def _render_startup_overview(agent_id: str, *, beads_root: Path, repo_root: Path) -> str:
    helper = _startup_helper(beads_root=beads_root, repo_root=repo_root)
    try:
        command_result: StartupCommandResult = execute_startup_command_plan(
            agent_id,
            helper=helper,
        )
        deferred_groups, skipped_epics, scan_limit = _deferred_descendant_changesets(
            command_result.epics,
            helper=helper,
        )
        triage_model = build_startup_triage_model(
            beads_root=beads_root,
            command_result=command_result,
            deferred_groups=deferred_groups,
            deferred_scan_limit=scan_limit,
            deferred_scan_skipped_epics=skipped_epics,
            epic_list_markdown=planner_overview.render_epics(
                command_result.epics, show_drafts=True
            ),
        )
        return render_startup_triage_markdown(triage_model)
    except KeyboardInterrupt:
        raise
    except Exception as exc:
        fallback_model = build_startup_triage_failure_model(
            beads_root=beads_root,
            phase="render_startup_overview",
            error=exc,
        )
        return render_startup_triage_markdown(fallback_model)


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
        help="explicit beads root override (defaults to project-scoped store)",
    )
    parser.add_argument(
        "--repo-dir",
        default="",
        help="explicit repo root override (defaults to ./worktree, then cwd)",
    )
    args = parser.parse_args()

    try:
        agent_id = _resolve_agent_id(args.agent_id)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    beads_root, repo_root, override_warning = _resolve_context(
        beads_dir=args.beads_dir,
        repo_dir=str(args.repo_dir).strip() or None,
    )
    if override_warning:
        print(override_warning, file=sys.stderr)
    if not beads_root.exists():
        print(f"error: beads dir not found: {beads_root}", file=sys.stderr)
        raise SystemExit(1)

    print(_render_startup_overview(agent_id, beads_root=beads_root, repo_root=repo_root))


if __name__ == "__main__":
    main()

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
    execute_startup_command_plan,
)

DEFAULT_DEFERRED_EPIC_SCAN_LIMIT = 25


def _issue_sort_key(issue: dict[str, object]) -> tuple[str, str]:
    issue_id = str(issue.get("id") or "").strip()
    title = str(issue.get("title") or "").strip()
    return (issue_id, title)


def _queue_claim_state(issue: dict[str, object]) -> str:
    claimed_by = issue.get("claimed_by")
    if isinstance(claimed_by, str) and claimed_by.strip():
        return f"claimed by {claimed_by.strip()}"
    return "unclaimed"


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


def _append_deferred_changeset_summary(
    lines: list[str],
    epics: list[dict[str, object]],
    *,
    helper: StartupBeadsInvocationHelper,
) -> None:
    groups, skipped_epics, scan_limit = _deferred_descendant_changesets(
        epics,
        helper=helper,
    )
    if not groups:
        lines.append("No deferred changesets under open/in-progress/blocked epics.")
    else:
        lines.append("Deferred changesets under open/in-progress/blocked epics:")
        for epic, deferred in groups:
            epic_id = str(epic.get("id") or "").strip() or "(unknown)"
            epic_status = lifecycle.canonical_lifecycle_status(epic.get("status")) or "unknown"
            epic_title = str(epic.get("title") or "").strip() or "(untitled)"
            lines.append(f"- {epic_id} [{epic_status}] {epic_title}")
            for issue in deferred:
                issue_id = str(issue.get("id") or "").strip() or "(unknown)"
                issue_status = (
                    lifecycle.canonical_lifecycle_status(issue.get("status")) or "unknown"
                )
                issue_title = str(issue.get("title") or "").strip() or "(untitled)"
                lines.append(f"  - {issue_id} [{issue_status}] {issue_title}")

    if skipped_epics:
        lines.append(
            "Deferred changeset scan limited to first "
            f"{scan_limit} active epics; skipped {skipped_epics}."
        )


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
    lines: list[str] = ["Planner startup overview", f"- Beads root: {beads_root}"]
    helper = _startup_helper(beads_root=beads_root, repo_root=repo_root)
    command_result: StartupCommandResult = execute_startup_command_plan(
        agent_id,
        helper=helper,
    )

    inbox = command_result.inbox_messages
    if inbox:
        lines.append("Unread messages:")
        for issue in sorted(inbox, key=_issue_sort_key):
            lines.append(f"- {issue.get('id') or ''} {issue.get('title') or ''}")
    else:
        lines.append("No unread messages.")

    queued = command_result.queued_messages
    if queued:
        lines.append("Queued messages:")
        for issue in sorted(queued, key=_issue_sort_key):
            lines.append(
                f"- {issue.get('id') or ''} [{issue.get('queue') or 'queue'}] "
                f"{issue.get('title') or ''} | claim: {_queue_claim_state(issue)}"
            )
    else:
        lines.append("No queued messages.")

    epics = command_result.epics
    lines.append(f"- Total epics: {len(epics)}")
    parity = command_result.parity_report
    lines.append(
        f"- Active top-level work (open/in_progress/blocked): {parity.active_top_level_work_count}"
    )
    lines.append(f"- Indexed active epics (at:epic discovery): {parity.indexed_active_epic_count}")
    if parity.in_parity:
        lines.append("Epic discovery parity: ok")
    if parity.missing_executable_identity:
        lines.append("Identity guardrail violations (deterministic remediation):")
        for violation in parity.missing_executable_identity:
            labels = ", ".join(violation.labels) if violation.labels else "(none)"
            lines.append(
                f"- {violation.issue_id} [status={violation.status or 'missing'} "
                f"type={violation.issue_type or 'missing'}] labels={labels}"
            )
            lines.append(f"  remediation: {violation.remediation_command}")
    if parity.missing_from_index:
        lines.append("Discovery index mismatch for executable top-level work:")
        for issue_id in parity.missing_from_index:
            lines.append(f"- {issue_id}")
        lines.append(
            "  remediation: run `bd prime`; if mismatch persists, run "
            "`bd doctor --fix --yes` and rerun startup."
        )

    _append_deferred_changeset_summary(
        lines,
        epics,
        helper=helper,
    )
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

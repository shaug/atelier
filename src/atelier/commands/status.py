"""Implementation for the ``atelier status`` command."""

from __future__ import annotations

import json
from pathlib import Path

from rich import box
from rich.console import Console
from rich.table import Table

from .. import beads, config, messages, worktrees
from ..io import die, say
from .resolve import resolve_current_project_with_repo_root

_FORMATS = {"table", "json"}


def status(args: object) -> None:
    """Show project hooks, claims, and changeset status."""
    format_value = str(getattr(args, "format", "table") or "table").lower()
    if format_value not in _FORMATS:
        die(f"unsupported format: {format_value}")

    project_root, project_config, _enlistment, repo_root = (
        resolve_current_project_with_repo_root()
    )
    project_data_dir = config.resolve_project_data_dir(project_root, project_config)
    beads_root = config.resolve_beads_root(project_data_dir, repo_root)

    beads.run_bd_command(["prime"], beads_root=beads_root, cwd=repo_root)

    epic_issues = beads.run_bd_json(
        ["list", "--label", "at:epic"], beads_root=beads_root, cwd=repo_root
    )
    agent_issues = beads.run_bd_json(
        ["list", "--label", "at:agent"], beads_root=beads_root, cwd=repo_root
    )

    agents, hook_map = _build_agent_payloads(
        agent_issues, beads_root=beads_root, repo_root=repo_root
    )
    epics = _build_epic_payloads(
        epic_issues,
        hook_map=hook_map,
        project_data_dir=project_data_dir,
        beads_root=beads_root,
        repo_root=repo_root,
    )
    queues = _build_queue_payloads(
        beads_root=beads_root,
        repo_root=repo_root,
    )

    epics = sorted(epics, key=lambda item: (item.get("root_branch") or "", item["id"]))
    agents = sorted(agents, key=lambda item: item.get("agent_id") or "")

    counts = _status_counts(epics, agents, queues)
    project_info = {
        "project_dir": str(project_root),
        "repo_root": str(repo_root),
        "beads_root": str(beads_root),
    }
    payload = {
        "scope": "project",
        "project": project_info,
        "counts": counts,
        "epics": epics,
        "agents": agents,
        "queues": queues,
    }

    if format_value == "json":
        say(json.dumps(payload, indent=2, sort_keys=True))
        return

    _render_status(project_info, counts, epics, agents, queues)


def _build_agent_payloads(
    issues: list[dict[str, object]],
    *,
    beads_root: Path,
    repo_root: Path,
) -> tuple[list[dict[str, object]], dict[str, list[str]]]:
    payloads: list[dict[str, object]] = []
    hook_map: dict[str, list[str]] = {}
    for issue in issues:
        description = issue.get("description")
        fields = beads.parse_description_fields(
            description if isinstance(description, str) else ""
        )
        agent_id = fields.get("agent_id") or issue.get("title") or issue.get("id") or ""
        if not isinstance(agent_id, str):
            agent_id = str(agent_id)
        agent_id = agent_id.strip()
        role = fields.get("role_type") or fields.get("role")
        hook_bead = None
        issue_id = issue.get("id")
        if isinstance(issue_id, str) and issue_id:
            hook_bead = beads.get_agent_hook(
                issue_id, beads_root=beads_root, cwd=repo_root
            )
        if not hook_bead:
            hook_bead = fields.get("hook_bead")
        heartbeat_at = fields.get("heartbeat_at")
        labels = _issue_labels(issue)
        payload = {
            "id": issue.get("id"),
            "title": issue.get("title"),
            "agent_id": agent_id,
            "role": role,
            "hook_bead": hook_bead,
            "heartbeat_at": heartbeat_at,
            "labels": labels,
        }
        payloads.append(payload)
        if (
            isinstance(hook_bead, str)
            and hook_bead
            and isinstance(agent_id, str)
            and agent_id
        ):
            hook_map.setdefault(hook_bead, []).append(agent_id)
    return payloads, hook_map


def _build_epic_payloads(
    issues: list[dict[str, object]],
    *,
    hook_map: dict[str, list[str]],
    project_data_dir: Path,
    beads_root: Path,
    repo_root: Path,
) -> list[dict[str, object]]:
    payloads: list[dict[str, object]] = []
    for issue in issues:
        epic_id = issue.get("id")
        if not isinstance(epic_id, str) or not epic_id:
            continue
        labels = _issue_labels(issue)
        root_branch = beads.extract_workspace_root_branch(issue) or None
        mapping = worktrees.load_mapping(
            worktrees.mapping_path(project_data_dir, epic_id)
        )
        worktree_relpath = beads.extract_worktree_path(issue)
        if not worktree_relpath and mapping:
            worktree_relpath = mapping.worktree_path
        worktree_path = None
        if worktree_relpath:
            candidate = Path(worktree_relpath)
            worktree_path = (
                str(candidate)
                if candidate.is_absolute()
                else str(project_data_dir / candidate)
            )
        changesets = _list_changesets(
            epic_id, beads_root=beads_root, repo_root=repo_root
        )
        ready_changesets = _list_ready_changesets(
            epic_id, beads_root=beads_root, repo_root=repo_root
        )
        summary = beads.summarize_changesets(changesets, ready=ready_changesets)
        changeset_counts = summary.as_dict()
        payloads.append(
            {
                "id": epic_id,
                "title": issue.get("title"),
                "status": issue.get("status"),
                "assignee": _normalize_assignee(issue.get("assignee")),
                "labels": labels,
                "root_branch": root_branch,
                "workspace_label": beads.workspace_label(root_branch)
                if root_branch
                else None,
                "worktree_path": worktree_path,
                "worktree_relpath": worktree_relpath,
                "hooked_by": hook_map.get(epic_id, []),
                "hooked": "at:hooked" in labels or epic_id in hook_map,
                "changesets": changeset_counts,
                "ready_to_close": summary.ready_to_close,
            }
        )
    return payloads


def _list_changesets(
    epic_id: str, *, beads_root: Path, repo_root: Path
) -> list[dict[str, object]]:
    return beads.run_bd_json(
        ["list", "--parent", epic_id, "--label", "at:changeset"],
        beads_root=beads_root,
        cwd=repo_root,
    )


def _list_ready_changesets(
    epic_id: str, *, beads_root: Path, repo_root: Path
) -> list[dict[str, object]]:
    return beads.run_bd_json(
        [
            "ready",
            "--parent",
            epic_id,
            "--label",
            "at:changeset",
            "--label",
            "cs:ready",
        ],
        beads_root=beads_root,
        cwd=repo_root,
    )


def _normalize_assignee(value: object) -> str | None:
    if isinstance(value, str):
        return value or None
    if isinstance(value, dict):
        for key in ("id", "name", "login"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate:
                return candidate
    return None


def _issue_labels(issue: dict[str, object]) -> list[str]:
    labels = issue.get("labels")
    if not isinstance(labels, list):
        return []
    return [str(label) for label in labels if label]


def _status_counts(
    epics: list[dict[str, object]],
    agents: list[dict[str, object]],
    queues: list[dict[str, object]],
) -> dict[str, object]:
    status_counts: dict[str, int] = {}
    total_changesets = 0
    ready_changesets = 0
    for epic in epics:
        status = str(epic.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        changesets = epic.get("changesets")
        if isinstance(changesets, dict):
            total_changesets += int(changesets.get("total", 0))
            ready_changesets += int(changesets.get("ready", 0))
    queue_total = sum(int(queue.get("total", 0)) for queue in queues)
    queue_claimed = sum(int(queue.get("claimed", 0)) for queue in queues)
    return {
        "epics": len(epics),
        "agents": len(agents),
        "changesets": total_changesets,
        "changesets_ready": ready_changesets,
        "queues": len(queues),
        "queue_messages": queue_total,
        "queue_claimed": queue_claimed,
        "epic_statuses": status_counts,
    }


def _build_queue_payloads(
    *, beads_root: Path, repo_root: Path
) -> list[dict[str, object]]:
    issues = beads.run_bd_json(
        ["list", "--label", "at:message"], beads_root=beads_root, cwd=repo_root
    )
    queues: dict[str, dict[str, int]] = {}
    for issue in issues:
        description = issue.get("description")
        if not isinstance(description, str):
            continue
        payload = messages.parse_message(description)
        queue_name = payload.metadata.get("queue")
        if not isinstance(queue_name, str) or not queue_name.strip():
            continue
        claimed_by = payload.metadata.get("claimed_by")
        entry = queues.setdefault(
            queue_name, {"total": 0, "claimed": 0, "unclaimed": 0}
        )
        entry["total"] += 1
        if isinstance(claimed_by, str) and claimed_by.strip():
            entry["claimed"] += 1
        else:
            entry["unclaimed"] += 1
    payloads = [{"queue": name, **stats} for name, stats in sorted(queues.items())]
    return payloads


def _render_status(
    project_info: dict[str, object],
    counts: dict[str, object],
    epics: list[dict[str, object]],
    agents: list[dict[str, object]],
    queues: list[dict[str, object]],
) -> None:
    console = Console()
    overview = Table(title="Project Status", box=box.SIMPLE, show_header=False)
    overview.add_column("Field", style="bold")
    overview.add_column("Value", overflow="fold")
    overview.add_row("Project dir", _display_value(project_info.get("project_dir")))
    overview.add_row("Repo root", _display_value(project_info.get("repo_root")))
    overview.add_row("Beads root", _display_value(project_info.get("beads_root")))
    overview.add_row("Epics", _display_value(counts.get("epics")))
    overview.add_row("Agents", _display_value(counts.get("agents")))
    overview.add_row("Changesets", _display_value(counts.get("changesets")))
    overview.add_row("Ready changesets", _display_value(counts.get("changesets_ready")))
    overview.add_row("Queues", _display_value(counts.get("queues")))
    overview.add_row("Queued messages", _display_value(counts.get("queue_messages")))
    overview.add_row("Claimed messages", _display_value(counts.get("queue_claimed")))
    console.print(overview)

    if epics:
        table = Table(title="Epics", box=box.SIMPLE)
        table.add_column("Epic", no_wrap=True)
        table.add_column("Status", no_wrap=True)
        table.add_column("Assignee", no_wrap=True)
        table.add_column("Root", no_wrap=True)
        table.add_column("Hooked by", no_wrap=True)
        table.add_column("Changesets", justify="right")
        table.add_column("Worktree", overflow="fold")
        for epic in epics:
            changesets = epic.get("changesets") or {}
            ready = changesets.get("ready")
            total = changesets.get("total")
            ready_display = (
                f"{ready}/{total}" if ready is not None and total is not None else "0/0"
            )
            hooked_by = epic.get("hooked_by") or []
            if isinstance(hooked_by, list):
                hooked_by_display = ", ".join(
                    [value for value in hooked_by if value]
                ).strip()
            else:
                hooked_by_display = str(hooked_by or "").strip()
            table.add_row(
                str(epic.get("id") or ""),
                _display_value(epic.get("status")),
                _display_value(epic.get("assignee")),
                _display_value(epic.get("root_branch")),
                hooked_by_display or "-",
                ready_display,
                _display_value(epic.get("worktree_relpath")),
            )
        console.print(table)
    else:
        console.print("No epics found.")

    if agents:
        table = Table(title="Agents", box=box.SIMPLE)
        table.add_column("Agent", no_wrap=True)
        table.add_column("Role", no_wrap=True)
        table.add_column("Hook", no_wrap=True)
        table.add_column("Heartbeat", no_wrap=True)
        for agent in agents:
            table.add_row(
                _display_value(agent.get("agent_id")),
                _display_value(agent.get("role")),
                _display_value(agent.get("hook_bead")),
                _display_value(agent.get("heartbeat_at")),
            )
        console.print(table)
    else:
        console.print("No agents found.")

    if queues:
        table = Table(title="Queues", box=box.SIMPLE)
        table.add_column("Queue", no_wrap=True)
        table.add_column("Total", justify="right")
        table.add_column("Claimed", justify="right")
        table.add_column("Unclaimed", justify="right")
        for queue in queues:
            table.add_row(
                _display_value(queue.get("queue")),
                _display_value(queue.get("total")),
                _display_value(queue.get("claimed")),
                _display_value(queue.get("unclaimed")),
            )
        console.print(table)


def _display_value(value: object) -> str:
    if value is None or value == "":
        return "unknown"
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)

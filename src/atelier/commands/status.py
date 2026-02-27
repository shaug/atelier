"""Implementation for the ``atelier status`` command."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Mapping

from rich import box
from rich.console import Console
from rich.table import Table

from .. import beads, config, git, lifecycle, messages, pr_strategy, prs, worktrees
from ..io import die, say
from ..worker import selection as worker_selection
from ..worker.finalization import pr_gate as worker_pr_gate
from .resolve import resolve_current_project_with_repo_root

_FORMATS = {"table", "json"}


def status(args: object) -> None:
    """Show project hooks, claims, and changeset status."""
    format_value = str(getattr(args, "format", "table") or "table").lower()
    if format_value not in _FORMATS:
        die(f"unsupported format: {format_value}")

    project_root, project_config, _enlistment, repo_root = resolve_current_project_with_repo_root()
    project_data_dir = config.resolve_project_data_dir(project_root, project_config)
    beads_root = config.resolve_beads_root(project_data_dir, repo_root)

    beads.run_bd_command(["prime"], beads_root=beads_root, cwd=repo_root)

    epic_issues = beads.list_epics(beads_root=beads_root, cwd=repo_root, include_closed=True)
    agent_issues = beads.run_bd_json(
        ["list", "--label", "at:agent"], beads_root=beads_root, cwd=repo_root
    )

    agents, hook_map, agent_index = _build_agent_payloads(
        agent_issues, beads_root=beads_root, repo_root=repo_root
    )
    origin = project_config.project.origin or project_config.project.repo_url
    repo_slug = prs.github_repo_slug(origin)
    epics = _build_epic_payloads(
        epic_issues,
        hook_map=hook_map,
        project_data_dir=project_data_dir,
        beads_root=beads_root,
        repo_root=repo_root,
        repo_slug=repo_slug,
        agent_index=agent_index,
    )
    diagnostics = _build_identity_diagnostics(
        beads.list_top_level_work_missing_epic_identity(
            beads_root=beads_root,
            cwd=repo_root,
            include_closed=False,
        )
    )
    queues = _build_queue_payloads(
        beads_root=beads_root,
        repo_root=repo_root,
    )

    epics = sorted(
        epics,
        key=lambda item: (
            str(item.get("root_branch") or ""),
            str(item.get("id") or ""),
        ),
    )
    agents = sorted(agents, key=lambda item: str(item.get("agent_id") or ""))

    counts = _status_counts(epics, agents, queues, diagnostics=diagnostics)
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
        "diagnostics": diagnostics,
    }

    if format_value == "json":
        say(json.dumps(payload, indent=2, sort_keys=True))
        return

    _render_status(project_info, counts, epics, agents, queues, diagnostics=diagnostics)


def _build_agent_payloads(
    issues: list[dict[str, object]],
    *,
    beads_root: Path,
    repo_root: Path,
) -> tuple[
    list[dict[str, object]],
    dict[str, list[str]],
    dict[str, dict[str, object]],
]:
    payloads: list[dict[str, object]] = []
    hook_map: dict[str, list[str]] = {}
    agent_index: dict[str, dict[str, object]] = {}
    for issue in issues:
        description = issue.get("description")
        fields = beads.parse_description_fields(description if isinstance(description, str) else "")
        agent_id = fields.get("agent_id") or issue.get("title") or issue.get("id") or ""
        if not isinstance(agent_id, str):
            agent_id = str(agent_id)
        agent_id = agent_id.strip()
        role = fields.get("role_type") or fields.get("role")
        hook_bead = None
        issue_id = issue.get("id")
        if isinstance(issue_id, str) and issue_id:
            hook_bead = beads.get_agent_hook(issue_id, beads_root=beads_root, cwd=repo_root)
        if not hook_bead:
            hook_bead = fields.get("hook_bead")
        heartbeat_at = fields.get("heartbeat_at")
        labels = _issue_labels(issue)
        family_id = _agent_family_id(agent_id)
        session_key = _agent_session_key(agent_id)
        session_pid = _agent_session_pid(agent_id)
        session_state = _agent_session_state(agent_id)
        reclaimable = session_state == "stale"
        payload = {
            "id": issue.get("id"),
            "title": issue.get("title"),
            "agent_id": agent_id,
            "family_id": family_id,
            "role": role,
            "hook_bead": hook_bead,
            "heartbeat_at": heartbeat_at,
            "session_key": session_key,
            "session_pid": session_pid,
            "session_state": session_state,
            "reclaimable": reclaimable,
            "labels": labels,
        }
        payloads.append(payload)
        if isinstance(agent_id, str) and agent_id:
            agent_index[agent_id] = payload
        if isinstance(hook_bead, str) and hook_bead and isinstance(agent_id, str) and agent_id:
            hook_map.setdefault(hook_bead, []).append(agent_id)
    return payloads, hook_map, agent_index


def _build_epic_payloads(
    issues: list[dict[str, object]],
    *,
    hook_map: dict[str, list[str]],
    project_data_dir: Path,
    beads_root: Path,
    repo_root: Path,
    repo_slug: str | None,
    agent_index: dict[str, dict[str, object]],
) -> list[dict[str, object]]:
    payloads: list[dict[str, object]] = []
    for issue in issues:
        epic_id = issue.get("id")
        if not isinstance(epic_id, str) or not epic_id:
            continue
        description = issue.get("description")
        fields = beads.parse_description_fields(description if isinstance(description, str) else "")
        labels = _issue_labels(issue)
        root_branch = beads.extract_workspace_root_branch(issue) or None
        mapping = worktrees.load_mapping(worktrees.mapping_path(project_data_dir, epic_id))
        worktree_relpath = beads.extract_worktree_path(issue)
        if not worktree_relpath and mapping:
            worktree_relpath = mapping.worktree_path
        worktree_path = None
        if worktree_relpath:
            candidate = Path(worktree_relpath)
            worktree_path = (
                str(candidate) if candidate.is_absolute() else str(project_data_dir / candidate)
            )
        changesets = _list_changesets(epic_id, beads_root=beads_root, repo_root=repo_root)
        changeset_details = _build_changeset_details(
            changesets,
            mapping=mapping,
            beads_root=beads_root,
            repo_root=repo_root,
            repo_slug=repo_slug,
            pr_strategy_value=fields.get("workspace.pr_strategy"),
        )
        ready_changesets = _list_ready_changesets(
            epic_id, beads_root=beads_root, repo_root=repo_root
        )
        summary = beads.summarize_changesets(changesets, ready=ready_changesets)
        changeset_counts = summary.as_dict()
        assignee = _normalize_assignee(issue.get("assignee"))
        assignee_session_state, assignee_session_pid = _assignee_session_status(
            assignee, agent_index=agent_index
        )
        reclaimable = assignee_session_state == "stale"
        ownership_policy_violation = worker_selection.has_planner_executable_assignee(issue)
        ownership_policy_reason = None
        if ownership_policy_violation:
            ownership_policy_reason = "planner-owned executable work"
        payloads.append(
            {
                "id": epic_id,
                "title": issue.get("title"),
                "status": issue.get("status"),
                "assignee": assignee,
                "assignee_session_state": assignee_session_state,
                "assignee_session_pid": assignee_session_pid,
                "reclaimable": reclaimable,
                "labels": labels,
                "root_branch": root_branch,
                "pr_strategy": fields.get("workspace.pr_strategy") or None,
                "workspace_label": (beads.workspace_label(root_branch) if root_branch else None),
                "worktree_path": worktree_path,
                "worktree_relpath": worktree_relpath,
                "hooked_by": hook_map.get(epic_id, []),
                "hooked": "at:hooked" in labels or epic_id in hook_map,
                "changesets": changeset_counts,
                "changeset_details": changeset_details,
                "ready_to_close": summary.ready_to_close,
                "ownership_policy_violation": ownership_policy_violation,
                "ownership_policy_reason": ownership_policy_reason,
            }
        )
    return payloads


def _build_changeset_details(
    changesets: list[dict[str, object]],
    *,
    mapping: worktrees.WorktreeMapping | None,
    beads_root: Path,
    repo_root: Path,
    repo_slug: str | None,
    pr_strategy_value: object,
) -> list[dict[str, object]]:
    details: list[dict[str, object]] = []
    strategy = pr_strategy.normalize_pr_strategy(pr_strategy_value)
    changesets_by_id: dict[str, dict[str, object]] = {}
    payload_by_repo_branch: dict[tuple[str, str], dict[str, object] | None] = {}
    payload_errors_by_repo_branch: dict[tuple[str, str], str | None] = {}

    def lookup_pr_payload(branch_repo_slug: str | None, branch: str) -> dict[str, object] | None:
        if not branch_repo_slug:
            return None
        cache_key = (branch_repo_slug, branch)
        if cache_key in payload_by_repo_branch:
            return payload_by_repo_branch[cache_key]
        lookup = prs.lookup_github_pr_status(branch_repo_slug, branch)
        payload = lookup.payload if lookup.found else None
        error: str | None = None
        if lookup.failed:
            error = lookup.error or "unknown gh error"
            if error.startswith("missing required command: gh"):
                error = None
        payload_by_repo_branch[cache_key] = payload
        payload_errors_by_repo_branch[cache_key] = error
        return payload

    def lookup_pr_payload_diagnostic(
        branch_repo_slug: str | None, branch: str
    ) -> tuple[dict[str, object] | None, str | None]:
        if not branch_repo_slug:
            return None, None
        payload = lookup_pr_payload(branch_repo_slug, branch)
        return payload, payload_errors_by_repo_branch.get((branch_repo_slug, branch))

    for issue in changesets:
        issue_id = issue.get("id")
        if isinstance(issue_id, str) and issue_id:
            changesets_by_id[issue_id] = issue
    for issue in changesets:
        changeset_id = issue.get("id")
        if not isinstance(changeset_id, str) or not changeset_id:
            continue
        labels = _issue_labels(issue)
        branch = None
        if mapping is not None:
            branch = mapping.changesets.get(changeset_id)
        pushed = False
        if branch:
            pushed = git.git_ref_exists(repo_root, f"refs/remotes/origin/{branch}")
        pr_payload = None
        if repo_slug and branch:
            pr_payload = lookup_pr_payload(repo_slug, branch)
        review_requested = prs.has_review_requests(pr_payload)
        lifecycle = prs.lifecycle_state(
            pr_payload, pushed=pushed, review_requested=review_requested
        )
        merge_conflict = prs.default_branch_has_merge_conflict(pr_payload)
        details.append(
            {
                "id": changeset_id,
                "title": issue.get("title"),
                "labels": labels,
                "branch": branch,
                "pushed": pushed,
                "review_requested": review_requested,
                "lifecycle_state": lifecycle,
                "merge_conflict": merge_conflict,
                "pr": _summarize_pr(pr_payload),
                "_issue": issue,
            }
        )
    for detail in details:
        issue = detail.pop("_issue", None)
        if not isinstance(issue, dict):
            detail["pr_allowed"] = False
            detail["pr_gate_reason"] = "blocked:changeset-payload-missing"
            continue
        decision = worker_pr_gate.changeset_pr_creation_decision(
            issue,
            repo_slug=repo_slug,
            repo_root=repo_root,
            git_path=None,
            branch_pr_strategy=strategy,
            beads_root=beads_root,
            lookup_pr_payload=lookup_pr_payload,
            lookup_pr_payload_diagnostic=lookup_pr_payload_diagnostic,
            lookup_dependency_issue=changesets_by_id.get,
        )
        detail["pr_allowed"] = decision.allow_pr
        detail["pr_gate_reason"] = decision.reason
    return details


def _summarize_pr(payload: dict[str, object] | None) -> dict[str, object] | None:
    if not payload:
        return None
    return {
        "number": payload.get("number"),
        "url": payload.get("url"),
        "state": payload.get("state"),
        "is_draft": payload.get("isDraft"),
        "review_decision": payload.get("reviewDecision"),
        "mergeable": payload.get("mergeable"),
        "merge_state_status": payload.get("mergeStateStatus"),
        "updated_at": payload.get("updatedAt"),
    }


def _list_changesets(epic_id: str, *, beads_root: Path, repo_root: Path) -> list[dict[str, object]]:
    descendants = beads.list_descendant_changesets(
        epic_id,
        beads_root=beads_root,
        cwd=repo_root,
        include_closed=True,
    )
    if not descendants:
        work_children = beads.list_work_children(
            epic_id,
            beads_root=beads_root,
            cwd=repo_root,
            include_closed=True,
        )
        if not work_children:
            epic_issues = beads.run_bd_json(["show", epic_id], beads_root=beads_root, cwd=repo_root)
            return epic_issues if epic_issues else []
    return descendants


def _list_ready_changesets(
    epic_id: str, *, beads_root: Path, repo_root: Path
) -> list[dict[str, object]]:
    return beads.run_bd_json(
        ["ready", "--parent", epic_id],
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


def _agent_family_id(agent_id: str) -> str:
    parts = [part for part in str(agent_id).split("/") if part]
    if len(parts) >= 3 and parts[0] == "atelier":
        return "/".join(parts[:3])
    return str(agent_id)


def _agent_session_key(agent_id: str) -> str | None:
    parts = [part for part in str(agent_id).split("/") if part]
    if len(parts) < 4 or parts[0] != "atelier":
        return None
    return parts[3]


def _agent_session_pid(agent_id: str) -> int | None:
    session_key = _agent_session_key(agent_id)
    if not session_key or not session_key.startswith("p"):
        return None
    pid_part = session_key[1:].split("-", 1)[0]
    if not pid_part.isdigit():
        return None
    return int(pid_part)


def _pid_is_alive(pid: int) -> bool:
    if pid == os.getpid():
        return True
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _agent_session_state(agent_id: str) -> str:
    session_key = _agent_session_key(agent_id)
    if not session_key:
        return "legacy"
    pid = _agent_session_pid(agent_id)
    if pid is None:
        return "unknown"
    return "live" if _pid_is_alive(pid) else "stale"


def _assignee_session_status(
    assignee: str | None,
    *,
    agent_index: dict[str, dict[str, object]],
) -> tuple[str | None, int | None]:
    if not assignee:
        return None, None
    known = agent_index.get(assignee)
    if known is not None:
        state = known.get("session_state")
        pid = known.get("session_pid")
        return str(state) if state else None, int(pid) if isinstance(pid, int) else None
    return _agent_session_state(assignee), _agent_session_pid(assignee)


def _issue_labels(issue: dict[str, object]) -> list[str]:
    labels = issue.get("labels")
    if not isinstance(labels, list):
        return []
    return [str(label) for label in labels if label]


def _status_counts(
    epics: list[dict[str, object]],
    agents: list[dict[str, object]],
    queues: list[dict[str, object]],
    *,
    diagnostics: dict[str, object],
) -> dict[str, object]:
    def _to_int(value: object) -> int:
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            try:
                return int(value)
            except ValueError:
                return 0
        return 0

    status_counts: dict[str, int] = {}
    total_changesets = 0
    ready_changesets = 0
    for epic in epics:
        status = str(epic.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        changesets = epic.get("changesets")
        if isinstance(changesets, dict):
            total_changesets += _to_int(changesets.get("total"))
            ready_changesets += _to_int(changesets.get("ready"))
    queue_total = sum(_to_int(queue.get("total")) for queue in queues)
    queue_claimed = sum(_to_int(queue.get("claimed")) for queue in queues)
    stale_agents = sum(1 for agent in agents if str(agent.get("session_state") or "") == "stale")
    reclaimable_epics = sum(1 for epic in epics if bool(epic.get("reclaimable")))
    ownership_policy_violations = sum(
        1 for epic in epics if bool(epic.get("ownership_policy_violation"))
    )
    missing_epic_identity = diagnostics.get("missing_epic_identity")
    if isinstance(missing_epic_identity, list):
        missing_epic_identity_count = len(missing_epic_identity)
    else:
        missing_epic_identity_count = 0
    return {
        "epics": len(epics),
        "agents": len(agents),
        "agents_stale": stale_agents,
        "changesets": total_changesets,
        "changesets_ready": ready_changesets,
        "epics_reclaimable": reclaimable_epics,
        "ownership_policy_violations": ownership_policy_violations,
        "missing_epic_identity": missing_epic_identity_count,
        "queues": len(queues),
        "queue_messages": queue_total,
        "queue_claimed": queue_claimed,
        "epic_statuses": status_counts,
    }


def _build_queue_payloads(*, beads_root: Path, repo_root: Path) -> list[dict[str, object]]:
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
        entry = queues.setdefault(queue_name, {"total": 0, "claimed": 0, "unclaimed": 0})
        entry["total"] += 1
        if isinstance(claimed_by, str) and claimed_by.strip():
            entry["claimed"] += 1
        else:
            entry["unclaimed"] += 1
    payloads = [{"queue": name, **stats} for name, stats in sorted(queues.items())]
    return payloads


def _render_status(
    project_info: Mapping[str, str],
    counts: dict[str, object],
    epics: list[dict[str, object]],
    agents: list[dict[str, object]],
    queues: list[dict[str, object]],
    *,
    diagnostics: dict[str, object],
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
    overview.add_row("Stale agents", _display_value(counts.get("agents_stale")))
    overview.add_row("Changesets", _display_value(counts.get("changesets")))
    overview.add_row("Ready changesets", _display_value(counts.get("changesets_ready")))
    overview.add_row("Reclaimable epics", _display_value(counts.get("epics_reclaimable")))
    overview.add_row(
        "Ownership violations",
        _display_value(counts.get("ownership_policy_violations")),
    )
    overview.add_row(
        "Identity gaps",
        _display_value(counts.get("missing_epic_identity")),
    )
    overview.add_row("Queues", _display_value(counts.get("queues")))
    overview.add_row("Queued messages", _display_value(counts.get("queue_messages")))
    overview.add_row("Claimed messages", _display_value(counts.get("queue_claimed")))
    console.print(overview)

    if epics:
        table = Table(title="Epics", box=box.SIMPLE)
        table.add_column("Epic", no_wrap=True)
        table.add_column("Status", no_wrap=True)
        table.add_column("Assignee", no_wrap=True)
        table.add_column("Session", no_wrap=True)
        table.add_column("Reclaim", no_wrap=True)
        table.add_column("Root", no_wrap=True)
        table.add_column("PR Strategy", no_wrap=True)
        table.add_column("Hooked by", no_wrap=True)
        table.add_column("Policy", no_wrap=True)
        table.add_column("Changesets", justify="right")
        table.add_column("Worktree", overflow="fold")
        for epic in epics:
            raw_changesets = epic.get("changesets")
            changesets = raw_changesets if isinstance(raw_changesets, dict) else {}
            ready = changesets.get("ready")
            total = changesets.get("total")
            ready_display = f"{ready}/{total}" if ready is not None and total is not None else "0/0"
            hooked_by = epic.get("hooked_by") or []
            if isinstance(hooked_by, list):
                hooked_by_display = ", ".join([value for value in hooked_by if value]).strip()
            else:
                hooked_by_display = str(hooked_by or "").strip()
            table.add_row(
                str(epic.get("id") or ""),
                _display_value(epic.get("status")),
                _display_value(epic.get("assignee")),
                _display_value(epic.get("assignee_session_state")),
                _display_value(epic.get("reclaimable")),
                _display_value(epic.get("root_branch")),
                _display_value(epic.get("pr_strategy")),
                hooked_by_display or "-",
                _display_value(epic.get("ownership_policy_reason") or "ok"),
                ready_display,
                _display_value(epic.get("worktree_relpath")),
            )
        console.print(table)
    else:
        console.print("No epics found.")

    missing_epic_identity = diagnostics.get("missing_epic_identity")
    if isinstance(missing_epic_identity, list) and missing_epic_identity:
        table = Table(title="Identity Diagnostics", box=box.SIMPLE)
        table.add_column("Issue", no_wrap=True)
        table.add_column("Status", no_wrap=True)
        table.add_column("Type", no_wrap=True)
        table.add_column("Reason", overflow="fold")
        for detail in missing_epic_identity:
            if not isinstance(detail, dict):
                continue
            table.add_row(
                _display_value(detail.get("id")),
                _display_value(detail.get("status")),
                _display_value(detail.get("issue_type")),
                _display_value(detail.get("reason")),
            )
        console.print(table)

    if agents:
        table = Table(title="Agents", box=box.SIMPLE)
        table.add_column("Agent", no_wrap=True)
        table.add_column("Role", no_wrap=True)
        table.add_column("Session", no_wrap=True)
        table.add_column("PID", no_wrap=True)
        table.add_column("State", no_wrap=True)
        table.add_column("Reclaim", no_wrap=True)
        table.add_column("Hook", no_wrap=True)
        table.add_column("Heartbeat", no_wrap=True)
        for agent in agents:
            table.add_row(
                _display_value(agent.get("agent_id")),
                _display_value(agent.get("role")),
                _display_value(agent.get("session_key")),
                _display_value(agent.get("session_pid")),
                _display_value(agent.get("session_state")),
                _display_value(agent.get("reclaimable")),
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


def _build_identity_diagnostics(issues: list[dict[str, object]]) -> dict[str, object]:
    missing_epic_identity: list[dict[str, object]] = []
    for issue in issues:
        issue_id = issue.get("id")
        if not isinstance(issue_id, str) or not issue_id.strip():
            continue
        canonical_status = lifecycle.canonical_lifecycle_status(issue.get("status")) or "unknown"
        issue_type = lifecycle.normalize_status_value(lifecycle.issue_payload_type(issue)) or "work"
        missing_epic_identity.append(
            {
                "id": issue_id.strip(),
                "status": canonical_status,
                "issue_type": issue_type,
                "reason": "missing at:epic identity label on top-level work",
            }
        )
    return {"missing_epic_identity": missing_epic_identity}

"""GC operations for stale agent hooks and epic claims."""

from __future__ import annotations

from pathlib import Path

from .. import beads
from .common import issue_labels, parse_rfc3339, try_show_issue
from .models import GcAction


def release_epic(epic: dict[str, object], *, beads_root: Path, cwd: Path) -> None:
    epic_id = str(epic.get("id") or "")
    if not epic_id:
        return
    labels = issue_labels(epic)
    status = str(epic.get("status") or "")
    args = ["update", epic_id, "--assignee", ""]
    if "at:hooked" in labels:
        args.extend(["--remove-label", "at:hooked"])
    if status and status not in {"closed", "done"}:
        args.extend(["--status", "open"])
    beads.run_bd_command(args, beads_root=beads_root, cwd=cwd, allow_failure=True)


def collect_hooks(
    *,
    beads_root: Path,
    repo_root: Path,
    stale_hours: float,
    include_missing_heartbeat: bool,
) -> list[GcAction]:
    import datetime as dt

    now = dt.datetime.now(tz=dt.timezone.utc)
    stale_delta = dt.timedelta(hours=stale_hours)
    actions: list[GcAction] = []

    agent_issues = beads.run_bd_json(
        ["list", "--label", "at:agent"], beads_root=beads_root, cwd=repo_root
    )
    agents: dict[str, dict[str, object]] = {}
    for issue in agent_issues:
        description = issue.get("description")
        fields = beads.parse_description_fields(description if isinstance(description, str) else "")
        agent_id = fields.get("agent_id") or issue.get("title")
        if not isinstance(agent_id, str) or not agent_id:
            continue
        agent_id = agent_id.strip()
        if not agent_id:
            continue
        issue_id = issue.get("id") if isinstance(issue, dict) else None
        hook_bead = None
        if isinstance(issue_id, str) and issue_id:
            hook_bead = beads.get_agent_hook(issue_id, beads_root=beads_root, cwd=repo_root)
        if not hook_bead:
            hook_bead = fields.get("hook_bead")
        agents[agent_id] = {
            "issue": issue,
            "issue_id": issue_id,
            "fields": fields,
            "hook_bead": hook_bead,
            "heartbeat_at": fields.get("heartbeat_at"),
        }

    epics = beads.list_epics(beads_root=beads_root, cwd=repo_root, include_closed=True)

    for agent_id, payload in agents.items():
        hook_bead = payload.get("hook_bead")
        if not isinstance(hook_bead, str) or not hook_bead:
            continue
        heartbeat_raw = payload.get("heartbeat_at")
        heartbeat = parse_rfc3339(heartbeat_raw if isinstance(heartbeat_raw, str) else None)
        stale = False
        if heartbeat is None:
            stale = include_missing_heartbeat
        else:
            stale = now - heartbeat > stale_delta
        if not stale:
            continue
        issue = payload.get("issue")
        issue_id = issue.get("id") if isinstance(issue, dict) else None
        if not isinstance(issue_id, str) or not issue_id:
            continue
        epic = try_show_issue(hook_bead, beads_root=beads_root, cwd=repo_root)
        description = f"Release stale hook for {agent_id} (epic {hook_bead})"

        def _apply_release(
            agent_bead_id: str = issue_id,
            epic_issue: dict[str, object] | None = epic,
        ) -> None:
            if epic_issue:
                release_epic(epic_issue, beads_root=beads_root, cwd=repo_root)
            beads.clear_agent_hook(agent_bead_id, beads_root=beads_root, cwd=repo_root)

        actions.append(GcAction(description=description, apply=_apply_release))

    for epic in epics:
        labels = issue_labels(epic)
        assignee = epic.get("assignee")
        epic_id = epic.get("id")
        description = epic.get("description")
        fields = beads.parse_description_fields(description if isinstance(description, str) else "")
        claim_expires_raw = fields.get("claim_expires_at")
        claim_expires_at = parse_rfc3339(
            claim_expires_raw if isinstance(claim_expires_raw, str) else None
        )
        if "at:hooked" not in labels and not assignee and claim_expires_at is None:
            continue
        if not isinstance(epic_id, str) or not epic_id:
            continue
        status = str(epic.get("status") or "").lower()
        assignee_id = assignee if isinstance(assignee, str) else ""
        agent_info = agents.get(assignee_id) if assignee_id else None
        hook_bead = agent_info.get("hook_bead") if agent_info else None
        if claim_expires_at is not None and claim_expires_at <= now:
            description = f"Release expired claim for epic {epic_id}"

            def _apply_expired(
                epic_issue: dict[str, object] = epic,
                agent_payload: dict[str, object] | None = agent_info,
                epic_id_value: str = epic_id,
            ) -> None:
                release_epic(epic_issue, beads_root=beads_root, cwd=repo_root)
                if agent_payload and agent_payload.get("hook_bead") == epic_id_value:
                    agent_issue_id = agent_payload.get("issue_id")
                    if isinstance(agent_issue_id, str) and agent_issue_id:
                        beads.clear_agent_hook(agent_issue_id, beads_root=beads_root, cwd=repo_root)

            actions.append(GcAction(description=description, apply=_apply_expired))
            continue

        if claim_expires_at is not None and "at:hooked" not in labels and not assignee:
            continue

        if status in {"closed", "done"} and ("at:hooked" in labels or assignee):
            description = f"Release closed epic hook {epic_id}"

            def _apply_closed(
                epic_issue: dict[str, object] = epic,
                agent_payload: dict[str, object] | None = agent_info,
                epic_id_value: str = epic_id,
            ) -> None:
                release_epic(epic_issue, beads_root=beads_root, cwd=repo_root)
                if agent_payload and agent_payload.get("hook_bead") == epic_id_value:
                    agent_issue_id = agent_payload.get("issue_id")
                    if isinstance(agent_issue_id, str) and agent_issue_id:
                        beads.clear_agent_hook(agent_issue_id, beads_root=beads_root, cwd=repo_root)

            actions.append(GcAction(description=description, apply=_apply_closed))
            continue

        if not agent_info or hook_bead != epic_id:
            description = f"Release orphaned epic hook {epic_id}"

            def _apply_unhook(epic_issue: dict[str, object] = epic) -> None:
                release_epic(epic_issue, beads_root=beads_root, cwd=repo_root)

            actions.append(GcAction(description=description, apply=_apply_unhook))
    return actions

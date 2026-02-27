"""GC operations for stale agent homes."""

from __future__ import annotations

from pathlib import Path

from .. import agent_home, beads
from .common import issue_labels, try_show_issue
from .hooks import release_epic
from .models import GcAction


def collect_agent_homes(
    *,
    project_dir: Path,
    beads_root: Path,
    repo_root: Path,
) -> list[GcAction]:
    actions: list[GcAction] = []
    agent_issues = beads.run_bd_json(
        ["list", "--label", "at:agent"], beads_root=beads_root, cwd=repo_root
    )
    epics = beads.list_epics(beads_root=beads_root, cwd=repo_root, include_closed=True)
    epics_by_id: dict[str, dict[str, object]] = {}
    epics_by_assignee: dict[str, list[dict[str, object]]] = {}
    for epic in epics:
        epic_id = epic.get("id")
        if isinstance(epic_id, str) and epic_id:
            epics_by_id[epic_id] = epic
        assignee = epic.get("assignee")
        if not isinstance(assignee, str):
            continue
        assignee_id = assignee.strip()
        if not assignee_id:
            continue
        epics_by_assignee.setdefault(assignee_id, []).append(epic)

    for issue in agent_issues:
        description = issue.get("description")
        fields = beads.parse_description_fields(description if isinstance(description, str) else "")
        agent_id = fields.get("agent_id") or issue.get("title") or ""
        if not isinstance(agent_id, str) or not agent_id.strip():
            continue
        agent_id = agent_id.strip()
        issue_id = issue.get("id")
        if not isinstance(issue_id, str) or not issue_id:
            continue
        if agent_home.session_pid_from_agent_id(agent_id) is None:
            continue
        if agent_home.is_session_agent_active(agent_id):
            continue
        hook_bead = None
        if issue_id:
            hook_bead = beads.get_agent_hook(issue_id, beads_root=beads_root, cwd=repo_root)
        if not hook_bead:
            hook_bead = fields.get("hook_bead")

        dependent_epics: list[dict[str, object]] = []
        dependent_epic_ids: set[str] = set()
        if isinstance(hook_bead, str) and hook_bead:
            hooked_epic = epics_by_id.get(hook_bead)
            if hooked_epic is not None:
                dependent_epics.append(hooked_epic)
                dependent_epic_ids.add(hook_bead)
        for epic in epics_by_assignee.get(agent_id, []):
            epic_id = epic.get("id")
            if not isinstance(epic_id, str) or not epic_id:
                continue
            if epic_id in dependent_epic_ids:
                continue
            dependent_epics.append(epic)
            dependent_epic_ids.add(epic_id)

        description_text = f"Prune stale session agent bead for {agent_id}"

        def _apply_remove(
            agent: str = agent_id,
            agent_bead_id: str = issue_id,
            has_hook: bool = isinstance(hook_bead, str) and bool(hook_bead),
            epics_to_release: tuple[dict[str, object], ...] = tuple(dependent_epics),
        ) -> None:
            for epic_issue in epics_to_release:
                release_epic(epic_issue, beads_root=beads_root, cwd=repo_root)
            if has_hook:
                beads.clear_agent_hook(agent_bead_id, beads_root=beads_root, cwd=repo_root)
            beads.run_bd_command(
                ["close", agent_bead_id],
                beads_root=beads_root,
                cwd=repo_root,
                allow_failure=True,
            )
            agent_home.cleanup_agent_home_by_id(project_dir, agent)

        actions.append(GcAction(description=description_text, apply=_apply_remove))
    return actions

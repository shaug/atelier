"""Worker epic selection helpers."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable

from .. import lifecycle
from .models_boundary import parse_issue_boundary


def issue_labels(issue: dict[str, object]) -> set[str]:
    return lifecycle.normalized_labels(issue.get("labels"))


def issue_parent_id(issue: dict[str, object]) -> str | None:
    try:
        boundary = parse_issue_boundary(issue, source="worker_selection:issue_parent_id")
    except ValueError:
        return None
    return boundary.parent_id


def issue_type(issue: dict[str, object]) -> object:
    return lifecycle.issue_payload_type(issue)


def evaluate_epic_claimability(issue: dict[str, object]) -> lifecycle.EpicClaimEvaluation:
    return lifecycle.evaluate_epic_claimability(
        status=issue.get("status"),
        labels=issue_labels(issue),
        issue_type=issue_type(issue),
        parent_id=issue_parent_id(issue),
    )


def agent_role(agent_id: object) -> str | None:
    if not isinstance(agent_id, str):
        return None
    parts = [part for part in agent_id.split("/") if part]
    if len(parts) >= 2 and parts[0] == "atelier":
        return parts[1].strip().lower() or None
    if parts:
        value = parts[0].strip().lower()
        return value or None
    return None


def is_planner_agent_id(agent_id: object) -> bool:
    return agent_role(agent_id) == "planner"


def has_planner_executable_assignee(issue: dict[str, object]) -> bool:
    evaluation = evaluate_epic_claimability(issue)
    if not evaluation.role.is_epic or not evaluation.claimable:
        return False
    assignee = issue.get("assignee")
    return is_planner_agent_id(assignee)


def has_executable_identity(issue: dict[str, object]) -> bool:
    """Return whether an issue is top-level executable work identity."""
    return evaluate_epic_claimability(issue).role.is_epic


def planner_owned_executable_issues(issues: list[dict[str, object]]) -> list[dict[str, object]]:
    return [issue for issue in issues if has_planner_executable_assignee(issue)]


def is_eligible_status(status: object, *, allow_hooked: bool) -> bool:
    return lifecycle.is_eligible_epic_status(status, allow_hooked=allow_hooked)


def filter_epics(
    issues: list[dict[str, object]],
    *,
    assignee: str | None = None,
    require_unassigned: bool = False,
    allow_hooked: bool = False,
    skip_draft: bool = True,
) -> list[dict[str, object]]:
    """Filter epics according to assignee and eligible status."""
    filtered: list[dict[str, object]] = []
    for issue in issues:
        evaluation = evaluate_epic_claimability(issue)
        if not evaluation.role.is_epic:
            continue
        status = issue.get("status")
        if not is_eligible_status(status, allow_hooked=allow_hooked):
            continue
        if skip_draft and evaluation.status == "deferred":
            continue
        if not evaluation.claimable:
            continue
        if has_planner_executable_assignee(issue):
            continue
        issue_assignee = issue.get("assignee")
        if assignee is not None:
            if issue_assignee != assignee:
                continue
        elif require_unassigned and issue_assignee:
            continue
        filtered.append(issue)
    return filtered


def parse_issue_time(value: object) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


def sort_by_created_at(
    issues: list[dict[str, object]], *, newest: bool = False
) -> list[dict[str, object]]:
    sentinel = dt.datetime.max.replace(tzinfo=dt.timezone.utc)
    return sorted(
        issues,
        key=lambda issue: parse_issue_time(issue.get("created_at")) or sentinel,
        reverse=newest,
    )


def sort_by_recency(issues: list[dict[str, object]]) -> list[dict[str, object]]:
    sentinel = dt.datetime.min.replace(tzinfo=dt.timezone.utc)

    def key(issue: dict[str, object]) -> dt.datetime:
        updated = parse_issue_time(issue.get("updated_at"))
        if updated:
            return updated
        created = parse_issue_time(issue.get("created_at"))
        if created:
            return created
        return sentinel

    return sorted(issues, key=key, reverse=True)


def agent_family_id(agent_id: str) -> str:
    parts = [part for part in str(agent_id).split("/") if part]
    if len(parts) >= 3 and parts[0] == "atelier":
        return "/".join(parts[:3])
    return str(agent_id)


def stale_family_assigned_epics(
    issues: list[dict[str, object]],
    *,
    agent_id: str,
    is_session_active: Callable[[str], bool],
) -> list[dict[str, object]]:
    candidates: list[dict[str, object]] = []
    for issue in issues:
        evaluation = evaluate_epic_claimability(issue)
        if not evaluation.role.is_epic or not evaluation.claimable:
            continue
        if not is_eligible_status(issue.get("status"), allow_hooked=True):
            continue
        if has_planner_executable_assignee(issue):
            continue
        assignee = issue.get("assignee")
        if not isinstance(assignee, str) or not assignee or assignee == agent_id:
            continue
        if is_session_active(assignee):
            continue
        candidates.append(issue)
    return sort_by_created_at(candidates)


def select_epic_from_ready_changesets(
    *,
    issues: list[dict[str, object]],
    ready_changesets: list[dict[str, object]],
    is_actionable: Callable[[str], bool],
) -> str | None:
    """Pick actionable epic (or standalone changeset) from global ready work."""
    known_epics: dict[str, dict[str, object]] = {
        str(issue_id): issue for issue in issues if (issue_id := issue.get("id")) is not None
    }
    for changeset in sort_by_created_at(ready_changesets):
        issue_id = changeset.get("id")
        if not isinstance(issue_id, str) or not issue_id:
            continue
        candidate = issue_id
        parent_id = issue_parent_id(changeset)
        if parent_id and parent_id in known_epics:
            candidate = parent_id
        elif "." in issue_id:
            # Compatibility fallback for legacy dotted child identifiers.
            maybe_epic = issue_id.split(".", 1)[0]
            if maybe_epic in known_epics:
                candidate = maybe_epic
        candidate_issue = known_epics.get(candidate)
        source_issue = candidate_issue if candidate_issue is not None else changeset
        evaluation = evaluate_epic_claimability(source_issue)
        if not evaluation.claimable or not evaluation.role.is_epic:
            continue
        if not is_eligible_status(source_issue.get("status"), allow_hooked=False):
            continue
        if has_planner_executable_assignee(source_issue):
            continue
        assignee = source_issue.get("assignee")
        if isinstance(assignee, str) and assignee.strip():
            continue
        if is_actionable(candidate):
            return candidate
    return None


def select_epic_prompt(
    issues: list[dict[str, object]],
    *,
    agent_id: str,
    is_actionable: Callable[[str], bool],
    extract_root_branch: Callable[[dict[str, object]], str | None],
    select_fn: Callable[[str, list[str]], str],
    assume_yes: bool = False,
) -> str | None:
    """Select an epic using prompt-mode semantics."""
    epics = filter_epics(issues, require_unassigned=True, allow_hooked=False, skip_draft=True)
    resume = filter_epics(issues, assignee=agent_id, allow_hooked=True, skip_draft=True)
    if not epics and not resume:
        return None
    choices: dict[str, str] = {}
    for issue in epics:
        issue_id = issue.get("id") or ""
        if not issue_id or not is_actionable(str(issue_id)):
            continue
        status = issue.get("status") or "unknown"
        title = issue.get("title") or ""
        root_branch_value = extract_root_branch(issue) or "unset"
        label = f"available | {issue_id} [{status}] {root_branch_value} {title}"
        choices[label] = str(issue_id)
    resume = sort_by_recency(resume)
    for issue in resume:
        issue_id = issue.get("id") or ""
        if not issue_id or not is_actionable(str(issue_id)):
            continue
        status = issue.get("status") or "unknown"
        title = issue.get("title") or ""
        root_branch_value = extract_root_branch(issue) or "unset"
        label = f"resume | {issue_id} [{status}] {root_branch_value} {title}"
        choices[label] = str(issue_id)
    if not choices:
        return None
    labels = list(choices.keys())
    if assume_yes:
        return choices[labels[0]]
    selected = select_fn("Epic to work on", labels)
    return choices[selected]


def select_epic_auto(
    issues: list[dict[str, object]],
    *,
    agent_id: str,
    is_actionable: Callable[[str], bool],
) -> str | None:
    """Select an epic using auto-mode semantics."""
    ready = filter_epics(issues, require_unassigned=True, allow_hooked=False, skip_draft=True)
    if ready:
        ready = sort_by_created_at(ready)
        for issue in ready:
            issue_id = issue.get("id") or ""
            if issue_id and is_actionable(str(issue_id)):
                return str(issue_id)
    unfinished = filter_epics(issues, assignee=agent_id, allow_hooked=True, skip_draft=True)
    if unfinished:
        unfinished = sort_by_created_at(unfinished)
        for issue in unfinished:
            issue_id = issue.get("id") or ""
            if issue_id and is_actionable(str(issue_id)):
                return str(issue_id)
    return None

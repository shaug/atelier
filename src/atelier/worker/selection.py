"""Worker epic selection helpers."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable


def is_eligible_status(status: str, *, allow_hooked: bool) -> bool:
    normalized = status.strip().lower()
    if normalized in {"open", "ready", "in_progress"}:
        return True
    if allow_hooked and normalized == "hooked":
        return True
    return False


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
        status = str(issue.get("status") or "")
        if not is_eligible_status(status, allow_hooked=allow_hooked):
            continue
        if skip_draft:
            labels = issue.get("labels")
            if isinstance(labels, list) and "at:draft" in {
                str(label) for label in labels if label is not None
            }:
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
    epics = filter_epics(
        issues, require_unassigned=True, allow_hooked=False, skip_draft=True
    )
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
    ready = filter_epics(
        issues, require_unassigned=True, allow_hooked=False, skip_draft=True
    )
    if ready:
        ready = sort_by_created_at(ready)
        for issue in ready:
            issue_id = issue.get("id") or ""
            if issue_id and is_actionable(str(issue_id)):
                return str(issue_id)
    unfinished = filter_epics(
        issues, assignee=agent_id, allow_hooked=True, skip_draft=True
    )
    if unfinished:
        unfinished = sort_by_created_at(unfinished)
        for issue in unfinished:
            issue_id = issue.get("id") or ""
            if issue_id and is_actionable(str(issue_id)):
                return str(issue_id)
    return None

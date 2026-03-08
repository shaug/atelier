"""Planner-facing helpers for issue owner versus assignee checks."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from . import lifecycle
from .worker.selection import agent_role


@dataclass(frozen=True)
class IssueOwnershipSummary:
    """Structured owner-versus-assignee summary for planner decisions."""

    issue_id: str
    title: str
    status: str
    work_record_kind: str
    owner_metadata: str | None
    assignee: str | None
    assignee_role: str | None
    execution_policy_key: str
    policy_decision: str

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable payload for deterministic script output.

        Returns:
            Plain dict form of the summary dataclass.
        """

        return asdict(self)


def summarize_issue_ownership(issue: Mapping[str, object]) -> IssueOwnershipSummary:
    """Build a planner-facing ownership summary for one Beads issue.

    Args:
        issue: Raw Beads issue payload.

    Returns:
        Structured summary that treats ``assignee`` as the execution-policy key
        and ``owner`` as metadata only.
    """

    issue_id = _clean_text(issue.get("id")) or "(unknown)"
    title = _clean_text(issue.get("title")) or "(untitled)"
    status = lifecycle.canonical_lifecycle_status(issue.get("status")) or (
        _clean_text(issue.get("status")) or "unknown"
    )
    labels = lifecycle.normalized_labels(issue.get("labels"))
    issue_type = lifecycle.issue_payload_type(dict(issue))
    parent_id = _parent_id(issue)
    is_work = lifecycle.is_work_issue(labels=labels, issue_type=issue_type)
    record_kind = _work_record_kind(is_work=is_work, parent_id=parent_id)
    owner = _clean_text(issue.get("owner"))
    assignee = _clean_text(issue.get("assignee"))
    assignee_runtime_role = agent_role(assignee)
    policy_decision = _policy_decision(
        is_work=is_work,
        status=status,
        assignee=assignee,
        assignee_role=assignee_runtime_role,
    )
    return IssueOwnershipSummary(
        issue_id=issue_id,
        title=title,
        status=status,
        work_record_kind=record_kind,
        owner_metadata=owner,
        assignee=assignee,
        assignee_role=assignee_runtime_role,
        execution_policy_key="assignee",
        policy_decision=policy_decision,
    )


def render_issue_ownership(summary: IssueOwnershipSummary) -> str:
    """Render a stable planner-facing owner-versus-assignee summary.

    Args:
        summary: Structured issue ownership summary.

    Returns:
        Deterministic plain-text report suitable for skill output.
    """

    owner = summary.owner_metadata or "unset"
    assignee = summary.assignee or "unassigned"
    assignee_role = summary.assignee_role or "none"
    lines = [
        "Issue ownership check:",
        f"- {summary.issue_id} [{summary.status}] {summary.title}",
        f"- work record: {summary.work_record_kind}",
        f"- execution policy key: {summary.execution_policy_key}",
        (f"- owner metadata: {owner} (metadata only; never use this as executable ownership)"),
        f"- assignee state: {assignee} (role: {assignee_role})",
        f"- decision: {summary.policy_decision}",
    ]
    return "\n".join(lines)


def _clean_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _parent_id(issue: Mapping[str, object]) -> str | None:
    parent = issue.get("parent_id")
    if parent is None:
        parent = issue.get("parent")
    if isinstance(parent, dict):
        return _clean_text(parent.get("id"))
    return _clean_text(parent)


def _work_record_kind(*, is_work: bool, parent_id: str | None) -> str:
    if not is_work:
        return "non-work record"
    if parent_id is None:
        return "top-level work bead (epic)"
    return "child work bead"


def _policy_decision(
    *,
    is_work: bool,
    status: str,
    assignee: str | None,
    assignee_role: str | None,
) -> str:
    if not is_work:
        return "not an executable work-bead policy target; owner stays metadata only"
    if status == "closed":
        return "closed work; use assignee history if needed, never owner metadata"
    if status == "deferred":
        return (
            "deferred work has no active execution owner; if promoted, check "
            "assignee rather than owner metadata"
        )
    if assignee_role == "planner" and assignee:
        return (
            "policy violation: executable work is assigned to planner "
            f"{assignee}; planners must not hold assignee ownership"
        )
    if assignee is None:
        return "executable ownership is currently unassigned; owner metadata does not fill this in"
    return f"executable ownership is assigned via assignee {assignee}; ignore owner metadata"

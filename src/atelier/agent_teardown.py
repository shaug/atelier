"""Deterministic teardown helpers for runtime-owned agent Beads state."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from . import beads, lifecycle


def _clean_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized or normalized.lower() == "null":
        return None
    return normalized


@dataclass(frozen=True)
class AgentTeardownResult:
    """Summarize a best-effort runtime teardown attempt."""

    agent_id: str | None
    agent_bead_id: str | None
    target_epic_id: str | None
    released_epic: bool
    hook_cleared: bool
    agent_closed: bool


def _read_agent_hook(
    *,
    agent_bead_id: str,
    beads_root: Path,
    repo_root: Path,
) -> tuple[bool, str | None]:
    """Read the current agent hook.

    Returns whether the read was definitive.
    """
    try:
        hook = beads.get_agent_hook(
            agent_bead_id,
            beads_root=beads_root,
            cwd=repo_root,
        )
    except SystemExit:
        return False, None
    return True, _clean_text(hook)


def _is_epic_assignment_released(
    *,
    epic_id: str,
    beads_root: Path,
    repo_root: Path,
) -> bool:
    """Return whether an epic no longer has assignee/hooked ownership state."""
    try:
        issues = beads.run_bd_json(
            ["show", epic_id],
            beads_root=beads_root,
            cwd=repo_root,
        )
    except SystemExit:
        return False
    if not issues:
        return False

    issue = issues[0]
    assignee = _clean_text(issue.get("assignee"))
    raw_labels = issue.get("labels")
    labels = (
        {label for label in raw_labels if isinstance(label, str)}
        if isinstance(raw_labels, list)
        else set()
    )
    hooked = beads.has_issue_label(labels, "hooked", beads_root=beads_root)
    return assignee is None and not hooked


def _issue_parent_id(issue: dict[str, object]) -> str | None:
    """Return normalized parent id from a Beads issue payload."""
    try:
        boundary = beads.parse_issue_boundary(issue, source="agent_teardown:issue_parent_id")
    except ValueError:
        return None
    return _clean_text(boundary.parent_id)


def _has_active_epic_ownership(
    *,
    agent_id: str,
    beads_root: Path,
    repo_root: Path,
) -> bool | None:
    """Return whether the agent still owns non-closed top-level work.

    Returns:
        ``True`` when at least one non-closed top-level work bead is still
        assigned to the runtime agent, ``False`` when none are found, and
        ``None`` when ownership cannot be verified.
    """
    try:
        assigned_issues = beads.run_bd_json(
            ["list", "--assignee", agent_id, "--all", "--limit", "0"],
            beads_root=beads_root,
            cwd=repo_root,
        )
    except SystemExit:
        return None

    for issue in assigned_issues:
        if not isinstance(issue, dict):
            continue
        if _clean_text(issue.get("assignee")) != agent_id:
            continue
        if lifecycle.canonical_lifecycle_status(issue.get("status")) == "closed":
            continue
        labels = lifecycle.normalized_labels(issue.get("labels"))
        role = lifecycle.infer_work_role(
            labels=labels,
            issue_type=lifecycle.issue_payload_type(issue),
            parent_id=_issue_parent_id(issue),
            has_work_children=False,
        )
        if role.is_work and role.is_epic:
            return True
    return False


def teardown_agent_runtime(
    *,
    beads_root: Path,
    repo_root: Path,
    agent_id: str | None = None,
    agent_bead_id: str | None = None,
    expected_epic_id: str | None = None,
    close_agent_bead: bool,
) -> AgentTeardownResult:
    """Release runtime-owned Beads hook/claim state for one agent session.

    Args:
        beads_root: Project Beads directory.
        repo_root: Repository root used for ``bd`` commands.
        agent_id: Optional explicit runtime agent identity.
        agent_bead_id: Optional explicit agent bead id.
        expected_epic_id: Optional expected hook target used as a CAS guard.
        close_agent_bead: Whether to close the agent bead after hook/claim
            cleanup.

    Returns:
        ``AgentTeardownResult`` describing observed teardown effects. This
        function is intentionally fail-closed and swallows command failures so
        duplicate or concurrent teardown attempts do not fail hard.
    """
    resolved_agent_id = _clean_text(agent_id) or _clean_text(os.environ.get("ATELIER_AGENT_ID"))
    resolved_agent_bead_id = _clean_text(agent_bead_id) or _clean_text(
        os.environ.get("ATELIER_AGENT_BEAD_ID")
    )
    if resolved_agent_bead_id is None and resolved_agent_id is not None:
        try:
            existing = beads.find_agent_bead(
                resolved_agent_id,
                beads_root=beads_root,
                cwd=repo_root,
            )
        except SystemExit:
            existing = None
        resolved_agent_bead_id = _clean_text(existing.get("id")) if existing else None

    expected_hook = _clean_text(expected_epic_id) or _clean_text(os.environ.get("ATELIER_EPIC_ID"))
    if resolved_agent_bead_id is None:
        return AgentTeardownResult(
            agent_id=resolved_agent_id,
            agent_bead_id=None,
            target_epic_id=expected_hook,
            released_epic=False,
            hook_cleared=False,
            agent_closed=False,
        )

    _, current_hook = _read_agent_hook(
        agent_bead_id=resolved_agent_bead_id,
        beads_root=beads_root,
        repo_root=repo_root,
    )
    target_epic = expected_hook or _clean_text(current_hook)

    released_epic = False
    epic_release_confirmed = False
    if target_epic:
        if resolved_agent_id:
            try:
                released_epic = beads.release_epic_assignment(
                    target_epic,
                    beads_root=beads_root,
                    cwd=repo_root,
                    expected_assignee=resolved_agent_id,
                    expected_hooked=None,
                )
            except SystemExit:
                released_epic = False
        if released_epic:
            epic_release_confirmed = True
        else:
            # Fail closed when release cannot be confirmed.
            epic_release_confirmed = _is_epic_assignment_released(
                epic_id=target_epic,
                beads_root=beads_root,
                repo_root=repo_root,
            )
            released_epic = epic_release_confirmed
        try:
            beads.clear_agent_hook(
                resolved_agent_bead_id,
                beads_root=beads_root,
                cwd=repo_root,
                expected_hook=target_epic,
            )
        except SystemExit:
            pass
    elif resolved_agent_id:
        has_active_ownership = _has_active_epic_ownership(
            agent_id=resolved_agent_id,
            beads_root=beads_root,
            repo_root=repo_root,
        )
        epic_release_confirmed = has_active_ownership is False

    hook_known_after_cleanup, remaining_hook = _read_agent_hook(
        agent_bead_id=resolved_agent_bead_id,
        beads_root=beads_root,
        repo_root=repo_root,
    )
    hook_cleared = hook_known_after_cleanup and remaining_hook is None

    epic_release_verified_for_close = epic_release_confirmed
    if close_agent_bead and hook_cleared and target_epic and epic_release_confirmed:
        # Re-verify right before close so we do not hide a stale epic claim.
        epic_release_verified_for_close = _is_epic_assignment_released(
            epic_id=target_epic,
            beads_root=beads_root,
            repo_root=repo_root,
        )
        released_epic = epic_release_verified_for_close

    agent_closed = False
    if close_agent_bead and hook_cleared and epic_release_verified_for_close:
        close_result = None
        try:
            close_result = beads.close_issue(
                resolved_agent_bead_id,
                beads_root=beads_root,
                cwd=repo_root,
                allow_failure=True,
            )
        except (SystemExit, ValueError):
            close_result = None
        if close_result is not None and close_result.returncode == 0:
            agent_closed = True
        if not agent_closed:
            try:
                issues = beads.run_bd_json(
                    ["show", resolved_agent_bead_id],
                    beads_root=beads_root,
                    cwd=repo_root,
                )
            except SystemExit:
                issues = []
            if issues:
                agent_closed = (
                    lifecycle.canonical_lifecycle_status(issues[0].get("status")) == "closed"
                )

    return AgentTeardownResult(
        agent_id=resolved_agent_id,
        agent_bead_id=resolved_agent_bead_id,
        target_epic_id=target_epic,
        released_epic=released_epic,
        hook_cleared=hook_cleared,
        agent_closed=agent_closed,
    )


__all__ = ["AgentTeardownResult", "teardown_agent_runtime"]

"""Read-only classification for stale terminal PR lifecycle drift."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .. import changeset_fields, git, lifecycle, prs

Issue = dict[str, object]

_NON_TERMINAL_STATUSES = frozenset({"open", "blocked", "in_progress"})
_TERMINAL_PR_STATES = frozenset({"merged", "closed"})


@dataclass(frozen=True)
class StaleTerminalPrLifecycleClassification:
    """Classification result for stale terminal PR lifecycle evidence."""

    kind: str
    reason: str
    canonical_status: str | None
    stored_pr_state: str | None
    live_pr_state: str | None = None
    stale_fields: tuple[str, ...] = ()
    detail: str | None = None

    @property
    def is_candidate(self) -> bool:
        """Return whether the issue is a stale terminal lifecycle candidate."""
        return self.kind == "candidate"

    @property
    def is_anomaly(self) -> bool:
        """Return whether the classification represents ambiguous evidence."""
        return self.kind == "anomaly"


def _classification(
    *,
    kind: str,
    reason: str,
    canonical_status: str | None,
    stored_pr_state: str | None,
    live_pr_state: str | None = None,
    stale_fields: tuple[str, ...] = (),
    detail: str | None = None,
) -> StaleTerminalPrLifecycleClassification:
    return StaleTerminalPrLifecycleClassification(
        kind=kind,
        reason=reason,
        canonical_status=canonical_status,
        stored_pr_state=stored_pr_state,
        live_pr_state=live_pr_state,
        stale_fields=stale_fields,
        detail=detail,
    )


def classify_stale_terminal_pr_lifecycle(
    issue: Issue,
    *,
    repo_slug: str | None,
    repo_root: Path,
    branch_pr: bool,
    git_path: str | None,
) -> StaleTerminalPrLifecycleClassification:
    """Classify stale terminal PR lifecycle drift for a non-terminal changeset.

    Args:
        issue: Changeset bead payload under evaluation.
        repo_slug: Optional GitHub ``owner/repo`` slug used for PR lookups.
        repo_root: Repository root used for git branch checks.
        branch_pr: Whether the project uses PR-mediated publishing.
        git_path: Optional git executable override.

    Returns:
        Classification describing whether the issue is a stale terminal PR
        candidate, an ambiguous anomaly, or an ordinary non-candidate path.
    """
    canonical_status = lifecycle.canonical_lifecycle_status(issue.get("status"))
    stored_pr_state = changeset_fields.review_state(issue)
    if not branch_pr:
        return _classification(
            kind="none",
            reason="non_pr_project",
            canonical_status=canonical_status,
            stored_pr_state=stored_pr_state,
        )
    if canonical_status not in _NON_TERMINAL_STATUSES:
        return _classification(
            kind="none",
            reason=f"status_{canonical_status or 'unknown'}",
            canonical_status=canonical_status,
            stored_pr_state=stored_pr_state,
        )

    work_branch = changeset_fields.work_branch(issue)
    if not work_branch:
        return _classification(
            kind="anomaly",
            reason="missing_work_branch",
            canonical_status=canonical_status,
            stored_pr_state=stored_pr_state,
        )
    if not repo_slug:
        return _classification(
            kind="anomaly",
            reason="missing_repo_slug",
            canonical_status=canonical_status,
            stored_pr_state=stored_pr_state,
        )

    pushed = git.git_ref_exists(repo_root, f"refs/remotes/origin/{work_branch}", git_path=git_path)
    lookup = prs.lookup_github_pr_status(repo_slug, work_branch)
    if lookup.failed:
        lookup = prs.lookup_github_pr_status(repo_slug, work_branch, refresh=True)
    if lookup.failed:
        return _classification(
            kind="anomaly",
            reason="pr_lifecycle_lookup_failed",
            canonical_status=canonical_status,
            stored_pr_state=stored_pr_state,
            detail=lookup.error or "unknown",
        )

    payload = lookup.payload if lookup.found and isinstance(lookup.payload, dict) else None
    review_requested = prs.has_review_requests(payload)
    live_pr_state = prs.lifecycle_state(
        payload,
        pushed=pushed,
        review_requested=review_requested,
    )
    if live_pr_state in lifecycle.ACTIVE_PR_LIFECYCLE_STATES:
        return _classification(
            kind="none",
            reason=f"active_pr_lifecycle_{live_pr_state}",
            canonical_status=canonical_status,
            stored_pr_state=stored_pr_state,
            live_pr_state=live_pr_state,
        )
    if live_pr_state not in _TERMINAL_PR_STATES:
        return _classification(
            kind="none",
            reason="terminal_pr_state_unavailable",
            canonical_status=canonical_status,
            stored_pr_state=stored_pr_state,
            live_pr_state=live_pr_state,
        )

    stale_fields = ["status"]
    if stored_pr_state not in _TERMINAL_PR_STATES or stored_pr_state != live_pr_state:
        stale_fields.append("pr_state")
    return _classification(
        kind="candidate",
        reason=f"terminal_pr_{live_pr_state}",
        canonical_status=canonical_status,
        stored_pr_state=stored_pr_state,
        live_pr_state=live_pr_state,
        stale_fields=tuple(stale_fields),
    )


__all__ = [
    "StaleTerminalPrLifecycleClassification",
    "classify_stale_terminal_pr_lifecycle",
]

"""Shared lifecycle contract helpers for planner and worker execution.

Canonical lifecycle semantics are defined by graph shape plus issue status:

- work-bead identity excludes explicit non-work records (message/agent/policy)
- epic role is inferred from top-level work nodes (no parent)
- changeset role is inferred from leaf work nodes (no work children)
- top-level leaf work nodes are both epic and changeset
- runnable work requires leaf role, active status, and satisfied dependencies
"""

from __future__ import annotations

from dataclasses import dataclass

ACTIVE_REVIEW_STATES = {"draft-pr", "pr-open", "in-review", "approved"}

CANONICAL_LIFECYCLE_STATUSES = {
    "deferred",
    "open",
    "in_progress",
    "blocked",
    "closed",
}
ACTIVE_LIFECYCLE_STATUSES = {"open", "in_progress"}
TERMINAL_CHANGESET_LABELS = {"cs:merged", "cs:abandoned"}
SPECIAL_NON_WORK_LABELS = {"at:message", "at:agent", "at:policy"}
SPECIAL_NON_WORK_TYPES = {"message", "agent", "policy"}
WORK_ISSUE_TYPES = {"epic", "task", "bug", "feature"}

_LEGACY_STATUS_ALIASES = {
    "ready": "open",
    "planned": "deferred",
    "hooked": "in_progress",
    "done": "closed",
}
_LEGACY_LABEL_STATUS_HINTS: tuple[tuple[str, str], ...] = (
    ("cs:merged", "closed"),
    ("cs:abandoned", "closed"),
    ("cs:blocked", "blocked"),
    ("cs:in_progress", "in_progress"),
    ("at:hooked", "in_progress"),
    ("cs:planned", "deferred"),
    ("at:draft", "deferred"),
    ("cs:ready", "open"),
    ("at:ready", "open"),
)


@dataclass(frozen=True)
class WorkRoleInference:
    """Derived work role information from graph shape and identity hints."""

    is_work: bool
    is_epic: bool
    is_changeset: bool
    has_work_children: bool
    parent_id: str | None

    @property
    def is_leaf(self) -> bool:
        """Return whether the node has no work-bead children."""
        return not self.has_work_children


@dataclass(frozen=True)
class RunnableLeafEvaluation:
    """Evaluation result for whether a work bead is runnable now."""

    runnable: bool
    status: str | None
    role: WorkRoleInference
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class EpicClaimEvaluation:
    """Evaluation result for whether a top-level work bead is claimable."""

    claimable: bool
    status: str | None
    role: WorkRoleInference
    reasons: tuple[str, ...]


def _clean_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def normalize_review_state(value: object) -> str | None:
    """Normalize persisted PR review state values.

    Args:
        value: Raw persisted review state.

    Returns:
        Lower-cased review state, or ``None`` when empty/invalid.
    """
    normalized = _clean_text(value)
    if normalized is None:
        return None
    lowered = normalized.lower()
    if lowered == "null":
        return None
    return lowered


def normalized_labels(raw_labels: object) -> set[str]:
    """Normalize issue labels into a comparable set.

    Args:
        raw_labels: Raw issue label payload from Beads.

    Returns:
        Deduplicated, trimmed labels with empty entries removed.
    """
    if not isinstance(raw_labels, list):
        return set()
    normalized: set[str] = set()
    for label in raw_labels:
        cleaned = _clean_text(label)
        if cleaned:
            normalized.add(cleaned)
    return normalized


def issue_payload_type(issue: dict[str, object]) -> object:
    """Return canonical issue type payload with legacy fallback.

    Args:
        issue: Raw issue payload mapping.

    Returns:
        Issue type value from ``issue_type`` when available, otherwise legacy
        ``type``.
    """
    issue_type = issue.get("issue_type")
    if issue_type is not None:
        return issue_type
    return issue.get("type")


def normalize_status_value(status: object) -> str | None:
    """Normalize a raw Beads status into lower-case text.

    Args:
        status: Raw status value from an issue payload.

    Returns:
        Cleaned lower-case status text, or ``None`` when missing.
    """
    cleaned = _clean_text(status)
    if cleaned is None:
        return None
    return cleaned.lower()


def _legacy_status_hint_from_labels(labels: set[str]) -> str | None:
    for label, status in _LEGACY_LABEL_STATUS_HINTS:
        if label in labels:
            return status
    return None


def canonical_lifecycle_status(status: object, *, labels: set[str] | None = None) -> str | None:
    """Resolve canonical lifecycle status with legacy compatibility.

    Args:
        status: Raw issue status.
        labels: Optional normalized labels used for transitional backfill when
            status is missing or legacy-only.

    Returns:
        Canonical lifecycle status (`deferred`, `open`, `in_progress`,
        `blocked`, `closed`) when resolvable. Unknown normalized values are
        returned as-is for diagnostics.
    """
    normalized = normalize_status_value(status)
    if normalized in CANONICAL_LIFECYCLE_STATUSES:
        return normalized
    if normalized in _LEGACY_STATUS_ALIASES:
        return _LEGACY_STATUS_ALIASES[normalized]
    if normalized is None and labels:
        hint = _legacy_status_hint_from_labels(labels)
        if hint is not None:
            return hint
    return normalized


def is_closed_status(status: object, *, labels: set[str] | None = None) -> bool:
    """Return whether status is terminal under canonical lifecycle semantics.

    Args:
        status: Raw issue status.
        labels: Optional labels used for transitional compatibility.

    Returns:
        ``True`` when status resolves to canonical ``closed``.
    """
    return canonical_lifecycle_status(status, labels=labels) == "closed"


def is_special_non_work_issue(*, labels: set[str], issue_type: object) -> bool:
    """Return whether an issue is explicitly non-work by label or type.

    Args:
        labels: Normalized issue labels.
        issue_type: Raw issue type value.

    Returns:
        ``True`` when the issue is explicitly special/non-work.
    """
    if SPECIAL_NON_WORK_LABELS.intersection(labels):
        return True
    issue_type_value = normalize_status_value(issue_type)
    return issue_type_value in SPECIAL_NON_WORK_TYPES


def is_work_issue(*, labels: set[str], issue_type: object) -> bool:
    """Return whether an issue should be treated as executable work.

    Args:
        labels: Normalized issue labels.
        issue_type: Raw issue type value.

    Returns:
        ``True`` when the issue is a work bead for planner/worker execution.
    """
    if is_special_non_work_issue(labels=labels, issue_type=issue_type):
        return False
    if {"at:epic", "at:changeset"}.intersection(labels):
        return True
    issue_type_value = normalize_status_value(issue_type)
    return issue_type_value in WORK_ISSUE_TYPES


def infer_work_role(
    *,
    labels: set[str],
    issue_type: object,
    parent_id: object,
    has_work_children: bool,
) -> WorkRoleInference:
    """Infer epic/changeset role from graph shape and work identity.

    Args:
        labels: Normalized issue labels.
        issue_type: Raw issue type value.
        parent_id: Raw parent issue identifier.
        has_work_children: Whether this node has child work beads.

    Returns:
        Inferred role where top-level work nodes are epics, leaf work nodes are
        changesets, and top-level leaves are both.
    """
    parent = _clean_text(parent_id)
    is_work = is_work_issue(labels=labels, issue_type=issue_type)
    is_epic = is_work and parent is None
    is_changeset = is_work and not has_work_children
    return WorkRoleInference(
        is_work=is_work,
        is_epic=is_epic,
        is_changeset=is_changeset,
        has_work_children=has_work_children,
        parent_id=parent,
    )


def evaluate_runnable_leaf(
    *,
    status: object,
    labels: set[str],
    issue_type: object,
    parent_id: object,
    has_work_children: bool,
    dependencies_satisfied: bool,
) -> RunnableLeafEvaluation:
    """Evaluate whether an issue is runnable as a leaf work item.

    Args:
        status: Raw issue status.
        labels: Normalized issue labels.
        issue_type: Raw issue type value.
        parent_id: Raw parent issue identifier.
        has_work_children: Whether the issue has child work beads.
        dependencies_satisfied: Whether all dependency blockers are terminal.

    Returns:
        Runnable evaluation with canonical status, inferred role, and rejection
        diagnostics.
    """
    role = infer_work_role(
        labels=labels,
        issue_type=issue_type,
        parent_id=parent_id,
        has_work_children=has_work_children,
    )
    canonical_status = canonical_lifecycle_status(status)
    reasons: list[str] = []
    if not role.is_work:
        reasons.append("not-work-bead")
    if not role.is_changeset:
        reasons.append("not-leaf-work")
    if canonical_status not in ACTIVE_LIFECYCLE_STATUSES:
        reasons.append(f"status={canonical_status or 'missing'}")
    if not dependencies_satisfied:
        reasons.append("dependencies-unsatisfied")
    return RunnableLeafEvaluation(
        runnable=not reasons,
        status=canonical_status,
        role=role,
        reasons=tuple(reasons),
    )


def evaluate_epic_claimability(
    *,
    status: object,
    labels: set[str],
    issue_type: object,
    parent_id: object,
) -> EpicClaimEvaluation:
    """Evaluate whether an issue is claimable as top-level executable work.

    Args:
        status: Raw issue status.
        labels: Normalized issue labels.
        issue_type: Raw issue type value.
        parent_id: Raw parent issue identifier.

    Returns:
        Claimability evaluation with canonical status and diagnostics.
    """
    role = infer_work_role(
        labels=labels,
        issue_type=issue_type,
        parent_id=parent_id,
        has_work_children=False,
    )
    canonical_status = canonical_lifecycle_status(status)
    reasons: list[str] = []
    if not role.is_work:
        reasons.append("not-work-bead")
    if not role.is_epic:
        reasons.append("not-top-level-work")
    if canonical_status not in ACTIVE_LIFECYCLE_STATUSES:
        reasons.append(f"status={canonical_status or 'missing'}")
    return EpicClaimEvaluation(
        claimable=not reasons,
        status=canonical_status,
        role=role,
        reasons=tuple(reasons),
    )


def is_eligible_epic_status(status: object, *, allow_hooked: bool) -> bool:
    """Return whether an epic status is eligible for worker selection.

    Args:
        status: Raw issue status value.
        allow_hooked: Whether legacy ``hooked`` status should be accepted.

    Returns:
        ``True`` when the status is active/open for epic selection.
    """
    normalized = normalize_status_value(status)
    if normalized is None:
        return True
    if normalized == "hooked" and not allow_hooked:
        return False
    canonical_status = canonical_lifecycle_status(status)
    return canonical_status in ACTIVE_LIFECYCLE_STATUSES


def is_active_root_branch_owner(*, status: object, labels: set[str]) -> bool:
    """Return whether root-branch ownership should be treated as active.

    Args:
        status: Raw issue status value.
        labels: Normalized issue labels.

    Returns:
        ``True`` when branch ownership should still block reuse.
    """
    canonical_status = canonical_lifecycle_status(status)
    if canonical_status == "closed":
        return False
    if canonical_status in {"deferred", "open", "in_progress", "blocked"}:
        return True
    return False


def is_changeset_in_progress(status: object, labels: set[str]) -> bool:
    """Return whether a changeset should be treated as in progress.

    Args:
        status: Raw issue status.
        labels: Normalized issue labels.

    Returns:
        ``True`` when canonical lifecycle status is ``in_progress``.
    """
    return canonical_lifecycle_status(status) == "in_progress"


def is_changeset_ready(status: object, labels: set[str]) -> bool:
    """Return whether a changeset is runnable in legacy-compatible mode.

    Args:
        status: Raw issue status.
        labels: Normalized issue labels.

    Returns:
        ``True`` when the issue is a changeset with active canonical status.
    """
    if "at:changeset" not in labels:
        return False
    canonical_status = canonical_lifecycle_status(status)
    return canonical_status in ACTIVE_LIFECYCLE_STATUSES


def is_changeset_in_review_candidate(
    *,
    labels: set[str],
    status: object,
    live_state: str | None = None,
    stored_review_state: str | None = None,
) -> bool:
    """Return whether review feedback should be checked for a changeset.

    Args:
        labels: Normalized issue labels.
        status: Raw issue status.
        live_state: Optional live PR lifecycle state.
        stored_review_state: Optional stored review state fallback.

    Returns:
        ``True`` when the changeset is active and has an eligible review state.
    """
    if "at:changeset" not in labels:
        return False
    if is_closed_status(status):
        return False
    if live_state is not None:
        return live_state in ACTIVE_REVIEW_STATES
    return normalize_review_state(stored_review_state) in ACTIVE_REVIEW_STATES

"""Shared lifecycle contract helpers for planner and worker execution.

Canonical lifecycle semantics are defined by graph shape plus issue status:

- work-bead identity excludes explicit non-work records (message/agent/policy)
- epic role is inferred from top-level work nodes (no parent)
- changeset role is inferred from leaf work nodes (no work children)
- top-level leaf work nodes are both epic and changeset
- runnable work requires leaf role, active status, and satisfied dependencies
- executable work is expected to produce committable artifacts; planner-owned
  cleanup/orchestration should not be modeled as worker-executable work
"""

from __future__ import annotations

from dataclasses import dataclass

ACTIVE_REVIEW_STATES = {"draft-pr", "pr-open", "in-review", "approved"}
ACTIVE_PR_LIFECYCLE_STATES = {"pushed", *ACTIVE_REVIEW_STATES}
INTEGRATED_REVIEW_STATES = {"merged"}
TERMINAL_UNINTEGRATED_REVIEW_STATES = {"closed"}

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


def is_active_pr_lifecycle_state(review_state: object) -> bool:
    """Return whether a PR lifecycle state is still actively in flight.

    Args:
        review_state: Raw review lifecycle state.

    Returns:
        ``True`` when the lifecycle state indicates ongoing publish/review work.
    """
    normalized = normalize_review_state(review_state)
    return normalized in ACTIVE_PR_LIFECYCLE_STATES


def is_integrated_review_state(review_state: object) -> bool:
    """Return whether a review state carries integration evidence.

    Args:
        review_state: Raw review lifecycle state.

    Returns:
        ``True`` when the state proves the dependency merged/integrated.
    """
    normalized = normalize_review_state(review_state)
    return normalized in INTEGRATED_REVIEW_STATES


def is_terminal_review_without_integration(review_state: object) -> bool:
    """Return whether a review state is terminal but not integrated.

    Args:
        review_state: Raw review lifecycle state.

    Returns:
        ``True`` when the state is terminal closed-without-merge evidence.
    """
    normalized = normalize_review_state(review_state)
    return normalized in TERMINAL_UNINTEGRATED_REVIEW_STATES


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


def canonical_lifecycle_status(status: object) -> str | None:
    """Resolve canonical lifecycle status.

    Args:
        status: Raw issue status.

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
    return normalized


def is_closed_status(status: object) -> bool:
    """Return whether status is terminal under canonical lifecycle semantics.

    Args:
        status: Raw issue status.

    Returns:
        ``True`` when status resolves to canonical ``closed``.
    """
    return canonical_lifecycle_status(status) == "closed"


def dependency_issue_satisfied(
    *,
    status: object,
    labels: set[str],
    require_integrated: bool,
    review_state: object | None = None,
    issue_type: object | None = None,
    has_work_children: bool | None = None,
) -> bool:
    """Return whether a dependency issue satisfies lifecycle gating.

    Args:
        status: Raw dependency issue status.
        labels: Normalized dependency issue labels.
        require_integrated: Whether dependencies must carry integration evidence
            (sequential contract).
        review_state: Optional dependency review lifecycle state.
        issue_type: Optional dependency issue type for unlabeled role hints.
        has_work_children: Optional graph-shape evidence for whether the
            dependency has child work items. When provided, leaf shape is
            authoritative for changeset role inference.

    Returns:
        ``True`` when the dependency is acceptable under the selected contract.
    """
    if not is_closed_status(status):
        return False
    if not require_integrated:
        return True
    issue_type_value = normalize_status_value(issue_type)
    if has_work_children is None:
        is_changeset = "at:changeset" in labels or bool(
            TERMINAL_CHANGESET_LABELS.intersection(labels)
        )
        if not is_changeset and issue_type_value in WORK_ISSUE_TYPES and "at:epic" not in labels:
            is_changeset = True
    else:
        is_changeset = False
        if not has_work_children:
            is_changeset = "at:changeset" in labels or bool(
                TERMINAL_CHANGESET_LABELS.intersection(labels)
            )
            if not is_changeset:
                is_changeset = is_work_issue(labels=labels, issue_type=issue_type_value)
    if not is_changeset:
        return True
    if "cs:merged" in labels:
        return True
    return is_integrated_review_state(review_state)


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

    Work identity is inferred from at:epic or issue type. Changeset role is
    inferred from graph (leaf work bead). Planner-owned cleanup-only operations
    should be modeled outside executable work-bead flows.

    Args:
        labels: Normalized issue labels. issue_type: Raw issue type value.

    Returns:
        ``True`` when the issue is a work bead for planner/worker execution.
    """
    if is_special_non_work_issue(labels=labels, issue_type=issue_type):
        return False
    if "at:epic" in labels:
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


def is_executable_epic_identity(
    *,
    labels: set[str],
    issue_type: object,
    parent_id: object,
) -> bool:
    """Return whether an issue has executable epic identity.

    Epic execution identity is strict: top-level work beads must also carry the
    ``at:epic`` label.

    Args:
        labels: Normalized issue labels.
        issue_type: Raw issue type value.
        parent_id: Raw parent issue identifier.

    Returns:
        ``True`` when the issue is top-level work and includes ``at:epic``.
    """
    role = infer_work_role(
        labels=labels,
        issue_type=issue_type,
        parent_id=parent_id,
        has_work_children=False,
    )
    return role.is_epic and "at:epic" in labels


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
    if "at:epic" not in labels:
        reasons.append("missing-at:epic-label")
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


def is_changeset_ready(
    status: object,
    labels: set[str],
    *,
    has_work_children: bool | None = None,
    issue_type: object = None,
    parent_id: object = None,
) -> bool:
    """Return whether a changeset is runnable based on graph role and status.

    Changeset role is inferred from graph (leaf work bead),. When
    has_work_children is unknown (None), fails closed (returns False).

    Args:
        status: Raw issue status. labels: Normalized issue labels.
        has_work_children: Whether the issue has child work beads. Required for
            graph inference; when None (unknown), returns False; when True,
            returns False (not a leaf).
        issue_type: Raw issue type (for work identity when has_work_children
            provided).
        parent_id: Raw parent id (for work identity when has_work_children
            provided).

    Returns:
        ``True`` when the issue is a leaf work bead with active canonical
        status.
    """
    if has_work_children is None:
        return False
    if has_work_children:
        return False
    role = infer_work_role(
        labels=labels,
        issue_type=issue_type or "task",
        parent_id=parent_id,
        has_work_children=False,
    )
    if not role.is_changeset:
        return False
    canonical_status = canonical_lifecycle_status(status)
    return canonical_status in ACTIVE_LIFECYCLE_STATUSES


def is_changeset_in_review_candidate(
    *,
    labels: set[str],
    status: object,
    live_state: str | None = None,
    stored_review_state: str | None = None,
    has_work_children: bool | None = None,
    issue_type: object = None,
    parent_id: object = None,
) -> bool:
    """Return whether review feedback should be checked for a changeset.

    Changeset role is inferred from graph (leaf work bead) When
    has_work_children is unknown, fails closed (returns False).

    Args:
        labels: Normalized issue labels.
        status: Raw issue status.
        live_state: Optional live PR lifecycle state.
        stored_review_state: Optional stored review state fallback.
        has_work_children: Whether the issue has child work beads.
        issue_type: Raw issue type (for work identity).
        parent_id: Raw parent id (for work identity).

    Returns:
        ``True`` when the changeset is active and has an eligible review state.
    """
    if has_work_children is None:
        return False
    if has_work_children:
        return False
    role = infer_work_role(
        labels=labels,
        issue_type=issue_type or "task",
        parent_id=parent_id,
        has_work_children=False,
    )
    if not role.is_changeset:
        return False
    if is_closed_status(status):
        return False
    if live_state is not None:
        return live_state in ACTIVE_REVIEW_STATES
    return normalize_review_state(stored_review_state) in ACTIVE_REVIEW_STATES

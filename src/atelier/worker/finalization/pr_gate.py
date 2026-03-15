"""PR gate helpers used during changeset finalization."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Iterator

from ... import beads, changesets, dependency_lineage, exec, git, lifecycle, prs
from ... import log as atelier_log
from .. import integration as worker_integration
from .. import store_adapter as worker_store
from ..models import FinalizeResult


@dataclass(frozen=True)
class PrGateResult:
    """Typed PR gate result for pushed-without-pr handling."""

    finalize_result: FinalizeResult
    detail: str | None = None


@dataclass(frozen=True)
class PrCreationDecision:
    """Decision for whether a PR may be created under sequential policy."""

    parent_state: str | None
    allow_pr: bool
    reason: str


@dataclass(frozen=True)
class StackIntegrityPreflightResult:
    """Sequential stack-integrity preflight outcome."""

    ok: bool
    reason: str | None = None
    edge: str | None = None
    detail: str | None = None
    remediation: str | None = None
    dependencies_integrated: bool = False


_STACK_INTEGRITY_REMEDIATIONS: dict[str, str] = {
    "dependency-lineage-ambiguous": (
        "Set a single deterministic dependency parent (or explicit "
        "`changeset.parent_branch`) and rerun finalize."
    ),
    "dependency-parent-unresolved": (
        "Ensure dependency changesets exist and publish `changeset.work_branch` "
        "metadata before retrying."
    ),
    "dependency-parent-state-unavailable": (
        "Push the dependency parent branch and verify GitHub PR status lookups for that branch."
    ),
    "dependency-parent-pr-closed": (
        "Reopen or recreate the dependency parent PR, or merge the parent "
        "changeset before retrying."
    ),
    "dependency-parent-pr-missing": (
        "Recreate the missing dependency parent PR for the parent branch, then rerun finalize."
    ),
    "dependency-parent-status-query-failed": (
        "Resolve GitHub status query failures for the dependency parent branch and rerun finalize."
    ),
    "dependency-parent-metadata-reconcile-failed": (
        "Repair parent review metadata and rerun finalize."
    ),
    "dependency-not-integrated": (
        "Wait until every declared dependency shows integrated evidence, then rerun finalize."
    ),
}
_ACTIVE_EPIC_PR_LIFECYCLE_STATES = frozenset(
    {"pushed", "draft-pr", "pr-open", "in-review", "approved"}
)


def _remediation_for_stack_reason(reason: str) -> str:
    return _STACK_INTEGRITY_REMEDIATIONS.get(
        reason,
        "Repair dependency parent lineage metadata and retry finalize.",
    )


def _dependency_edge(
    *,
    issue: dict[str, object],
    parent_id: str | None,
    parent_branch: str | None,
) -> str:
    child_id = str(issue.get("id") or "").strip() or "unknown-changeset"
    resolved_parent = parent_id or "unknown-parent"
    if parent_branch:
        return f"{child_id} -> {resolved_parent} ({parent_branch})"
    return f"{child_id} -> {resolved_parent}"


def _normalize_branch(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned or cleaned.lower() == "null":
        return None
    return cleaned


def _normalize_issue_id(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _is_epic_issue(*, issue: dict[str, object], beads_root: Path) -> bool:
    labels = lifecycle.normalized_labels(issue.get("labels"))
    if beads.has_issue_label(labels, "epic", beads_root=beads_root):
        return True
    issue_type = lifecycle.issue_payload_type(issue)
    return isinstance(issue_type, str) and issue_type.strip().lower() == "epic"


def _resolve_epic_scope_id(
    issue: dict[str, object],
    *,
    repo_root: Path,
    beads_root: Path | None,
) -> str | None:
    if beads_root is None:
        return None
    current_issue = issue
    current_id = _normalize_issue_id(current_issue.get("id"))
    if not current_id:
        return None
    visited: set[str] = set()
    while True:
        if current_id in visited:
            return None
        visited.add(current_id)
        if _is_epic_issue(issue=current_issue, beads_root=beads_root):
            return current_id
        try:
            boundary = beads.parse_issue_boundary(
                current_issue, source="pr_gate:resolve_epic_scope"
            )
        except ValueError:
            return None
        parent_id = _normalize_issue_id(boundary.parent_id)
        if not parent_id:
            return current_id
        try:
            parent_issues = beads.run_bd_json(
                ["show", parent_id],
                beads_root=beads_root,
                cwd=repo_root,
            )
        except Exception as exc:  # pragma: no cover - defensive boundary
            atelier_log.warning(
                f"changeset={current_id} failed to resolve epic scope via {parent_id}: {exc}"
            )
            return parent_id
        if not parent_issues:
            return parent_id
        current_issue = parent_issues[0]
        current_id = parent_id


def _sequential_pr_creation_decision(*, parent_state: str | None) -> PrCreationDecision:
    parent_state_normalized = None
    if isinstance(parent_state, str):
        parent_state_normalized = parent_state.strip().lower() or None

    if parent_state_normalized is None:
        return PrCreationDecision(
            parent_state=None,
            allow_pr=True,
            reason="no-parent",
        )
    if lifecycle.is_integrated_review_state(parent_state_normalized):
        return PrCreationDecision(
            parent_state=parent_state_normalized,
            allow_pr=True,
            reason=f"parent:{parent_state_normalized}",
        )
    return PrCreationDecision(
        parent_state=parent_state_normalized,
        allow_pr=False,
        reason=f"blocked:{parent_state_normalized}",
    )


def _changeset_lifecycle_state(
    issue: dict[str, object],
    *,
    repo_slug: str | None,
    repo_root: Path,
    git_path: str | None,
    lookup_pr_payload: Callable[..., dict[str, object] | None],
) -> str | None:
    description = issue.get("description")
    description_text = description if isinstance(description, str) else ""
    fields = beads.parse_description_fields(description_text)
    work_branch = _normalize_branch(fields.get("changeset.work_branch"))
    if repo_slug and work_branch:
        pushed = git.git_ref_exists(
            repo_root,
            f"refs/remotes/origin/{work_branch}",
            git_path=git_path,
        )
        payload = lookup_pr_payload(repo_slug, work_branch)
        review_requested = prs.has_review_requests(payload)
        state = prs.lifecycle_state(payload, pushed=pushed, review_requested=review_requested)
        if state:
            return state
    review = changesets.parse_review_metadata(description_text)
    return lifecycle.normalize_review_state(review.pr_state)


def _active_epic_sibling_state(
    issue: dict[str, object],
    *,
    repo_slug: str | None,
    repo_root: Path,
    git_path: str | None,
    beads_root: Path | None,
    lookup_pr_payload: Callable[..., dict[str, object] | None],
) -> tuple[str, str] | None:
    if beads_root is None:
        return None
    current_id = _normalize_issue_id(issue.get("id"))
    if not current_id:
        return None
    epic_id = _resolve_epic_scope_id(issue, repo_root=repo_root, beads_root=beads_root)
    if not epic_id:
        return None
    try:
        siblings = beads.list_descendant_changesets(
            epic_id,
            beads_root=beads_root,
            cwd=repo_root,
            include_closed=True,
        )
    except Exception as exc:  # pragma: no cover - defensive boundary
        atelier_log.warning(
            f"changeset={current_id} failed to evaluate sibling PR gate under {epic_id}: {exc}"
        )
        return None
    for sibling in siblings:
        sibling_id = _normalize_issue_id(sibling.get("id"))
        if not sibling_id or sibling_id == current_id:
            continue
        sibling_state = _changeset_lifecycle_state(
            sibling,
            repo_slug=repo_slug,
            repo_root=repo_root,
            git_path=git_path,
            lookup_pr_payload=lookup_pr_payload,
        )
        if sibling_state in _ACTIVE_EPIC_PR_LIFECYCLE_STATES:
            return sibling_id, sibling_state
    return None


def _dependency_integrated(
    dependency_issue: dict[str, object],
    *,
    repo_slug: str | None,
    repo_root: Path,
    git_path: str | None,
    lookup_pr_payload: Callable[..., dict[str, object] | None],
) -> bool:
    integrated, _ = worker_integration.changeset_integration_signal(
        dependency_issue,
        repo_slug=repo_slug,
        repo_root=repo_root,
        lookup_pr_payload=lookup_pr_payload,
        git_path=git_path,
    )
    return integrated


def _dependency_integration_diagnostics(
    dependency_ids: tuple[str, ...],
    *,
    lookup_dependency_issue: Callable[[str], dict[str, object] | None],
    repo_slug: str | None,
    repo_root: Path,
    git_path: str | None,
    lookup_pr_payload: Callable[..., dict[str, object] | None],
) -> tuple[bool, tuple[str, ...]]:
    unresolved: list[str] = []
    for dependency_id in dependency_ids:
        dependency_issue = lookup_dependency_issue(dependency_id)
        if dependency_issue is None:
            unresolved.append(f"{dependency_id}(unavailable)")
            continue
        if _dependency_integrated(
            dependency_issue,
            repo_slug=repo_slug,
            repo_root=repo_root,
            git_path=git_path,
            lookup_pr_payload=lookup_pr_payload,
        ):
            continue
        unresolved.append(dependency_id)
    return not unresolved, tuple(unresolved)


def _dependency_id_from_unresolved(token: str) -> str:
    return token.split("(", 1)[0].strip()


def sequential_stack_integrity_preflight(
    issue: dict[str, object],
    *,
    repo_slug: str | None,
    repo_root: Path,
    git_path: str | None,
    beads_root: Path | None = None,
    lookup_pr_payload: Callable[..., dict[str, object] | None],
    lookup_pr_payload_diagnostic: Callable[..., tuple[dict[str, object] | None, str | None]]
    | None = None,
    lookup_dependency_issue: Callable[[str], dict[str, object] | None] | None = None,
    reconcile_parent_review_state: Callable[..., None] | None = None,
) -> StackIntegrityPreflightResult:
    """Validate sequential parent-child PR integrity for dependency stacks."""
    description = issue.get("description")
    fields = beads.parse_description_fields(description if isinstance(description, str) else "")
    issue_cache: dict[str, dict[str, object] | None] = {}

    def lookup_dependency_issue_local(issue_id: str) -> dict[str, object] | None:
        if issue_id in issue_cache:
            return issue_cache[issue_id]
        dependency_issue = None
        if lookup_dependency_issue is not None:
            dependency_issue = lookup_dependency_issue(issue_id)
        if dependency_issue is None and beads_root is not None:
            issues = beads.run_bd_json(["show", issue_id], beads_root=beads_root, cwd=repo_root)
            dependency_issue = issues[0] if issues else None
        issue_cache[issue_id] = dependency_issue
        return issue_cache[issue_id]

    lineage = dependency_lineage.resolve_parent_lineage(
        issue,
        root_branch=fields.get("changeset.root_branch"),
        lookup_issue=lookup_dependency_issue_local,
    )
    if not lineage.dependency_ids:
        return StackIntegrityPreflightResult(ok=True)

    dependencies_integrated, unresolved_dependency_ids = _dependency_integration_diagnostics(
        lineage.dependency_ids,
        lookup_dependency_issue=lookup_dependency_issue_local,
        repo_slug=repo_slug,
        repo_root=repo_root,
        git_path=git_path,
        lookup_pr_payload=lookup_pr_payload,
    )
    if dependencies_integrated:
        return StackIntegrityPreflightResult(ok=True, dependencies_integrated=True)

    edge = _dependency_edge(
        issue=issue,
        parent_id=lineage.dependency_parent_id,
        parent_branch=lineage.dependency_parent_branch,
    )
    unresolved_dependency_set = {
        _dependency_id_from_unresolved(token) for token in unresolved_dependency_ids
    }
    unresolved_non_parent = (
        bool(unresolved_dependency_set)
        and lineage.dependency_parent_id is not None
        and lineage.dependency_parent_id not in unresolved_dependency_set
    )
    if unresolved_non_parent:
        reason = "dependency-not-integrated"
        detail = "dependencies missing integrated evidence: " + ", ".join(unresolved_dependency_ids)
        return StackIntegrityPreflightResult(
            ok=False,
            reason=reason,
            edge=edge,
            detail=detail,
            remediation=_remediation_for_stack_reason(reason),
        )
    if lineage.blocked or not lineage.dependency_parent_branch:
        reason = lineage.blocker_reason or "dependency-parent-unresolved"
        detail = lineage.diagnostics[0] if lineage.diagnostics else None
        return StackIntegrityPreflightResult(
            ok=False,
            reason=reason,
            edge=edge,
            detail=detail,
            remediation=_remediation_for_stack_reason(reason),
        )
    if not repo_slug:
        reason = "dependency-parent-state-unavailable"
        return StackIntegrityPreflightResult(
            ok=False,
            reason=reason,
            edge=edge,
            detail="missing repo slug for dependency parent PR state lookup",
            remediation=_remediation_for_stack_reason(reason),
        )

    parent_branch = lineage.dependency_parent_branch
    parent_issue = (
        lookup_dependency_issue_local(lineage.dependency_parent_id)
        if lineage.dependency_parent_id
        else None
    )
    parent_payload = lookup_pr_payload(repo_slug, parent_branch)
    lookup_error: str | None = None
    if parent_payload is None and lookup_pr_payload_diagnostic is not None:
        payload_check, lookup_error = lookup_pr_payload_diagnostic(repo_slug, parent_branch)
        if payload_check is not None:
            parent_payload = payload_check
            lookup_error = None
    if lookup_error:
        reason = "dependency-parent-status-query-failed"
        return StackIntegrityPreflightResult(
            ok=False,
            reason=reason,
            edge=edge,
            detail=lookup_error,
            remediation=_remediation_for_stack_reason(reason),
        )

    pushed = git.git_ref_exists(
        repo_root, f"refs/remotes/origin/{parent_branch}", git_path=git_path
    )
    parent_state = prs.lifecycle_state(
        parent_payload,
        pushed=pushed,
        review_requested=prs.has_review_requests(parent_payload),
    )

    parent_review = None
    has_recorded_pr_signal = False
    if parent_issue:
        parent_description = parent_issue.get("description")
        metadata = changesets.parse_review_metadata(
            parent_description if isinstance(parent_description, str) else ""
        )
        parent_review = metadata.pr_state.strip().lower() if metadata.pr_state else None
        has_recorded_pr_signal = bool(
            metadata.pr_url
            or metadata.pr_number
            or (
                metadata.pr_state
                and metadata.pr_state.strip().lower() not in {"", "null", "pushed"}
            )
        )
        if (
            parent_payload
            and parent_state
            and parent_state != parent_review
            and reconcile_parent_review_state is not None
            and isinstance(lineage.dependency_parent_id, str)
            and lineage.dependency_parent_id
        ):
            try:
                reconcile_parent_review_state(
                    parent_issue=parent_issue,
                    parent_issue_id=lineage.dependency_parent_id,
                    parent_payload=parent_payload,
                    parent_state=parent_state,
                    pushed=pushed,
                )
            except Exception as exc:  # pragma: no cover - defensive boundary
                reason = "dependency-parent-metadata-reconcile-failed"
                return StackIntegrityPreflightResult(
                    ok=False,
                    reason=reason,
                    edge=edge,
                    detail=str(exc),
                    remediation=_remediation_for_stack_reason(reason),
                )

    if parent_state is None:
        reason = "dependency-parent-state-unavailable"
        return StackIntegrityPreflightResult(
            ok=False,
            reason=reason,
            edge=edge,
            detail=f"unable to resolve lifecycle for dependency parent branch {parent_branch!r}",
            remediation=_remediation_for_stack_reason(reason),
        )
    if parent_state == "closed":
        reason = "dependency-parent-pr-closed"
        return StackIntegrityPreflightResult(
            ok=False,
            reason=reason,
            edge=edge,
            detail=f"dependency parent PR for branch {parent_branch!r} is closed",
            remediation=_remediation_for_stack_reason(reason),
        )
    if parent_state == "pushed" and has_recorded_pr_signal:
        reason = "dependency-parent-pr-missing"
        detail = (
            f"dependency parent branch {parent_branch!r} has no live PR but stored "
            f"review state is {parent_review or 'unknown'}"
        )
        return StackIntegrityPreflightResult(
            ok=False,
            reason=reason,
            edge=edge,
            detail=detail,
            remediation=_remediation_for_stack_reason(reason),
        )
    return StackIntegrityPreflightResult(ok=True)


def _top_level_integration_parent(
    *,
    fields: Mapping[str, object],
    root_branch: str | None,
    repo_root: Path,
    git_path: str | None,
) -> str | None:
    workspace_parent = _normalize_branch(fields.get("workspace.parent_branch"))
    if workspace_parent and workspace_parent != root_branch:
        return workspace_parent
    default_branch = _normalize_branch(git.git_default_branch(repo_root, git_path=git_path))
    if default_branch and default_branch != root_branch:
        return default_branch
    return None


def changeset_parent_lifecycle_state(
    issue: dict[str, object],
    *,
    repo_slug: str | None,
    repo_root: Path,
    git_path: str | None,
    beads_root: Path | None = None,
    lookup_pr_payload: Callable[..., dict[str, object] | None],
    lookup_dependency_issue: Callable[[str], dict[str, object] | None] | None = None,
) -> str | None:
    description = issue.get("description")
    fields = beads.parse_description_fields(description if isinstance(description, str) else "")
    issue_cache: dict[str, dict[str, object] | None] = {}

    def lookup_dependency_issue_local(issue_id: str) -> dict[str, object] | None:
        if issue_id in issue_cache:
            return issue_cache[issue_id]
        dependency_issue = None
        if lookup_dependency_issue is not None:
            dependency_issue = lookup_dependency_issue(issue_id)
        if dependency_issue is None and beads_root is not None:
            issues = beads.run_bd_json(["show", issue_id], beads_root=beads_root, cwd=repo_root)
            dependency_issue = issues[0] if issues else None
        issue_cache[issue_id] = dependency_issue
        return issue_cache[issue_id]

    lineage = dependency_lineage.resolve_parent_lineage(
        issue,
        root_branch=fields.get("changeset.root_branch"),
        lookup_issue=lookup_dependency_issue_local,
    )
    normalized = lineage.effective_parent_branch
    if lineage.dependency_ids and lineage.dependency_parent_branch:
        normalized = lineage.dependency_parent_branch
    if normalized is None:
        return None
    normalized_root = lineage.root_branch
    if (
        normalized_root
        and normalized == normalized_root
        and not lineage.used_dependency_parent
        and not lineage.dependency_ids
    ):
        # True top-level changesets use root==parent; treat as no-parent so
        # strategies do not self-deadlock.
        return None
    integration_parent = _top_level_integration_parent(
        fields=fields,
        root_branch=normalized_root,
        repo_root=repo_root,
        git_path=git_path,
    )
    if (
        integration_parent
        and normalized == integration_parent
        and not lineage.used_dependency_parent
        and not lineage.dependency_ids
    ):
        # Legacy root-collapsed parent metadata may normalize to integration
        # branch; treat these top-level changesets as no-parent.
        return None
    if not repo_slug:
        return None
    pushed = git.git_ref_exists(repo_root, f"refs/remotes/origin/{normalized}", git_path=git_path)
    payload = lookup_pr_payload(repo_slug, normalized)
    review_requested = prs.has_review_requests(payload)
    return prs.lifecycle_state(payload, pushed=pushed, review_requested=review_requested)


def changeset_pr_creation_decision(
    issue: dict[str, object],
    *,
    repo_slug: str | None,
    repo_root: Path,
    git_path: str | None,
    beads_root: Path | None = None,
    lookup_pr_payload: Callable[..., dict[str, object] | None],
    lookup_pr_payload_diagnostic: Callable[..., tuple[dict[str, object] | None, str | None]]
    | None = None,
    lookup_dependency_issue: Callable[[str], dict[str, object] | None] | None = None,
) -> PrCreationDecision:
    preflight = sequential_stack_integrity_preflight(
        issue,
        repo_slug=repo_slug,
        repo_root=repo_root,
        git_path=git_path,
        beads_root=beads_root,
        lookup_pr_payload=lookup_pr_payload,
        lookup_pr_payload_diagnostic=lookup_pr_payload_diagnostic,
        lookup_dependency_issue=lookup_dependency_issue,
    )
    if not preflight.ok:
        reason_suffix = preflight.reason or "dependency-parent-unresolved"
        return PrCreationDecision(
            parent_state=None,
            allow_pr=False,
            reason=f"blocked:{reason_suffix}",
        )

    description = issue.get("description")
    fields = beads.parse_description_fields(description if isinstance(description, str) else "")
    issue_cache: dict[str, dict[str, object] | None] = {}

    def lookup_dependency_issue_local(issue_id: str) -> dict[str, object] | None:
        if issue_id in issue_cache:
            return issue_cache[issue_id]
        dependency_issue = None
        if lookup_dependency_issue is not None:
            dependency_issue = lookup_dependency_issue(issue_id)
        if dependency_issue is None and beads_root is not None:
            issues = beads.run_bd_json(["show", issue_id], beads_root=beads_root, cwd=repo_root)
            dependency_issue = issues[0] if issues else None
        issue_cache[issue_id] = dependency_issue
        return issue_cache[issue_id]

    lineage = dependency_lineage.resolve_parent_lineage(
        issue,
        root_branch=fields.get("changeset.root_branch"),
        lookup_issue=lookup_dependency_issue_local,
    )
    if preflight.dependencies_integrated and (
        lineage.blocked or not lineage.dependency_parent_branch
    ):
        return _sequential_pr_creation_decision(parent_state=None)
    if lineage.blocked:
        reason_suffix = lineage.blocker_reason or "dependency-parent-unresolved"
        if lineage.diagnostics:
            reason_suffix = f"{reason_suffix} ({lineage.diagnostics[0]})"
        return PrCreationDecision(
            parent_state=None,
            allow_pr=False,
            reason=f"blocked:{reason_suffix}",
        )
    if lineage.dependency_ids and not lineage.dependency_parent_branch:
        reason_suffix = "dependency-parent-state-unavailable"
        if lineage.diagnostics:
            reason_suffix = f"{reason_suffix} ({lineage.diagnostics[0]})"
        return PrCreationDecision(
            parent_state=None,
            allow_pr=False,
            reason=f"blocked:{reason_suffix}",
        )

    parent_state = changeset_parent_lifecycle_state(
        issue,
        repo_slug=repo_slug,
        repo_root=repo_root,
        git_path=git_path,
        beads_root=beads_root,
        lookup_pr_payload=lookup_pr_payload,
        lookup_dependency_issue=lookup_dependency_issue,
    )
    if lineage.dependency_ids and parent_state is None:
        return PrCreationDecision(
            parent_state=None,
            allow_pr=False,
            reason="blocked:dependency-parent-state-unavailable",
        )
    decision = _sequential_pr_creation_decision(parent_state=parent_state)
    if decision.allow_pr and decision.reason == "no-parent":
        active_sibling = _active_epic_sibling_state(
            issue,
            repo_slug=repo_slug,
            repo_root=repo_root,
            git_path=git_path,
            beads_root=beads_root,
            lookup_pr_payload=lookup_pr_payload,
        )
        if active_sibling is not None:
            sibling_id, sibling_state = active_sibling
            issue_id = _normalize_issue_id(issue.get("id")) or "unknown-changeset"
            atelier_log.info(
                "changeset="
                f"{issue_id} blocked by active sibling PR lifecycle "
                f"{sibling_id}:{sibling_state}"
            )
            return PrCreationDecision(
                parent_state=None,
                allow_pr=False,
                reason="blocked:epic-pr-in-flight",
            )
    return decision


def set_changeset_review_pending_state(
    *,
    changeset_id: str,
    pr_payload: dict[str, object] | None,
    pushed: bool,
    fallback_pr_state: str | None,
    beads_root: Path,
    repo_root: Path,
    mark_changeset_in_progress: Callable[..., None],
    update_changeset_review_from_pr: Callable[..., None],
) -> None:
    mark_changeset_in_progress(changeset_id, beads_root=beads_root, repo_root=repo_root)
    if pr_payload:
        update_changeset_review_from_pr(
            changeset_id,
            pr_payload=pr_payload,
            pushed=pushed,
            beads_root=beads_root,
            repo_root=repo_root,
        )
        return
    if fallback_pr_state:
        worker_store.update_changeset_review(
            changeset_id,
            pr_state=fallback_pr_state,
            beads_root=beads_root,
            repo_root=repo_root,
            preserve_existing=True,
        )


def attempt_create_pr(
    *,
    repo_slug: str,
    issue: dict[str, object],
    work_branch: str,
    is_draft: bool,
    beads_root: Path,
    repo_root: Path,
    git_path: str | None,
    changeset_base_branch: Callable[..., str | None],
    render_changeset_pr_body: Callable[[dict[str, object]], str],
) -> tuple[bool, str]:
    base_branch = changeset_base_branch(
        issue,
        repo_slug=repo_slug,
        beads_root=beads_root,
        repo_root=repo_root,
        git_path=git_path,
    )
    if not base_branch:
        return False, "missing PR base branch metadata"
    title = str(issue.get("title") or "").strip() or work_branch
    body = render_changeset_pr_body(issue)
    with _temporary_text_file(body) as body_file:
        command = [
            "gh",
            "pr",
            "create",
            "--repo",
            repo_slug,
            "--base",
            base_branch,
            "--head",
            work_branch,
            "--title",
            title,
            "--body-file",
            str(body_file),
        ]
        if is_draft:
            command.append("--draft")
        result = exec.try_run_command(command)
    if result is None:
        return False, "missing required command: gh"
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        return False, detail or "gh pr create failed"
    detail = (result.stdout or "").strip()
    if is_draft:
        return True, detail or "created draft PR"
    return True, detail or "created PR"


def attempt_create_draft_pr(
    *,
    repo_slug: str,
    issue: dict[str, object],
    work_branch: str,
    beads_root: Path,
    repo_root: Path,
    git_path: str | None,
    changeset_base_branch: Callable[..., str | None],
    render_changeset_pr_body: Callable[[dict[str, object]], str],
) -> tuple[bool, str]:
    """Backward-compatible wrapper that always creates a draft PR."""
    return attempt_create_pr(
        repo_slug=repo_slug,
        issue=issue,
        work_branch=work_branch,
        is_draft=True,
        beads_root=beads_root,
        repo_root=repo_root,
        git_path=git_path,
        changeset_base_branch=changeset_base_branch,
        render_changeset_pr_body=render_changeset_pr_body,
    )


@contextmanager
def _temporary_text_file(content: str) -> Iterator[Path]:
    with NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
        handle.write(content)
        temp_path = Path(handle.name)
    try:
        yield temp_path
    finally:
        temp_path.unlink(missing_ok=True)


def handle_pushed_without_pr(
    *,
    issue: dict[str, object],
    changeset_id: str,
    agent_id: str,
    repo_slug: str | None,
    repo_root: Path,
    beads_root: Path,
    git_path: str | None,
    create_as_draft: bool,
    create_detail_prefix: str | None = None,
    changeset_base_branch: Callable[..., str | None],
    changeset_work_branch: Callable[[dict[str, object]], str | None],
    render_changeset_pr_body: Callable[[dict[str, object]], str],
    lookup_pr_payload: Callable[..., dict[str, object] | None],
    lookup_pr_payload_diagnostic: Callable[..., tuple[dict[str, object] | None, str | None]],
    mark_changeset_in_progress: Callable[..., None],
    send_planner_notification: Callable[..., None],
    update_changeset_review_from_pr: Callable[..., None],
    emit: Callable[[str], None],
    attempt_create_pr_fn: Callable[..., tuple[bool, str]] | None = None,
) -> PrGateResult:
    decision = changeset_pr_creation_decision(
        issue,
        repo_slug=repo_slug,
        repo_root=repo_root,
        git_path=git_path,
        beads_root=beads_root,
        lookup_pr_payload=lookup_pr_payload,
    )
    if not decision.allow_pr:
        set_changeset_review_pending_state(
            changeset_id=changeset_id,
            pr_payload=None,
            pushed=True,
            fallback_pr_state="pushed",
            beads_root=beads_root,
            repo_root=repo_root,
            mark_changeset_in_progress=mark_changeset_in_progress,
            update_changeset_review_from_pr=update_changeset_review_from_pr,
        )
        return PrGateResult(
            finalize_result=FinalizeResult(
                continue_running=True, reason="changeset_review_pending"
            ),
            detail=decision.reason,
        )

    failure_reason = "changeset_pr_create_failed"
    failure_subject = "NEEDS-DECISION: PR creation failed"
    create_detail = create_detail_prefix or ""
    if not repo_slug:
        failure_reason = "changeset_pr_missing_repo_slug"
        failure_subject = "NEEDS-DECISION: PR provider config missing"
        create_detail = "missing GitHub repo slug for PR creation"
    else:
        work_branch = changeset_work_branch(issue)
        if not work_branch:
            create_detail = "missing changeset.work_branch metadata for PR creation"
        else:
            create_fn = attempt_create_pr_fn or attempt_create_pr
            created, detail = create_fn(
                repo_slug=repo_slug,
                issue=issue,
                work_branch=work_branch,
                is_draft=create_as_draft,
                beads_root=beads_root,
                repo_root=repo_root,
                git_path=git_path,
                changeset_base_branch=changeset_base_branch,
                render_changeset_pr_body=render_changeset_pr_body,
            )
            create_detail = detail
            if created:
                pr_payload = lookup_pr_payload(repo_slug, work_branch)
                lookup_error = None
                if pr_payload is None:
                    payload_check, lookup_error = lookup_pr_payload_diagnostic(
                        repo_slug, work_branch
                    )
                    if payload_check is not None:
                        pr_payload = payload_check
                        lookup_error = None
                if pr_payload:
                    set_changeset_review_pending_state(
                        changeset_id=changeset_id,
                        pr_payload=pr_payload,
                        pushed=True,
                        fallback_pr_state=None,
                        beads_root=beads_root,
                        repo_root=repo_root,
                        mark_changeset_in_progress=mark_changeset_in_progress,
                        update_changeset_review_from_pr=update_changeset_review_from_pr,
                    )
                else:
                    set_changeset_review_pending_state(
                        changeset_id=changeset_id,
                        pr_payload=None,
                        pushed=True,
                        fallback_pr_state="draft-pr" if create_as_draft else "pr-open",
                        beads_root=beads_root,
                        repo_root=repo_root,
                        mark_changeset_in_progress=mark_changeset_in_progress,
                        update_changeset_review_from_pr=update_changeset_review_from_pr,
                    )
                if lookup_error:
                    create_detail = f"{create_detail}; unable to verify created PR: {lookup_error}"
                return PrGateResult(
                    finalize_result=FinalizeResult(
                        continue_running=True, reason="changeset_review_pending"
                    ),
                    detail=create_detail or None,
                )
            # Recover from duplicate/race failures by checking live PR state.
            pr_payload = lookup_pr_payload(repo_slug, work_branch)
            lookup_error = None
            if pr_payload is None:
                payload_check, lookup_error = lookup_pr_payload_diagnostic(repo_slug, work_branch)
                if payload_check is not None:
                    pr_payload = payload_check
                    lookup_error = None
            if pr_payload:
                set_changeset_review_pending_state(
                    changeset_id=changeset_id,
                    pr_payload=pr_payload,
                    pushed=True,
                    fallback_pr_state=None,
                    beads_root=beads_root,
                    repo_root=repo_root,
                    mark_changeset_in_progress=mark_changeset_in_progress,
                    update_changeset_review_from_pr=update_changeset_review_from_pr,
                )
                return PrGateResult(
                    finalize_result=FinalizeResult(
                        continue_running=True, reason="changeset_review_pending"
                    ),
                    detail="existing PR found after create failure",
                )
            if lookup_error:
                failure_reason = "changeset_pr_status_query_failed"
                failure_subject = "NEEDS-DECISION: PR status query failed"
                create_detail = f"{create_detail}; unable to verify existing PR: {lookup_error}"
                atelier_log.warning(
                    "changeset="
                    f"{changeset_id} PR status lookup failed after create attempt: "
                    f"{lookup_error}"
                )

    mark_changeset_in_progress(changeset_id, beads_root=beads_root, repo_root=repo_root)
    note = (
        "publish_pending: branch pushed but PR missing where "
        f"strategy allows PR ({decision.reason})"
    )
    if create_detail:
        note = f"{note}; PR creation attempt failed: {create_detail}"
    beads.run_bd_command(
        [
            "update",
            changeset_id,
            "--append-notes",
            note,
        ],
        beads_root=beads_root,
        cwd=repo_root,
        allow_failure=True,
    )
    body = (
        "Changeset branch is pushed but no PR exists where policy allows PR "
        f"creation (reason={decision.reason})."
    )
    if create_detail:
        body = f"{body}\nPR creation attempt failed: {create_detail}"
        emit(f"PR creation failed for {changeset_id}: {create_detail}")
    if failure_reason == "changeset_pr_missing_repo_slug":
        body = (
            f"{body}\nAction: configure GitHub provider metadata so finalize can "
            "create PRs automatically."
        )
    else:
        body = f"{body}\nAction: resolve `gh pr create` failure and rerun worker finalize."
    send_planner_notification(
        subject=f"{failure_subject} ({changeset_id})",
        body=body,
        agent_id=agent_id,
        thread_id=changeset_id,
        beads_root=beads_root,
        repo_root=repo_root,
        dry_run=False,
    )
    atelier_log.warning(
        "changeset="
        f"{changeset_id} finalize stopped reason={failure_reason} "
        f"detail={create_detail or 'n/a'}"
    )
    return PrGateResult(
        finalize_result=FinalizeResult(continue_running=False, reason=failure_reason),
        detail=create_detail or None,
    )

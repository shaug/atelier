"""Worker reconcile helpers for merged changesets."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .. import agent_home, beads, changesets, config, git, lifecycle, prs
from . import stale_pr_lifecycle
from . import store_adapter as worker_store
from .models import FinalizeResult, ReconcileResult


@dataclass(frozen=True)
class ReconcileCandidate:
    issue_id: str
    issue: dict[str, object]
    status: str
    epic_id: str
    integrated_sha: str | None
    dependency_ids: tuple[str, ...]
    terminal_pr_state: str | None = None
    require_terminal_status: bool = False
    triage_summary: str | None = None


@dataclass(frozen=True)
class ReopenLifecycleEvidence:
    active_state: str
    source: str
    stored_state: str | None
    live_state: str | None


@dataclass(frozen=True)
class EpicHookStateEvidence:
    has_live_hook: bool | None
    detail: str


def _normalized_labels(issue: dict[str, object]) -> set[str]:
    return lifecycle.normalized_labels(issue.get("labels"))


def _canonical_changeset_status(issue: dict[str, object]) -> str | None:
    return lifecycle.canonical_lifecycle_status(issue.get("status"))


def _description_fields(issue: dict[str, object]) -> dict[str, str]:
    description = issue.get("description")
    text = description if isinstance(description, str) else ""
    return beads.parse_description_fields(text)


def _changeset_work_branch(issue: dict[str, object]) -> str | None:
    value = _description_fields(issue).get("changeset.work_branch")
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized or normalized.lower() == "null":
        return None
    return normalized


def _stored_review_state(issue: dict[str, object]) -> str | None:
    return lifecycle.normalize_review_state(_description_fields(issue).get("pr_state"))


def _claims_merged_closure(issue: dict[str, object]) -> bool:
    if _canonical_changeset_status(issue) != "closed":
        return False
    labels = _normalized_labels(issue)
    if "cs:abandoned" in labels:
        return False
    if "cs:merged" in labels:
        return True
    return _stored_review_state(issue) == "merged"


def _live_review_state(
    issue: dict[str, object],
    *,
    repo_slug: str | None,
    repo_root: Path,
    git_path: str | None,
) -> tuple[str | None, str | None]:
    if not repo_slug:
        return None, None
    work_branch = _changeset_work_branch(issue)
    if not work_branch:
        return None, None
    pushed = git.git_ref_exists(repo_root, f"refs/remotes/origin/{work_branch}", git_path=git_path)
    lookup = prs.lookup_github_pr_status(repo_slug, work_branch)
    if lookup.failed:
        # Retry with a forced refresh so a transient cached lookup error does
        # not keep poisoning reconcile decisions for this branch.
        lookup = prs.lookup_github_pr_status(repo_slug, work_branch, refresh=True)
    if lookup.failed:
        return None, lookup.error
    if not lookup.found or not isinstance(lookup.payload, dict):
        return None, None
    pr_payload = lookup.payload
    review_requested = prs.has_review_requests(pr_payload)
    return (
        prs.lifecycle_state(pr_payload, pushed=pushed, review_requested=review_requested),
        None,
    )


def _review_drift_evidence(
    issue: dict[str, object],
    *,
    repo_slug: str | None,
    repo_root: Path,
    git_path: str | None,
) -> tuple[ReopenLifecycleEvidence | None, str | None]:
    if _canonical_changeset_status(issue) != "closed":
        return None, None
    stored_state = _stored_review_state(issue)
    live_state, lookup_error = _live_review_state(
        issue,
        repo_slug=repo_slug,
        repo_root=repo_root,
        git_path=git_path,
    )
    if live_state in lifecycle.ACTIVE_REVIEW_STATES:
        return (
            ReopenLifecycleEvidence(
                active_state=live_state,
                source="live-pr",
                stored_state=stored_state,
                live_state=live_state,
            ),
            None,
        )
    return None, lookup_error


def _format_lookup_error(error: str | None) -> str:
    if not isinstance(error, str):
        return "unknown"
    normalized = " ".join(error.strip().split())
    if not normalized:
        return "unknown"
    return normalized


def _normalized_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized:
        return None
    return normalized


def _normalized_sha(value: object) -> str | None:
    normalized = _normalized_text(value)
    if normalized is None or normalized.lower() == "null":
        return None
    return normalized


def _recorded_integrated_sha(issue: dict[str, object]) -> str | None:
    return _normalized_sha(_description_fields(issue).get("changeset.integrated_sha"))


def _converge_stale_terminal_metadata(
    candidate: ReconcileCandidate,
    *,
    beads_root: Path,
    repo_root: Path,
) -> tuple[str, ...]:
    issue = candidate.issue
    changeset_id = candidate.issue_id
    updates: list[str] = []
    if candidate.terminal_pr_state:
        description = issue.get("description")
        metadata = changesets.parse_review_metadata(
            description if isinstance(description, str) else ""
        )
        stored_state = lifecycle.normalize_review_state(metadata.pr_state)
        if stored_state != candidate.terminal_pr_state:
            worker_store.update_changeset_review(
                changeset_id,
                changesets.ReviewMetadata(
                    pr_url=metadata.pr_url,
                    pr_number=metadata.pr_number,
                    pr_state=candidate.terminal_pr_state,
                    review_owner=metadata.review_owner,
                ),
                beads_root=beads_root,
                repo_root=repo_root,
            )
            updates.append(f"pr_state={candidate.terminal_pr_state}")
    if candidate.integrated_sha:
        recorded_sha = _recorded_integrated_sha(issue)
        if recorded_sha != candidate.integrated_sha:
            worker_store.update_changeset_integrated_sha(
                changeset_id,
                candidate.integrated_sha,
                beads_root=beads_root,
                repo_root=repo_root,
            )
            updates.append(f"changeset.integrated_sha={candidate.integrated_sha}")
    return tuple(updates)


def _converged_integrated_sha(updates: tuple[str, ...]) -> str | None:
    prefix = "changeset.integrated_sha="
    for update in updates:
        if update.startswith(prefix):
            return update.removeprefix(prefix)
    return None


def _agent_issue_identity(issue: dict[str, object]) -> str | None:
    fields = _description_fields(issue)
    description_identity = _normalized_text(fields.get("agent_id"))
    if description_identity is not None:
        return description_identity
    return _normalized_text(issue.get("title"))


def _active_hook_scan_for_epic(
    epic_id: str,
    *,
    beads_root: Path,
    repo_root: Path,
) -> EpicHookStateEvidence:
    issues_by_id: dict[str, dict[str, object]] = {}
    list_errors: list[str] = []
    for label in beads.issue_label_candidates(
        "agent",
        beads_root=beads_root,
        include_configured_prefix=True,
    ):
        try:
            agent_issues = beads.run_bd_json(
                ["list", "--label", label, "--all", "--limit", "0"],
                beads_root=beads_root,
                cwd=repo_root,
            )
        except SystemExit:
            list_errors.append(f"agent_list_failed({label})")
            continue
        for issue in agent_issues:
            issue_id = _normalized_text(issue.get("id"))
            if issue_id is None:
                continue
            issues_by_id.setdefault(issue_id, issue)

    active_hook_agents: set[str] = set()
    scan_unknown_details: list[str] = []
    for issue_id in sorted(issues_by_id):
        issue = issues_by_id[issue_id]
        agent_id = _agent_issue_identity(issue)
        if agent_id is None or not agent_home.is_session_agent_active(agent_id):
            continue
        try:
            hook = beads.get_agent_hook(issue_id, beads_root=beads_root, cwd=repo_root)
        except SystemExit:
            scan_unknown_details.append(f"hook_lookup_failed({agent_id})")
            continue
        if hook == epic_id:
            active_hook_agents.add(agent_id)

    if active_hook_agents:
        agents = ",".join(sorted(active_hook_agents))
        return EpicHookStateEvidence(has_live_hook=True, detail=f"active_hook({agents})")
    if scan_unknown_details or list_errors:
        details = ";".join([*scan_unknown_details, *list_errors])
        return EpicHookStateEvidence(has_live_hook=None, detail=details)
    return EpicHookStateEvidence(has_live_hook=False, detail="no_active_hook_match")


def _epic_hook_state(
    epic_id: str,
    *,
    load_epic: Callable[[str], dict[str, object] | None],
    beads_root: Path,
    repo_root: Path,
    cache: dict[str, EpicHookStateEvidence],
) -> EpicHookStateEvidence:
    cached = cache.get(epic_id)
    if cached is not None:
        return cached
    epic = load_epic(epic_id)
    if not epic:
        evidence = EpicHookStateEvidence(has_live_hook=None, detail="epic_unavailable")
        cache[epic_id] = evidence
        return evidence

    fallback_hook_evidence = _active_hook_scan_for_epic(
        epic_id,
        beads_root=beads_root,
        repo_root=repo_root,
    )
    if fallback_hook_evidence.has_live_hook:
        cache[epic_id] = fallback_hook_evidence
        return fallback_hook_evidence

    assignee = _normalized_text(epic.get("assignee"))
    assignee_evidence: EpicHookStateEvidence
    if assignee is None:
        assignee_evidence = EpicHookStateEvidence(has_live_hook=False, detail="unassigned")
    elif not agent_home.is_session_agent_active(assignee):
        assignee_evidence = EpicHookStateEvidence(
            has_live_hook=False, detail=f"assignee_inactive({assignee})"
        )
    else:
        assignee_bead = beads.find_agent_bead(assignee, beads_root=beads_root, cwd=repo_root)
        if not assignee_bead:
            assignee_evidence = EpicHookStateEvidence(
                has_live_hook=None, detail=f"agent_bead_missing({assignee})"
            )
        else:
            assignee_bead_id = _normalized_text(assignee_bead.get("id"))
            if assignee_bead_id is None:
                assignee_evidence = EpicHookStateEvidence(
                    has_live_hook=None, detail=f"agent_bead_id_missing({assignee})"
                )
            else:
                try:
                    hook = beads.get_agent_hook(
                        assignee_bead_id,
                        beads_root=beads_root,
                        cwd=repo_root,
                    )
                except SystemExit:
                    assignee_evidence = EpicHookStateEvidence(
                        has_live_hook=None, detail=f"hook_lookup_failed({assignee})"
                    )
                else:
                    if hook == epic_id:
                        assignee_evidence = EpicHookStateEvidence(
                            has_live_hook=True,
                            detail=f"active_hook({assignee})",
                        )
                    elif hook:
                        assignee_evidence = EpicHookStateEvidence(
                            has_live_hook=False,
                            detail=f"hooked_elsewhere({assignee}->{hook})",
                        )
                    else:
                        assignee_evidence = EpicHookStateEvidence(
                            has_live_hook=False,
                            detail=f"assignee_unhooked({assignee})",
                        )

    if assignee_evidence.has_live_hook:
        cache[epic_id] = assignee_evidence
        return assignee_evidence

    if fallback_hook_evidence.has_live_hook is None or assignee_evidence.has_live_hook is None:
        detail = ";".join((assignee_evidence.detail, fallback_hook_evidence.detail))
        evidence = EpicHookStateEvidence(has_live_hook=None, detail=detail)
        cache[epic_id] = evidence
        return evidence

    detail = ";".join((assignee_evidence.detail, fallback_hook_evidence.detail))
    evidence = EpicHookStateEvidence(has_live_hook=False, detail=detail)
    cache[epic_id] = evidence
    return evidence


def list_reconcile_epic_candidates(
    *,
    project_config: config.ProjectConfig,
    beads_root: Path,
    repo_root: Path,
    git_path: str | None = None,
    changeset_integration_signal: Callable[..., tuple[bool, str | None]],
    resolve_epic_id_for_changeset: Callable[..., str | None],
    is_closed_status: Callable[[object], bool],
    epic_root_integrated_into_parent: Callable[..., bool],
) -> dict[str, list[str]]:
    """Return merged changeset reconciliation candidates grouped by epic."""
    all_changesets = beads.list_all_changesets(
        beads_root=beads_root,
        cwd=repo_root,
        include_closed=True,
    )
    repo_slug = prs.github_repo_slug(
        project_config.project.origin or project_config.project.repo_url
    )
    epic_cache: dict[str, dict[str, object] | None] = {}

    def load_epic(epic_id: str) -> dict[str, object] | None:
        if epic_id in epic_cache:
            return epic_cache[epic_id]
        loaded = beads.run_bd_json(["show", epic_id], beads_root=beads_root, cwd=repo_root)
        epic_cache[epic_id] = loaded[0] if loaded else None
        return epic_cache[epic_id]

    hook_state_cache: dict[str, EpicHookStateEvidence] = {}
    candidates: dict[str, list[str]] = {}
    for issue in all_changesets:
        issue_id = issue.get("id")
        if not isinstance(issue_id, str) or not issue_id.strip():
            continue
        changeset_id = issue_id.strip()
        status = _canonical_changeset_status(issue)
        if status == "in_progress":
            epic_id = resolve_epic_id_for_changeset(
                issue, beads_root=beads_root, repo_root=repo_root
            )
            if not epic_id:
                continue
            hook_state = _epic_hook_state(
                epic_id,
                load_epic=load_epic,
                beads_root=beads_root,
                repo_root=repo_root,
                cache=hook_state_cache,
            )
            if hook_state.has_live_hook is not False:
                continue
            live_state, lookup_error = _live_review_state(
                issue,
                repo_slug=repo_slug,
                repo_root=repo_root,
                git_path=git_path,
            )
            if lookup_error is not None:
                candidates.setdefault(epic_id, []).append(changeset_id)
                continue
            if live_state in {"merged", "closed"}:
                candidates.setdefault(epic_id, []).append(changeset_id)
            continue
        drift_evidence, drift_lookup_error = _review_drift_evidence(
            issue,
            repo_slug=repo_slug,
            repo_root=repo_root,
            git_path=git_path,
        )
        if drift_lookup_error is not None:
            epic_id = resolve_epic_id_for_changeset(
                issue, beads_root=beads_root, repo_root=repo_root
            )
            if not epic_id:
                continue
            candidates.setdefault(epic_id, []).append(changeset_id)
            continue
        if drift_evidence is None:
            if status not in {"open", "blocked", "closed"}:
                continue
            integration_proven, integrated_sha = changeset_integration_signal(
                issue,
                repo_slug=repo_slug,
                repo_root=repo_root,
                git_path=git_path,
                require_target_branch_proof=status == "closed",
            )
            if not integration_proven:
                continue
            epic_id = resolve_epic_id_for_changeset(
                issue, beads_root=beads_root, repo_root=repo_root
            )
            if not epic_id:
                continue
            if status == "closed":
                epic_issue = load_epic(epic_id)
                epic_closed = bool(epic_issue) and is_closed_status(epic_issue.get("status"))
                if (
                    epic_closed
                    and integrated_sha
                    and epic_issue
                    and epic_root_integrated_into_parent(
                        epic_issue, repo_root=repo_root, git_path=git_path
                    )
                ):
                    continue
            candidates.setdefault(epic_id, []).append(changeset_id)
            continue
        epic_id = resolve_epic_id_for_changeset(issue, beads_root=beads_root, repo_root=repo_root)
        if not epic_id:
            continue
        candidates.setdefault(epic_id, []).append(changeset_id)
    ordered: dict[str, list[str]] = {}
    for epic_id in sorted(candidates):
        ordered[epic_id] = sorted(candidates[epic_id])
    return ordered


def _format_reopen_evidence(evidence: ReopenLifecycleEvidence) -> str:
    stored = evidence.stored_state or "none"
    live = evidence.live_state or "none"
    return (
        f"evidence(source={evidence.source},active={evidence.active_state},"
        f"stored={stored},live={live})"
    )


def resolve_hook_agent_bead_for_epic(
    epic_id: str,
    *,
    fallback_agent_bead_id: str | None,
    beads_root: Path,
    repo_root: Path,
) -> str | None:
    issues = beads.run_bd_json(["show", epic_id], beads_root=beads_root, cwd=repo_root)
    if not issues:
        return fallback_agent_bead_id
    assignee = issues[0].get("assignee")
    if isinstance(assignee, str) and assignee.strip():
        assignee_bead = beads.find_agent_bead(
            assignee.strip(), beads_root=beads_root, cwd=repo_root
        )
        if assignee_bead:
            issue_id = assignee_bead.get("id")
            if isinstance(issue_id, str) and issue_id.strip():
                return issue_id.strip()
    return fallback_agent_bead_id


def reconcile_blocked_merged_changesets(
    *,
    agent_id: str,
    agent_bead_id: str | None,
    project_config: config.ProjectConfig,
    project_data_dir: Path | None,
    beads_root: Path,
    repo_root: Path,
    git_path: str | None = None,
    epic_filter: str | None = None,
    changeset_filter: set[str] | None = None,
    dry_run: bool = False,
    log: Callable[[str], None] | None = None,
    resolve_epic_id_for_changeset: Callable[..., str | None],
    changeset_integration_signal: Callable[..., tuple[bool, str | None]],
    issue_dependency_ids: Callable[[dict[str, object]], tuple[str, ...]],
    issue_labels: Callable[[dict[str, object]], set[str]],
    finalize_changeset: Callable[..., FinalizeResult],
    finalize_epic_if_complete: Callable[..., FinalizeResult],
) -> ReconcileResult:
    """Reconcile merged changesets, honoring dependency order."""
    all_changesets = beads.list_all_changesets(
        beads_root=beads_root,
        cwd=repo_root,
        include_closed=True,
    )
    scanned = 0
    actionable = 0
    reconciled = 0
    failed = 0
    started_at = dt.datetime.now(tz=dt.timezone.utc)
    repo_slug = prs.github_repo_slug(
        project_config.project.origin or project_config.project.repo_url
    )
    epic_cache: dict[str, dict[str, object] | None] = {}

    def load_epic(epic_id: str) -> dict[str, object] | None:
        if epic_id in epic_cache:
            return epic_cache[epic_id]
        loaded = beads.run_bd_json(["show", epic_id], beads_root=beads_root, cwd=repo_root)
        epic_cache[epic_id] = loaded[0] if loaded else None
        return epic_cache[epic_id]

    hook_state_cache: dict[str, EpicHookStateEvidence] = {}
    drift_anomaly_ids: set[str] = set()
    drift_lookup_error_ids: set[str] = set()
    for issue in all_changesets:
        changeset_id = issue.get("id")
        if not isinstance(changeset_id, str) or not changeset_id.strip():
            continue
        changeset_id = changeset_id.strip()
        if changeset_filter is not None and changeset_id not in changeset_filter:
            continue
        if _canonical_changeset_status(issue) != "closed":
            continue
        drift_evidence, drift_lookup_error = _review_drift_evidence(
            issue,
            repo_slug=repo_slug,
            repo_root=repo_root,
            git_path=git_path,
        )
        if drift_lookup_error is not None:
            epic_id = resolve_epic_id_for_changeset(
                issue, beads_root=beads_root, repo_root=repo_root
            )
            if epic_filter and epic_id != epic_filter:
                continue
            scanned += 1
            if not epic_id:
                failed += 1
                if log:
                    log(f"reconcile error: {changeset_id} (unable to resolve epic)")
                continue
            actionable += 1
            failed += 1
            drift_lookup_error_ids.add(changeset_id)
            if log:
                log(
                    "reconcile anomaly: "
                    f"{changeset_id} -> epic={epic_id} "
                    "closed+pr-lifecycle-lookup-error"
                    f"(error={_format_lookup_error(drift_lookup_error)}) "
                    "decision-required"
                )
            continue
        if drift_evidence is None:
            continue
        epic_id = resolve_epic_id_for_changeset(issue, beads_root=beads_root, repo_root=repo_root)
        if epic_filter and epic_id != epic_filter:
            continue
        scanned += 1
        if not epic_id:
            failed += 1
            if log:
                log(f"reconcile error: {changeset_id} (unable to resolve epic)")
            continue
        actionable += 1
        drift_anomaly_ids.add(changeset_id)
        if dry_run:
            failed += 1
            if log:
                log(
                    "reconcile dry-run anomaly: "
                    f"{changeset_id} -> epic={epic_id} "
                    f"closed+active-pr-lifecycle({_format_reopen_evidence(drift_evidence)})"
                )
            continue
        if beads.close_transition_has_active_pr_lifecycle(
            issue,
            active_pr_lifecycle=True,
        ):
            worker_store.mark_issue_in_progress(
                changeset_id,
                beads_root=beads_root,
                repo_root=repo_root,
            )
            reconciled += 1
            if log:
                log(
                    "reconcile recovery: "
                    f"{changeset_id} -> epic={epic_id} restored to in_progress "
                    "after closed+active-pr-lifecycle drift "
                    f"({_format_reopen_evidence(drift_evidence)})"
                )
        if log:
            log(
                "reconcile anomaly: "
                f"{changeset_id} -> epic={epic_id} "
                f"closed+active-pr-lifecycle({_format_reopen_evidence(drift_evidence)}) "
                "decision-required"
            )

    candidates: dict[str, ReconcileCandidate] = {}
    for issue in all_changesets:
        changeset_id = issue.get("id")
        if not isinstance(changeset_id, str) or not changeset_id.strip():
            continue
        changeset_id = changeset_id.strip()
        if changeset_id in drift_anomaly_ids or changeset_id in drift_lookup_error_ids:
            continue
        if changeset_filter is not None and changeset_id not in changeset_filter:
            continue
        status = _canonical_changeset_status(issue)
        if status not in {"open", "in_progress", "blocked", "closed"}:
            if log:
                log(f"reconcile scan: {changeset_id} status={status or 'unknown'}")
                log(f"reconcile skip: {changeset_id} (status={status})")
            continue
        epic_id = resolve_epic_id_for_changeset(issue, beads_root=beads_root, repo_root=repo_root)
        if epic_filter and epic_id != epic_filter:
            continue
        if log:
            log(f"reconcile scan: {changeset_id} status={status or 'unknown'}")
        if not epic_id:
            failed += 1
            if log:
                log(f"reconcile error: {changeset_id} (unable to resolve epic)")
            continue
        scanned += 1
        stale_terminal: stale_pr_lifecycle.StaleTerminalPrLifecycleClassification | None = None
        if status == "in_progress":
            hook_state = _epic_hook_state(
                epic_id,
                load_epic=load_epic,
                beads_root=beads_root,
                repo_root=repo_root,
                cache=hook_state_cache,
            )
            if hook_state.has_live_hook is None:
                actionable += 1
                failed += 1
                if log:
                    log(
                        "reconcile anomaly: "
                        f"{changeset_id} -> epic={epic_id} "
                        f"in_progress+hook-state-unknown({hook_state.detail}) "
                        "decision-required"
                    )
                continue
            if hook_state.has_live_hook:
                if log:
                    log(
                        f"reconcile skip: {changeset_id} "
                        f"(in_progress with live hook: {hook_state.detail})"
                    )
                continue
            stale_terminal = stale_pr_lifecycle.classify_stale_terminal_pr_lifecycle(
                issue,
                repo_slug=repo_slug,
                repo_root=repo_root,
                branch_pr=project_config.branch.pr,
                git_path=git_path,
            )
            if stale_terminal.is_anomaly:
                actionable += 1
                failed += 1
                if log:
                    log(
                        "reconcile anomaly: "
                        f"{changeset_id} -> epic={epic_id} "
                        f"status={status} "
                        f"{stale_pr_lifecycle.format_operator_triage(stale_terminal)}"
                    )
                continue
            if not stale_terminal.is_candidate:
                if log:
                    log(
                        "reconcile skip: "
                        f"{changeset_id} -> epic={epic_id} "
                        f"status={status} "
                        f"{stale_pr_lifecycle.format_operator_triage(stale_terminal)}"
                    )
                continue
            integration_proven, integrated_sha = changeset_integration_signal(
                issue,
                repo_slug=repo_slug,
                repo_root=repo_root,
                git_path=git_path,
                require_target_branch_proof=stale_terminal.live_pr_state == "merged",
            )
            candidates[changeset_id] = ReconcileCandidate(
                issue_id=changeset_id,
                issue=issue,
                status=status,
                epic_id=epic_id,
                integrated_sha=integrated_sha.strip()
                if integration_proven and integrated_sha
                else None,
                dependency_ids=issue_dependency_ids(issue),
                terminal_pr_state=stale_terminal.live_pr_state,
                require_terminal_status=True,
                triage_summary=stale_pr_lifecycle.format_operator_triage(stale_terminal),
            )
            continue
        if project_config.branch.pr and status in {"open", "blocked"}:
            stale_terminal = stale_pr_lifecycle.classify_stale_terminal_pr_lifecycle(
                issue,
                repo_slug=repo_slug,
                repo_root=repo_root,
                branch_pr=True,
                git_path=git_path,
            )
            if stale_terminal.is_anomaly:
                actionable += 1
                failed += 1
                if log:
                    log(
                        "reconcile anomaly: "
                        f"{changeset_id} -> epic={epic_id} "
                        f"status={status} "
                        f"{stale_pr_lifecycle.format_operator_triage(stale_terminal)}"
                    )
                continue
            if stale_terminal.is_candidate:
                integration_proven, integrated_sha = changeset_integration_signal(
                    issue,
                    repo_slug=repo_slug,
                    repo_root=repo_root,
                    git_path=git_path,
                    require_target_branch_proof=stale_terminal.live_pr_state == "merged",
                )
                candidates[changeset_id] = ReconcileCandidate(
                    issue_id=changeset_id,
                    issue=issue,
                    status=status,
                    epic_id=epic_id,
                    integrated_sha=integrated_sha.strip()
                    if integration_proven and integrated_sha
                    else None,
                    dependency_ids=issue_dependency_ids(issue),
                    terminal_pr_state=stale_terminal.live_pr_state,
                    require_terminal_status=True,
                    triage_summary=stale_pr_lifecycle.format_operator_triage(stale_terminal),
                )
                continue
            if log:
                log(
                    "reconcile skip: "
                    f"{changeset_id} -> epic={epic_id} "
                    f"status={status} "
                    f"{stale_pr_lifecycle.format_operator_triage(stale_terminal)}"
                )
            continue
        integration_proven, integrated_sha = changeset_integration_signal(
            issue,
            repo_slug=repo_slug,
            repo_root=repo_root,
            git_path=git_path,
            require_target_branch_proof=status == "closed",
        )
        if not integration_proven:
            if status == "closed" and _claims_merged_closure(issue):
                actionable += 1
                failed += 1
                if log:
                    log(
                        "reconcile anomaly: "
                        f"{changeset_id} -> epic={epic_id} "
                        "closed+merged-like-without-integration-proof "
                        "(classify abandoned/superseded or restore integration evidence)"
                    )
                continue
            if log:
                log(f"reconcile skip: {changeset_id} (no integration signal)")
            continue
        candidates[changeset_id] = ReconcileCandidate(
            issue_id=changeset_id,
            issue=issue,
            status=status,
            epic_id=epic_id,
            integrated_sha=integrated_sha.strip() if integrated_sha else None,
            dependency_ids=issue_dependency_ids(issue),
        )
    actionable += len(candidates)
    if not candidates:
        return ReconcileResult(
            scanned=scanned,
            actionable=actionable,
            reconciled=reconciled,
            failed=failed,
        )

    issue_cache: dict[str, dict[str, object] | None] = {
        candidate.issue_id: candidate.issue for candidate in candidates.values()
    }

    def load_issue(issue_id: str) -> dict[str, object] | None:
        if issue_id in issue_cache:
            return issue_cache[issue_id]
        issue_cache[issue_id] = worker_store.show_issue(
            issue_id,
            beads_root=beads_root,
            repo_root=repo_root,
        )
        return issue_cache[issue_id]

    dependency_finalized_cache: dict[str, bool] = {}

    def dependency_finalized(issue_id: str) -> bool:
        if issue_id in dependency_finalized_cache:
            return dependency_finalized_cache[issue_id]
        issue = load_issue(issue_id)
        if not issue:
            dependency_finalized_cache[issue_id] = False
            return False
        if not lifecycle.is_work_issue(
            labels=issue_labels(issue),
            issue_type=lifecycle.issue_payload_type(issue),
        ):
            dependency_finalized_cache[issue_id] = True
            return True
        work_children = worker_store.list_work_children(
            issue_id,
            beads_root=beads_root,
            repo_root=repo_root,
            include_closed=True,
        )
        if work_children:
            dependency_finalized_cache[issue_id] = True
            return True
        drift_evidence, drift_lookup_error = _review_drift_evidence(
            issue,
            repo_slug=repo_slug,
            repo_root=repo_root,
            git_path=git_path,
        )
        if drift_lookup_error is not None:
            if log:
                log(
                    "reconcile anomaly: "
                    f"{issue_id} "
                    "closed+pr-lifecycle-lookup-error"
                    f"(error={_format_lookup_error(drift_lookup_error)}) "
                    "falling-back-to-integration-proof"
                )
        if drift_evidence is not None:
            dependency_finalized_cache[issue_id] = False
            return False
        status = _canonical_changeset_status(issue)
        integrated, _ = changeset_integration_signal(
            issue,
            repo_slug=repo_slug,
            repo_root=repo_root,
            git_path=git_path,
            require_target_branch_proof=status == "closed",
        )
        if integrated:
            dependency_finalized_cache[issue_id] = True
            return True
        dependency_finalized_cache[issue_id] = False
        return False

    remaining = set(candidates)
    reconciled_ids: set[str] = set()
    failed_ids: set[str] = set()
    epics_ready_to_finalize: set[str] = set()

    while remaining:
        progressed = False
        for changeset_id in sorted(remaining):
            candidate = candidates[changeset_id]
            dependency_waiting = False
            dependency_errors: list[str] = []
            for dependency_id in candidate.dependency_ids:
                if dependency_id in reconciled_ids:
                    continue
                if dependency_id in failed_ids:
                    dependency_waiting = True
                    dependency_errors.append(f"{dependency_id}(failed)")
                    continue
                if dependency_id in candidates:
                    dependency_waiting = True
                    dependency_errors.append(dependency_id)
                    continue
                if not dependency_finalized(dependency_id):
                    dependency_waiting = True
                    dependency_errors.append(dependency_id)
            if dependency_waiting:
                if log:
                    log(
                        "reconcile defer: "
                        f"{changeset_id} (waiting on dependencies: "
                        f"{', '.join(dependency_errors)})"
                    )
                continue
            remaining.remove(changeset_id)
            progressed = True
            if dry_run:
                reconciled += 1
                reconciled_ids.add(changeset_id)
                if log:
                    log(
                        f"reconcile dry-run: {changeset_id} -> epic={candidate.epic_id}"
                        + (f" {candidate.triage_summary}" if candidate.triage_summary else "")
                        + (
                            f" integrated_sha={candidate.integrated_sha}"
                            if candidate.integrated_sha
                            else ""
                        )
                    )
                continue
            converged_updates: tuple[str, ...] = ()
            if candidate.terminal_pr_state is not None:
                try:
                    converged_updates = _converge_stale_terminal_metadata(
                        candidate,
                        beads_root=beads_root,
                        repo_root=repo_root,
                    )
                except (SystemExit, ValueError) as exc:
                    failed += 1
                    failed_ids.add(changeset_id)
                    if log:
                        log(
                            "reconcile anomaly: "
                            f"{changeset_id} -> epic={candidate.epic_id} "
                            "stale-terminal-metadata-convergence-failed"
                            f"(error={_format_lookup_error(str(exc))}) decision-required"
                        )
                    continue
            if candidate.status in {"closed", "done"}:
                beads.reconcile_closed_issue_exported_github_tickets(
                    changeset_id,
                    beads_root=beads_root,
                    cwd=repo_root,
                )
                if candidate.integrated_sha:
                    worker_store.update_changeset_integrated_sha(
                        changeset_id,
                        candidate.integrated_sha,
                        beads_root=beads_root,
                        repo_root=repo_root,
                    )
                if log:
                    log(
                        f"reconcile ok: {changeset_id} -> epic={candidate.epic_id} (already closed)"
                    )
                reconciled += 1
                reconciled_ids.add(changeset_id)
                epics_ready_to_finalize.add(candidate.epic_id)
                continue

            hook_agent_bead_id = resolve_hook_agent_bead_for_epic(
                candidate.epic_id,
                fallback_agent_bead_id=agent_bead_id,
                beads_root=beads_root,
                repo_root=repo_root,
            )
            finalize_result = finalize_changeset(
                changeset_id=candidate.issue_id,
                epic_id=candidate.epic_id,
                agent_id=agent_id,
                agent_bead_id=hook_agent_bead_id or "",
                started_at=started_at,
                repo_slug=repo_slug,
                beads_root=beads_root,
                repo_root=repo_root,
                branch_pr=project_config.branch.pr,
                branch_history=project_config.branch.history,
                branch_squash_message=project_config.branch.squash_message,
                project_data_dir=project_data_dir,
                git_path=git_path,
            )
            if not finalize_result.continue_running or "_blocked_" in finalize_result.reason:
                failed += 1
                failed_ids.add(changeset_id)
                if log:
                    log(
                        f"reconcile error: {changeset_id} "
                        f"(finalize reason={finalize_result.reason})"
                    )
                continue
            refreshed_issue: dict[str, object] | None = None
            if candidate.require_terminal_status or candidate.integrated_sha:
                issue_cache.pop(changeset_id, None)
                refreshed_issue = load_issue(changeset_id)
            if candidate.require_terminal_status:
                refreshed_status = (
                    _canonical_changeset_status(refreshed_issue) if refreshed_issue else None
                )
                if refreshed_status != "closed":
                    failed += 1
                    failed_ids.add(changeset_id)
                    if log:
                        log(
                            "reconcile anomaly: "
                            f"{changeset_id} -> epic={candidate.epic_id} "
                            + (
                                "stale-terminal-finalize-remained-non-terminal("
                                f"expected_pr_state={candidate.terminal_pr_state or 'none'}, "
                                f"status={refreshed_status or 'unknown'}, "
                                f"reason={finalize_result.reason}"
                                + (
                                    f",metadata={','.join(converged_updates)}"
                                    if converged_updates
                                    else ""
                                )
                                + ") decision-required"
                            )
                        )
                    continue
            if (
                candidate.integrated_sha
                and _converged_integrated_sha(converged_updates) is None
                and _recorded_integrated_sha(refreshed_issue or {}) is None
            ):
                worker_store.update_changeset_integrated_sha(
                    changeset_id,
                    candidate.integrated_sha,
                    beads_root=beads_root,
                    repo_root=repo_root,
                )
            if log:
                log(
                    f"reconcile ok: {changeset_id} -> epic={candidate.epic_id} "
                    f"(finalize reason={finalize_result.reason})"
                    + (f" {candidate.triage_summary}" if candidate.triage_summary else "")
                    + (f" metadata={','.join(converged_updates)}" if converged_updates else "")
                )
            reconciled += 1
            reconciled_ids.add(changeset_id)
        if not progressed:
            break

    for changeset_id in sorted(remaining):
        candidate = candidates[changeset_id]
        blockers: list[str] = []
        for dependency_id in candidate.dependency_ids:
            if dependency_id in reconciled_ids:
                continue
            if dependency_id in failed_ids:
                blockers.append(f"{dependency_id}(failed)")
                continue
            if dependency_id in candidates:
                blockers.append(dependency_id)
                continue
            if not dependency_finalized(dependency_id):
                blockers.append(dependency_id)
        failed += 1
        failed_ids.add(changeset_id)
        if log:
            if blockers:
                log(
                    f"reconcile error: {changeset_id} "
                    f"(blocked by dependencies: {', '.join(blockers)})"
                )
            else:
                log(f"reconcile error: {changeset_id} (dependency order unresolved)")

    if not dry_run:
        for epic_id in sorted(epics_ready_to_finalize):
            hook_agent_bead_id = resolve_hook_agent_bead_for_epic(
                epic_id,
                fallback_agent_bead_id=agent_bead_id,
                beads_root=beads_root,
                repo_root=repo_root,
            )
            epic_result = finalize_epic_if_complete(
                epic_id=epic_id,
                agent_id=agent_id,
                agent_bead_id=hook_agent_bead_id or "",
                branch_pr=project_config.branch.pr,
                branch_history=project_config.branch.history,
                branch_squash_message=project_config.branch.squash_message,
                beads_root=beads_root,
                repo_root=repo_root,
                project_data_dir=project_data_dir,
                git_path=git_path,
                log=log,
            )
            if "_blocked_" in epic_result.reason:
                failed += 1
                if log:
                    log(f"reconcile error: epic {epic_id} (finalize reason={epic_result.reason})")
                continue
            if log:
                log(f"reconcile epic: {epic_id} (finalize reason={epic_result.reason})")

    return ReconcileResult(
        scanned=scanned,
        actionable=actionable,
        reconciled=reconciled,
        failed=failed,
    )

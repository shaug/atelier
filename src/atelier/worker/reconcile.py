"""Worker reconcile helpers for merged changesets."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .. import beads, changesets, config, git, lifecycle, prs
from .models import FinalizeResult, ReconcileResult


@dataclass(frozen=True)
class ReconcileCandidate:
    issue_id: str
    issue: dict[str, object]
    status: str
    epic_id: str
    integrated_sha: str | None
    dependency_ids: tuple[str, ...]


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


def _live_review_state(
    issue: dict[str, object],
    *,
    repo_slug: str | None,
    repo_root: Path,
    git_path: str | None,
) -> str | None:
    if not repo_slug:
        return None
    work_branch = _changeset_work_branch(issue)
    if not work_branch:
        return None
    pushed = git.git_ref_exists(repo_root, f"refs/remotes/origin/{work_branch}", git_path=git_path)
    pr_payload = prs.read_github_pr_status(repo_slug, work_branch)
    review_requested = prs.has_review_requests(pr_payload)
    return prs.lifecycle_state(pr_payload, pushed=pushed, review_requested=review_requested)


def _review_drift_state(
    issue: dict[str, object],
    *,
    repo_slug: str | None,
    repo_root: Path,
    git_path: str | None,
) -> str | None:
    if _canonical_changeset_status(issue) != "closed":
        return None
    stored_state = _stored_review_state(issue)
    if stored_state in lifecycle.ACTIVE_REVIEW_STATES:
        return stored_state
    live_state = _live_review_state(
        issue,
        repo_slug=repo_slug,
        repo_root=repo_root,
        git_path=git_path,
    )
    if live_state in lifecycle.ACTIVE_REVIEW_STATES:
        return live_state
    return None


def _reopen_changeset_for_review(
    *,
    changeset_id: str,
    review_state: str,
    beads_root: Path,
    repo_root: Path,
) -> None:
    timestamp = dt.datetime.now(tz=dt.timezone.utc).isoformat()
    beads.run_bd_command(
        [
            "update",
            changeset_id,
            "--status",
            "in_progress",
            "--append-notes",
            (
                "reconcile_reopened_for_review: "
                f"{timestamp} state={review_state} source=closed_changeset_pr_drift"
            ),
        ],
        beads_root=beads_root,
        cwd=repo_root,
    )
    beads.update_changeset_review(
        changeset_id,
        changesets.ReviewMetadata(pr_state=review_state),
        beads_root=beads_root,
        cwd=repo_root,
    )


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

    candidates: dict[str, list[str]] = {}
    for issue in all_changesets:
        issue_id = issue.get("id")
        if not isinstance(issue_id, str) or not issue_id.strip():
            continue
        changeset_id = issue_id.strip()
        drift_state = _review_drift_state(
            issue,
            repo_slug=repo_slug,
            repo_root=repo_root,
            git_path=git_path,
        )
        if drift_state is None:
            status = _canonical_changeset_status(issue)
            if status not in {"open", "in_progress", "blocked", "closed"}:
                continue
            integration_proven, integrated_sha = changeset_integration_signal(
                issue, repo_slug=repo_slug, repo_root=repo_root, git_path=git_path
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
    reopened_drift_ids: set[str] = set()
    for issue in all_changesets:
        changeset_id = issue.get("id")
        if not isinstance(changeset_id, str) or not changeset_id.strip():
            continue
        changeset_id = changeset_id.strip()
        if changeset_filter is not None and changeset_id not in changeset_filter:
            continue
        if _canonical_changeset_status(issue) != "closed":
            continue
        drift_state = _review_drift_state(
            issue,
            repo_slug=repo_slug,
            repo_root=repo_root,
            git_path=git_path,
        )
        if drift_state is None:
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
        reopened_drift_ids.add(changeset_id)
        if dry_run:
            reconciled += 1
            if log:
                log(
                    "reconcile dry-run: "
                    f"{changeset_id} -> epic={epic_id} reopen(state={drift_state})"
                )
            continue
        _reopen_changeset_for_review(
            changeset_id=changeset_id,
            review_state=drift_state,
            beads_root=beads_root,
            repo_root=repo_root,
        )
        reconciled += 1
        if log:
            log(f"reconcile reopened: {changeset_id} -> epic={epic_id} (state={drift_state})")

    candidates: dict[str, ReconcileCandidate] = {}
    for issue in all_changesets:
        changeset_id = issue.get("id")
        if not isinstance(changeset_id, str) or not changeset_id.strip():
            continue
        changeset_id = changeset_id.strip()
        if changeset_id in reopened_drift_ids:
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
        integration_proven, integrated_sha = changeset_integration_signal(
            issue, repo_slug=repo_slug, repo_root=repo_root, git_path=git_path
        )
        if not integration_proven:
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
        loaded = beads.run_bd_json(["show", issue_id], beads_root=beads_root, cwd=repo_root)
        issue_cache[issue_id] = loaded[0] if loaded else None
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
        work_children = beads.list_work_children(
            issue_id,
            beads_root=beads_root,
            cwd=repo_root,
            include_closed=True,
        )
        if work_children:
            dependency_finalized_cache[issue_id] = True
            return True
        if _canonical_changeset_status(issue) != "closed":
            dependency_finalized_cache[issue_id] = False
            return False
        if (
            _review_drift_state(
                issue,
                repo_slug=repo_slug,
                repo_root=repo_root,
                git_path=git_path,
            )
            is not None
        ):
            dependency_finalized_cache[issue_id] = False
            return False
        integrated, _ = changeset_integration_signal(
            issue, repo_slug=repo_slug, repo_root=repo_root, git_path=git_path
        )
        if integrated:
            dependency_finalized_cache[issue_id] = True
            return True
        stored_state = _stored_review_state(issue)
        if stored_state in lifecycle.ACTIVE_REVIEW_STATES or stored_state in {"pushed", "merged"}:
            dependency_finalized_cache[issue_id] = False
            return False
        if stored_state not in {"closed", "abandoned"}:
            dependency_finalized_cache[issue_id] = False
            return False
        dependency_finalized_cache[issue_id] = True
        return True

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
                        + (
                            f" integrated_sha={candidate.integrated_sha}"
                            if candidate.integrated_sha
                            else ""
                        )
                    )
                continue
            if candidate.status in {"closed", "done"}:
                beads.reconcile_closed_issue_exported_github_tickets(
                    changeset_id,
                    beads_root=beads_root,
                    cwd=repo_root,
                )
                if candidate.integrated_sha:
                    beads.update_changeset_integrated_sha(
                        changeset_id,
                        candidate.integrated_sha,
                        beads_root=beads_root,
                        cwd=repo_root,
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
                branch_pr_strategy=project_config.branch.pr_strategy,
                branch_history=project_config.branch.history,
                branch_squash_message=project_config.branch.squash_message,
                project_data_dir=project_data_dir,
                git_path=git_path,
            )
            if "_blocked_" in finalize_result.reason:
                failed += 1
                failed_ids.add(changeset_id)
                if log:
                    log(
                        f"reconcile error: {changeset_id} "
                        f"(finalize reason={finalize_result.reason})"
                    )
                continue
            if candidate.integrated_sha:
                beads.update_changeset_integrated_sha(
                    changeset_id,
                    candidate.integrated_sha,
                    beads_root=beads_root,
                    cwd=repo_root,
                )
            if log:
                log(
                    f"reconcile ok: {changeset_id} -> epic={candidate.epic_id} "
                    f"(finalize reason={finalize_result.reason})"
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

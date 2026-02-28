"""Finalize/publish state helpers for worker runtime."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from pathlib import Path

from .. import (
    agents,
    beads,
    changeset_fields,
    changesets,
    dependency_lineage,
    exec,
    git,
    lifecycle,
    pr_strategy,
    prs,
)
from ..io import say
from ..models import BranchPrMode
from ..worker import finalization_service as worker_finalization_service
from ..worker import integration_service as worker_integration_service
from ..worker import publish as worker_publish
from ..worker import queueing as worker_queueing
from ..worker import reconcile_service as worker_reconcile_service
from ..worker.finalization import pr_gate as worker_pr_gate
from ..worker.finalization import recovery as worker_recovery
from ..worker.models import FinalizeResult
from .work_runtime_common import (
    dry_run_log,
    extract_workspace_parent_branch,
    issue_labels,
    issue_parent_id,
    parse_issue_time,
)


def send_planner_notification(
    *,
    subject: str,
    body: str,
    agent_id: str,
    thread_id: str | None,
    beads_root: Path,
    repo_root: Path,
    dry_run: bool,
) -> None:
    """Send planner notification.

    Args:
        subject: Value for `subject`.
        body: Value for `body`.
        agent_id: Value for `agent_id`.
        thread_id: Value for `thread_id`.
        beads_root: Value for `beads_root`.
        repo_root: Value for `repo_root`.
        dry_run: Value for `dry_run`.

    Returns:
        Function result.
    """
    worker_queueing.send_planner_notification(
        subject=subject,
        body=body,
        agent_id=agent_id,
        thread_id=thread_id,
        beads_root=beads_root,
        repo_root=repo_root,
        dry_run=dry_run,
        dry_run_log=dry_run_log,
    )


def send_no_ready_changesets(
    *,
    epic_id: str,
    agent_id: str,
    beads_root: Path,
    repo_root: Path,
    dry_run: bool,
) -> None:
    """Send no ready changesets.

    Args:
        epic_id: Value for `epic_id`.
        agent_id: Value for `agent_id`.
        beads_root: Value for `beads_root`.
        repo_root: Value for `repo_root`.
        dry_run: Value for `dry_run`.

    Returns:
        Function result.
    """
    worker_queueing.send_no_ready_changesets(
        epic_id=epic_id,
        agent_id=agent_id,
        beads_root=beads_root,
        repo_root=repo_root,
        dry_run=dry_run,
        dry_run_log=dry_run_log,
    )


def release_epic_assignment(epic_id: str, *, beads_root: Path, repo_root: Path) -> None:
    """Release epic assignment.

    Args:
        epic_id: Value for `epic_id`.
        beads_root: Value for `beads_root`.
        repo_root: Value for `repo_root`.

    Returns:
        Function result.
    """
    issues = beads.run_bd_json(["show", epic_id], beads_root=beads_root, cwd=repo_root)
    if not issues:
        return
    issue = issues[0]
    labels = issue_labels(issue)
    status = str(issue.get("status") or "")
    args = ["update", epic_id, "--assignee", ""]
    if "at:hooked" in labels:
        args.extend(["--remove-label", "at:hooked"])
    if status and status not in {"closed", "done"}:
        args.extend(["--status", "open"])
    beads.run_bd_command(args, beads_root=beads_root, cwd=repo_root, allow_failure=True)


def has_open_descendant_changesets(changeset_id: str, *, beads_root: Path, repo_root: Path) -> bool:
    """Has open descendant changesets.

    Args:
        changeset_id: Value for `changeset_id`.
        beads_root: Value for `beads_root`.
        repo_root: Value for `repo_root`.

    Returns:
        Function result.
    """
    descendants = beads.list_descendant_changesets(
        changeset_id,
        beads_root=beads_root,
        cwd=repo_root,
        include_closed=False,
    )
    return bool(descendants)


def is_changeset_in_progress(issue: dict[str, object]) -> bool:
    """Is changeset in progress.

    Args:
        issue: Value for `issue`.

    Returns:
        Function result.
    """
    return lifecycle.is_changeset_in_progress(issue.get("status"), issue_labels(issue))


def is_changeset_ready(
    issue: dict[str, object],
    *,
    has_work_children: bool = False,
) -> bool:
    """Is changeset ready.

    Call with has_work_children=False when issue is from list_descendant_changesets
    (leaf work beads). Fails closed when has_work_children is unknown.

    Args:
        issue: Value for `issue`.
        has_work_children: Whether the issue has child work beads.

    Returns:
        Function result.
    """
    return lifecycle.is_changeset_ready(
        issue.get("status"),
        issue_labels(issue),
        has_work_children=has_work_children,
        issue_type=lifecycle.issue_payload_type(issue),
        parent_id=issue_parent_id(issue),
    )


def changeset_review_state(issue: dict[str, object]) -> str | None:
    """Changeset review state.

    Args:
        issue: Value for `issue`.

    Returns:
        Function result.
    """
    return changeset_fields.review_state(issue)


def changeset_waiting_on_review(issue: dict[str, object]) -> bool:
    """Changeset waiting on review.

    Args:
        issue: Value for `issue`.

    Returns:
        Function result.
    """
    state = changeset_review_state(issue)
    if state is None:
        return False
    return state in {"pushed", "draft-pr", "pr-open", "in-review", "approved"}


def changeset_has_review_handoff_signal(
    issue: dict[str, object],
    *,
    repo_slug: str | None,
    repo_root: Path,
    branch_pr: bool,
    git_path: str | None,
) -> bool:
    """Return whether a changeset has deterministic review handoff evidence.

    Args:
        issue: Changeset issue payload.
        repo_slug: Optional GitHub owner/repo slug.
        repo_root: Repository checkout path.
        branch_pr: Whether PR mode is enabled for the project.
        git_path: Optional git binary path override.

    Returns:
        ``True`` when the changeset has a pushed remote branch and/or open PR
        lifecycle signal that indicates review handoff.
    """
    if not branch_pr:
        return False
    work_branch = changeset_work_branch(issue)
    if not work_branch:
        return False
    pushed = git.git_ref_exists(repo_root, f"refs/remotes/origin/{work_branch}", git_path=git_path)
    pr_payload = lookup_pr_payload(repo_slug, work_branch)
    review_requested = prs.has_review_requests(pr_payload)
    state = prs.lifecycle_state(pr_payload, pushed=pushed, review_requested=review_requested)
    return state in {"pushed", "draft-pr", "pr-open", "in-review", "approved"}


def changeset_work_branch(issue: dict[str, object]) -> str | None:
    """Changeset work branch.

    Args:
        issue: Value for `issue`.

    Returns:
        Function result.
    """
    return changeset_fields.work_branch(issue)


def changeset_pr_url(issue: dict[str, object]) -> str | None:
    """Changeset pr url.

    Args:
        issue: Value for `issue`.

    Returns:
        Function result.
    """
    return changeset_fields.pr_url(issue)


def lookup_pr_payload(repo_slug: str | None, branch: str) -> dict[str, object] | None:
    """Lookup PR payload for a branch.

    Args:
        repo_slug: GitHub owner/repo slug.
        branch: Branch name used for PR lookup.

    Returns:
        PR payload when found, otherwise ``None``.
    """
    if not repo_slug:
        return None
    return prs.read_github_pr_status(repo_slug, branch)


def lookup_pr_payload_diagnostic(
    repo_slug: str | None, branch: str
) -> tuple[dict[str, object] | None, str | None]:
    """Lookup PR payload with explicit query-failure diagnostics.

    Args:
        repo_slug: GitHub owner/repo slug.
        branch: Branch name used for PR lookup.

    Returns:
        Tuple containing payload and optional diagnostic message.
    """
    if not repo_slug:
        return None, None
    lookup = prs.lookup_github_pr_status(repo_slug, branch, refresh=True)
    if lookup.found:
        return lookup.payload, None
    if lookup.failed:
        error = lookup.error or "unknown gh error"
        if error.startswith("missing required command: gh"):
            return None, None
        return None, error
    return None, None


def changeset_root_branch(issue: dict[str, object]) -> str | None:
    """Changeset root branch.

    Args:
        issue: Value for `issue`.

    Returns:
        Function result.
    """
    return changeset_fields.root_branch(issue)


def _normalize_branch(value: object) -> str:
    if not isinstance(value, str):
        return ""
    normalized = value.strip()
    if not normalized or normalized.lower() == "null":
        return ""
    return normalized


def _resolve_parent_lineage(
    issue: dict[str, object],
    *,
    root_branch: str,
    beads_root: Path | None,
    repo_root: Path,
) -> dependency_lineage.ParentLineageResolution:
    issue_cache: dict[str, dict[str, object] | None] = {}

    def lookup_dependency_issue(issue_id: str) -> dict[str, object] | None:
        if beads_root is None:
            return None
        if issue_id in issue_cache:
            return issue_cache[issue_id]
        issues = beads.run_bd_json(["show", issue_id], beads_root=beads_root, cwd=repo_root)
        issue_cache[issue_id] = issues[0] if issues else None
        return issue_cache[issue_id]

    return dependency_lineage.resolve_parent_lineage(
        issue,
        root_branch=root_branch,
        lookup_issue=lookup_dependency_issue,
    )


def _resolve_workspace_parent_branch(
    issue: dict[str, object],
    *,
    root_branch: str,
    parent_branch: str,
    workspace_parent_branch: str,
    beads_root: Path | None,
    repo_root: Path,
) -> str:
    resolved_workspace_parent = _normalize_branch(workspace_parent_branch)
    if resolved_workspace_parent:
        return resolved_workspace_parent
    if beads_root is None:
        return ""
    if not root_branch or not parent_branch:
        return ""
    if root_branch != parent_branch:
        return ""
    epic_id = resolve_epic_id_for_changeset(issue, beads_root=beads_root, repo_root=repo_root)
    if not epic_id:
        return ""
    epic_issues = beads.run_bd_json(["show", epic_id], beads_root=beads_root, cwd=repo_root)
    if not epic_issues:
        return ""
    return _normalize_branch(extract_workspace_parent_branch(epic_issues[0]))


def _resolve_non_root_default_branch(
    *, root_branch: str, repo_root: Path, git_path: str | None
) -> str:
    default_branch = _normalize_branch(git.git_default_branch(repo_root, git_path=git_path))
    if not default_branch:
        return ""
    if root_branch and default_branch == root_branch:
        return ""
    return default_branch


def _branch_integrated_into(
    branch: str, target_branch: str, *, repo_root: Path, git_path: str | None
) -> bool:
    branch_ref = branch_ref_for_lookup(repo_root, branch, git_path=git_path)
    target_ref = branch_ref_for_lookup(repo_root, target_branch, git_path=git_path)
    if not target_ref:
        return False
    if not branch_ref:
        # Branch is already gone; treat this as integrated lineage.
        return True
    if git.git_is_ancestor(repo_root, branch_ref, target_ref, git_path=git_path) is True:
        return True
    return (
        git.git_branch_fully_applied(repo_root, target_ref, branch_ref, git_path=git_path) is True
    )


def _lookup_no_pr_payload(_repo_slug: str | None, _branch: str) -> dict[str, object] | None:
    return None


def _dependencies_integrated(
    dependency_ids: tuple[str, ...],
    *,
    repo_slug: str | None,
    beads_root: Path | None,
    repo_root: Path,
    git_path: str | None,
    lookup_pr_payload_fn: Callable[[str | None, str], dict[str, object] | None],
) -> bool:
    if beads_root is None:
        return False
    for dependency_id in dependency_ids:
        dependency_issues = beads.run_bd_json(
            ["show", dependency_id], beads_root=beads_root, cwd=repo_root
        )
        if not dependency_issues:
            return False
        dependency_issue = dependency_issues[0]
        integrated, _ = worker_integration_service.changeset_integration_signal(
            dependency_issue,
            repo_slug=repo_slug,
            repo_root=repo_root,
            lookup_pr_payload=lookup_pr_payload_fn,
            git_path=git_path,
        )
        if not integrated:
            return False
    return True


def changeset_base_branch(
    issue: dict[str, object],
    *,
    branch_pr_strategy: object | None = None,
    repo_slug: str | None = None,
    beads_root: Path | None = None,
    repo_root: Path,
    git_path: str | None,
    lookup_pr_payload_fn: Callable[[str | None, str], dict[str, object] | None] = lookup_pr_payload,
    update_metadata: bool = True,
) -> str | None:
    """Changeset base branch.

    Args:
        issue: Value for `issue`.
        beads_root: Value for `beads_root`.
        repo_root: Value for `repo_root`.
        git_path: Value for `git_path`.

    Returns:
        Function result.
    """
    description = issue.get("description")
    fields = beads.parse_description_fields(description if isinstance(description, str) else "")
    root_branch = _normalize_branch(changeset_root_branch(issue))
    lineage = _resolve_parent_lineage(
        issue,
        root_branch=root_branch,
        beads_root=beads_root,
        repo_root=repo_root,
    )
    parent_branch = _normalize_branch(lineage.effective_parent_branch)
    raw_parent_branch = parent_branch
    workspace_parent_branch = _resolve_workspace_parent_branch(
        issue,
        root_branch=root_branch,
        parent_branch=parent_branch,
        workspace_parent_branch=str(fields.get("workspace.parent_branch") or ""),
        beads_root=beads_root,
        repo_root=repo_root,
    )
    if workspace_parent_branch and root_branch and workspace_parent_branch == root_branch:
        workspace_parent_branch = ""
    default_parent_branch = ""
    if (
        not lineage.blocked
        and not workspace_parent_branch
        and (not parent_branch or (root_branch and parent_branch == root_branch))
    ):
        default_parent_branch = _resolve_non_root_default_branch(
            root_branch=root_branch,
            repo_root=repo_root,
            git_path=git_path,
        )
    integration_parent_branch = workspace_parent_branch or default_parent_branch
    normalized_strategy = (
        pr_strategy.normalize_pr_strategy(branch_pr_strategy)
        if branch_pr_strategy is not None
        else None
    )
    if normalized_strategy == "sequential":
        if integration_parent_branch:
            changeset_id = issue.get("id")
            if (
                update_metadata
                and beads_root is not None
                and isinstance(changeset_id, str)
                and changeset_id
            ):
                root_base = (
                    git.git_rev_parse(repo_root, root_branch, git_path=git_path)
                    if root_branch
                    else None
                )
                parent_base = git.git_rev_parse(
                    repo_root,
                    integration_parent_branch,
                    git_path=git_path,
                )
                beads.update_changeset_branch_metadata(
                    changeset_id,
                    root_branch=root_branch,
                    parent_branch=integration_parent_branch,
                    work_branch=changeset_work_branch(issue),
                    root_base=root_base,
                    parent_base=parent_base,
                    beads_root=beads_root,
                    cwd=repo_root,
                    allow_override=True,
                )
            return integration_parent_branch
        if root_branch:
            return None
        return _resolve_non_root_default_branch(
            root_branch="", repo_root=repo_root, git_path=git_path
        )
    if lineage.blocked:
        if not (
            lineage.dependency_ids
            and integration_parent_branch
            and _dependencies_integrated(
                lineage.dependency_ids,
                repo_slug=repo_slug,
                beads_root=beads_root,
                repo_root=repo_root,
                git_path=git_path,
                lookup_pr_payload_fn=lookup_pr_payload_fn,
            )
        ):
            return None
        changeset_id = issue.get("id")
        if (
            update_metadata
            and beads_root is not None
            and isinstance(changeset_id, str)
            and changeset_id
        ):
            root_base = (
                git.git_rev_parse(repo_root, root_branch, git_path=git_path)
                if root_branch
                else None
            )
            parent_base = git.git_rev_parse(
                repo_root,
                integration_parent_branch,
                git_path=git_path,
            )
            beads.update_changeset_branch_metadata(
                changeset_id,
                root_branch=root_branch,
                parent_branch=integration_parent_branch,
                work_branch=changeset_work_branch(issue),
                root_base=root_base,
                parent_base=parent_base,
                beads_root=beads_root,
                cwd=repo_root,
                allow_override=True,
            )
        return integration_parent_branch
    if (
        update_metadata
        and beads_root is not None
        and lineage.used_dependency_parent
        and lineage.dependency_parent_branch
    ):
        changeset_id = issue.get("id")
        if isinstance(changeset_id, str) and changeset_id:
            root_base = (
                git.git_rev_parse(repo_root, root_branch, git_path=git_path)
                if root_branch
                else None
            )
            parent_base = git.git_rev_parse(
                repo_root, lineage.dependency_parent_branch, git_path=git_path
            )
            beads.update_changeset_branch_metadata(
                changeset_id,
                root_branch=root_branch,
                parent_branch=lineage.dependency_parent_branch,
                work_branch=changeset_work_branch(issue),
                root_base=root_base,
                parent_base=parent_base,
                beads_root=beads_root,
                cwd=repo_root,
                allow_override=True,
            )
    collapsed_parent_normalized = bool(
        raw_parent_branch
        and root_branch
        and raw_parent_branch == root_branch
        and integration_parent_branch
    )
    if collapsed_parent_normalized and integration_parent_branch:
        parent_branch = integration_parent_branch
        changeset_id = issue.get("id")
        if (
            update_metadata
            and beads_root is not None
            and isinstance(changeset_id, str)
            and changeset_id
        ):
            root_base = (
                git.git_rev_parse(repo_root, root_branch, git_path=git_path)
                if root_branch
                else None
            )
            parent_base = git.git_rev_parse(
                repo_root,
                integration_parent_branch,
                git_path=git_path,
            )
            beads.update_changeset_branch_metadata(
                changeset_id,
                root_branch=root_branch,
                parent_branch=integration_parent_branch,
                work_branch=changeset_work_branch(issue),
                root_base=root_base,
                parent_base=parent_base,
                beads_root=beads_root,
                cwd=repo_root,
                allow_override=True,
            )

    if parent_branch and integration_parent_branch and parent_branch != integration_parent_branch:
        if _branch_integrated_into(
            parent_branch,
            integration_parent_branch,
            repo_root=repo_root,
            git_path=git_path,
        ):
            changeset_id = issue.get("id")
            if (
                update_metadata
                and beads_root is not None
                and isinstance(changeset_id, str)
                and changeset_id
            ):
                root_base = (
                    git.git_rev_parse(repo_root, root_branch, git_path=git_path)
                    if root_branch
                    else None
                )
                parent_base = git.git_rev_parse(
                    repo_root,
                    integration_parent_branch,
                    git_path=git_path,
                )
                beads.update_changeset_branch_metadata(
                    changeset_id,
                    root_branch=root_branch,
                    parent_branch=integration_parent_branch,
                    work_branch=changeset_work_branch(issue),
                    root_base=root_base,
                    parent_base=parent_base,
                    beads_root=beads_root,
                    cwd=repo_root,
                    allow_override=True,
                )
            return integration_parent_branch
    if parent_branch:
        if root_branch and parent_branch == root_branch:
            return None
        return parent_branch
    if integration_parent_branch:
        return integration_parent_branch
    if root_branch:
        return None
    return _resolve_non_root_default_branch(root_branch="", repo_root=repo_root, git_path=git_path)


def align_existing_pr_base(
    *,
    issue: dict[str, object],
    changeset_id: str,
    pr_payload: dict[str, object],
    repo_slug: str,
    beads_root: Path,
    repo_root: Path,
    git_path: str | None,
    branch_pr_strategy: object | None = None,
) -> tuple[bool, str | None]:
    """Align an existing PR base to the expected changeset parent lineage.

    Args:
        issue: Value for ``issue``.
        changeset_id: Value for ``changeset_id``.
        pr_payload: Value for ``pr_payload``.
        repo_slug: Value for ``repo_slug``.
        beads_root: Value for ``beads_root``.
        repo_root: Value for ``repo_root``.
        git_path: Value for ``git_path``.

    Returns:
        Tuple of ``(ok, detail)``. ``detail`` contains remediation or update
        notes when present.
    """

    def run_git(args: list[str]) -> tuple[bool, str]:
        result = exec.try_run_command(
            git.git_command(["-C", str(repo_root), *args], git_path=git_path)
        )
        if result is None:
            return False, "missing required command: git"
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            return False, detail or f"command failed: git {' '.join(args)}"
        return True, (result.stdout or "").strip()

    def ensure_local_branch(branch: str) -> tuple[bool, str | None]:
        local_ref = f"refs/heads/{branch}"
        if git.git_ref_exists(repo_root, local_ref, git_path=git_path):
            return True, None
        remote_ref = f"refs/remotes/origin/{branch}"
        if not git.git_ref_exists(repo_root, remote_ref, git_path=git_path):
            return False, f"missing local/remote branch ref for {branch!r}"
        ok, detail = run_git(["branch", branch, f"origin/{branch}"])
        if not ok:
            return False, detail
        return True, None

    expected_base = changeset_base_branch(
        issue,
        branch_pr_strategy=branch_pr_strategy,
        repo_slug=repo_slug,
        beads_root=beads_root,
        repo_root=repo_root,
        git_path=git_path,
        lookup_pr_payload_fn=lookup_pr_payload,
    )
    expected_branch = _normalize_branch(expected_base)
    if not expected_branch:
        return False, "unable to resolve expected PR base branch"

    boundary = prs.parse_pr_boundary(pr_payload, source=f"align_existing_pr_base:{changeset_id}")
    if boundary is None:
        return False, "missing PR payload"
    actual_branch = _normalize_branch(boundary.base_ref_name)
    if not actual_branch:
        return False, "PR payload missing baseRefName"
    if actual_branch == expected_branch:
        return True, None

    work_branch = _normalize_branch(changeset_work_branch(issue))
    if not work_branch:
        return False, "missing changeset.work_branch metadata for PR base alignment"

    clean = git.git_is_clean(repo_root, git_path=git_path)
    if clean is False:
        return False, "repository must be clean before PR base alignment"
    if clean is None:
        return False, "unable to determine repository clean status before base alignment"

    ok, detail = ensure_local_branch(work_branch)
    if not ok:
        return False, detail
    ok, detail = ensure_local_branch(expected_branch)
    if not ok:
        return False, detail

    rebased = False
    rebase_source_ref = branch_ref_for_lookup(repo_root, actual_branch, git_path=git_path)
    current_branch = git.git_current_branch(repo_root, git_path=git_path)
    if rebase_source_ref:
        ok, detail = run_git(["checkout", work_branch])
        if not ok:
            return False, detail
        ok, detail = run_git(["rebase", "--onto", expected_branch, rebase_source_ref, work_branch])
        if not ok:
            run_git(["rebase", "--abort"])
            if current_branch and current_branch != work_branch:
                run_git(["checkout", current_branch])
            return False, f"failed to restack {work_branch} onto {expected_branch}: {detail}"
        rebased = True
        if current_branch and current_branch != work_branch:
            run_git(["checkout", current_branch])
        ok, detail = run_git(["push", "--force-with-lease", "origin", work_branch])
        if not ok:
            return False, f"failed to force-push restacked branch {work_branch}: {detail}"

    pr_number = boundary.number
    if pr_number is None:
        return False, "PR payload missing number for base retarget"
    edit_result = exec.try_run_command(
        [
            "gh",
            "pr",
            "edit",
            str(pr_number),
            "--repo",
            repo_slug,
            "--base",
            expected_branch,
        ]
    )
    if edit_result is None:
        return False, "missing required command: gh"
    if edit_result.returncode != 0:
        detail = (edit_result.stderr or edit_result.stdout or "").strip()
        return False, detail or "gh pr edit failed"

    root_branch = changeset_root_branch(issue)
    parent_base = git.git_rev_parse(repo_root, expected_branch, git_path=git_path)
    root_base = (
        git.git_rev_parse(repo_root, root_branch, git_path=git_path) if root_branch else None
    )
    beads.update_changeset_branch_metadata(
        changeset_id,
        root_branch=root_branch,
        parent_branch=expected_branch,
        work_branch=work_branch,
        root_base=root_base,
        parent_base=parent_base,
        beads_root=beads_root,
        cwd=repo_root,
        allow_override=True,
    )
    detail_message = (
        f"PR base mismatch corrected for {changeset_id}: "
        f"expected={expected_branch}, actual={actual_branch}; "
        f"{'restacked and retargeted' if rebased else 'retargeted'}."
    )
    beads.run_bd_command(
        ["update", changeset_id, "--append-notes", f"publish_info: {detail_message}"],
        beads_root=beads_root,
        cwd=repo_root,
        allow_failure=True,
    )
    return True, detail_message


def render_changeset_pr_body(issue: dict[str, object]) -> str:
    """Render changeset pr body.

    Args:
        issue: Value for `issue`.

    Returns:
        Function result.
    """
    description = issue.get("description")
    fields = beads.parse_description_fields(description if isinstance(description, str) else "")
    return worker_publish.render_changeset_pr_body(issue, fields=fields)


_DEFAULT_CHANGESET_BASE_BRANCH = changeset_base_branch
_DEFAULT_RENDER_CHANGESET_PR_BODY = render_changeset_pr_body


def attempt_create_pr(
    *,
    repo_slug: str,
    issue: dict[str, object],
    work_branch: str,
    is_draft: bool,
    branch_pr_strategy: object = pr_strategy.PR_STRATEGY_DEFAULT,
    beads_root: Path,
    repo_root: Path,
    git_path: str | None,
    changeset_base_branch: Callable[..., str | None] | None = None,
    render_changeset_pr_body: Callable[[dict[str, object]], str] | None = None,
    changeset_base_branch_fn: Callable[..., str | None] | None = None,
    render_changeset_pr_body_fn: Callable[[dict[str, object]], str] | None = None,
) -> tuple[bool, str]:
    """Attempt create PR.

    Args:
        repo_slug: Value for `repo_slug`.
        issue: Value for `issue`.
        work_branch: Value for `work_branch`.
        is_draft: Whether to create a draft PR.
        branch_pr_strategy: PR strategy used to resolve PR base policy.
        beads_root: Value for `beads_root`.
        repo_root: Value for `repo_root`.
        git_path: Value for `git_path`.
        changeset_base_branch: Value for `changeset_base_branch`.
        render_changeset_pr_body: Value for `render_changeset_pr_body`.
        changeset_base_branch_fn: Value for `changeset_base_branch_fn`.
        render_changeset_pr_body_fn: Value for `render_changeset_pr_body_fn`.

    Returns:
        Function result.
    """
    return worker_pr_gate.attempt_create_pr(
        repo_slug=repo_slug,
        issue=issue,
        work_branch=work_branch,
        is_draft=is_draft,
        branch_pr_strategy=branch_pr_strategy,
        beads_root=beads_root,
        repo_root=repo_root,
        git_path=git_path,
        changeset_base_branch=(
            changeset_base_branch or changeset_base_branch_fn or _DEFAULT_CHANGESET_BASE_BRANCH
        ),
        render_changeset_pr_body=(
            render_changeset_pr_body
            or render_changeset_pr_body_fn
            or _DEFAULT_RENDER_CHANGESET_PR_BODY
        ),
    )


def attempt_create_draft_pr(
    *,
    repo_slug: str,
    issue: dict[str, object],
    work_branch: str,
    branch_pr_strategy: object = pr_strategy.PR_STRATEGY_DEFAULT,
    beads_root: Path,
    repo_root: Path,
    git_path: str | None,
    changeset_base_branch: Callable[..., str | None] | None = None,
    render_changeset_pr_body: Callable[[dict[str, object]], str] | None = None,
    changeset_base_branch_fn: Callable[..., str | None] | None = None,
    render_changeset_pr_body_fn: Callable[[dict[str, object]], str] | None = None,
) -> tuple[bool, str]:
    """Backward-compatible wrapper around ``attempt_create_pr``.

    Args:
        repo_slug: Repository owner/name slug.
        issue: Changeset issue payload.
        work_branch: Work branch to open the PR from.
        branch_pr_strategy: PR strategy used to resolve PR base policy.
        beads_root: Beads root path.
        repo_root: Repository root path.
        git_path: Optional git executable path override.
        changeset_base_branch: Optional base-branch resolver.
        render_changeset_pr_body: Optional PR body renderer.
        changeset_base_branch_fn: Legacy alias for base-branch resolver.
        render_changeset_pr_body_fn: Legacy alias for PR body renderer.

    Returns:
        Tuple of ``(created, detail)`` from PR creation.
    """
    return attempt_create_pr(
        repo_slug=repo_slug,
        issue=issue,
        work_branch=work_branch,
        is_draft=True,
        branch_pr_strategy=branch_pr_strategy,
        beads_root=beads_root,
        repo_root=repo_root,
        git_path=git_path,
        changeset_base_branch=changeset_base_branch,
        render_changeset_pr_body=render_changeset_pr_body,
        changeset_base_branch_fn=changeset_base_branch_fn,
        render_changeset_pr_body_fn=render_changeset_pr_body_fn,
    )


def set_changeset_review_pending_state(
    *,
    changeset_id: str,
    pr_payload: dict[str, object] | None,
    pushed: bool,
    fallback_pr_state: str | None,
    beads_root: Path,
    repo_root: Path,
) -> None:
    """Set changeset review pending state.

    Args:
        changeset_id: Value for `changeset_id`.
        pr_payload: Value for `pr_payload`.
        pushed: Value for `pushed`.
        fallback_pr_state: Value for `fallback_pr_state`.
        beads_root: Value for `beads_root`.
        repo_root: Value for `repo_root`.

    Returns:
        Function result.
    """
    worker_pr_gate.set_changeset_review_pending_state(
        changeset_id=changeset_id,
        pr_payload=pr_payload,
        pushed=pushed,
        fallback_pr_state=fallback_pr_state,
        beads_root=beads_root,
        repo_root=repo_root,
        mark_changeset_in_progress=mark_changeset_in_progress,
        update_changeset_review_from_pr=update_changeset_review_from_pr,
    )


def update_changeset_review_from_pr(
    changeset_id: str,
    *,
    pr_payload: dict[str, object] | None,
    pushed: bool,
    beads_root: Path,
    repo_root: Path,
) -> None:
    """Update changeset review from pr.

    Args:
        changeset_id: Value for `changeset_id`.
        pr_payload: Value for `pr_payload`.
        pushed: Value for `pushed`.
        beads_root: Value for `beads_root`.
        repo_root: Value for `repo_root`.

    Returns:
        Function result.
    """
    if not pr_payload:
        return
    review_requested = prs.has_review_requests(pr_payload)
    lifecycle = prs.lifecycle_state(pr_payload, pushed=pushed, review_requested=review_requested)
    metadata = changesets.ReviewMetadata(
        pr_url=str(pr_payload.get("url") or "") or None,
        pr_number=str(pr_payload.get("number") or "") or None,
        pr_state=lifecycle,
    )
    beads.update_changeset_review(
        changeset_id,
        metadata,
        beads_root=beads_root,
        cwd=repo_root,
    )


def handle_pushed_without_pr(
    *,
    issue: dict[str, object],
    changeset_id: str,
    agent_id: str,
    repo_slug: str | None,
    repo_root: Path,
    beads_root: Path,
    branch_pr_strategy: object,
    git_path: str | None,
    create_as_draft: bool = True,
    create_detail_prefix: str | None = None,
) -> FinalizeResult:
    """Handle pushed without pr.

    Args:
        issue: Value for `issue`.
        changeset_id: Value for `changeset_id`.
        agent_id: Value for `agent_id`.
        repo_slug: Value for `repo_slug`.
        repo_root: Value for `repo_root`.
        beads_root: Value for `beads_root`.
        branch_pr_strategy: Value for `branch_pr_strategy`.
        git_path: Value for `git_path`.
        create_as_draft: Whether PR creation should use draft mode.
        create_detail_prefix: Value for `create_detail_prefix`.

    Returns:
        Function result.
    """
    gate_result = worker_pr_gate.handle_pushed_without_pr(
        issue=issue,
        changeset_id=changeset_id,
        agent_id=agent_id,
        repo_slug=repo_slug,
        repo_root=repo_root,
        beads_root=beads_root,
        branch_pr_strategy=branch_pr_strategy,
        git_path=git_path,
        create_as_draft=create_as_draft,
        create_detail_prefix=create_detail_prefix,
        changeset_base_branch=changeset_base_branch,
        changeset_work_branch=changeset_work_branch,
        render_changeset_pr_body=render_changeset_pr_body,
        lookup_pr_payload=lookup_pr_payload,
        lookup_pr_payload_diagnostic=lookup_pr_payload_diagnostic,
        mark_changeset_in_progress=mark_changeset_in_progress,
        send_planner_notification=send_planner_notification,
        update_changeset_review_from_pr=update_changeset_review_from_pr,
        emit=say,
        attempt_create_pr_fn=attempt_create_pr,
    )
    return gate_result.finalize_result


def _reconcile_parent_review_state(
    *,
    parent_issue: dict[str, object],
    parent_issue_id: str,
    parent_payload: dict[str, object] | None,
    parent_state: str,
    pushed: bool,
    beads_root: Path,
    repo_root: Path,
) -> None:
    if parent_payload:
        update_changeset_review_from_pr(
            parent_issue_id,
            pr_payload=parent_payload,
            pushed=pushed,
            beads_root=beads_root,
            repo_root=repo_root,
        )
        return
    parent_description = parent_issue.get("description")
    existing = changesets.parse_review_metadata(
        parent_description if isinstance(parent_description, str) else ""
    )
    beads.update_changeset_review(
        parent_issue_id,
        changesets.ReviewMetadata(
            pr_url=None if parent_state == "pushed" else existing.pr_url,
            pr_number=None if parent_state == "pushed" else existing.pr_number,
            pr_state=parent_state,
            review_owner=existing.review_owner,
        ),
        beads_root=beads_root,
        cwd=repo_root,
    )


def changeset_stack_integrity_preflight(
    issue: dict[str, object],
    *,
    repo_slug: str | None,
    repo_root: Path,
    git_path: str | None,
    branch_pr_strategy: object,
    beads_root: Path | None = None,
) -> worker_pr_gate.StackIntegrityPreflightResult:
    """Run sequential stack-integrity preflight for a changeset issue.

    Args:
        issue: Changeset issue payload.
        repo_slug: Optional GitHub owner/repo slug.
        repo_root: Repository checkout path.
        git_path: Optional git executable override.
        branch_pr_strategy: Configured PR strategy value.
        beads_root: Optional Beads root for dependency issue lookups.

    Returns:
        Preflight result describing whether stack integrity passed.
    """
    preflight = worker_pr_gate.sequential_stack_integrity_preflight(
        issue,
        repo_slug=repo_slug,
        repo_root=repo_root,
        git_path=git_path,
        branch_pr_strategy=branch_pr_strategy,
        beads_root=beads_root,
        lookup_pr_payload=lookup_pr_payload,
        lookup_pr_payload_diagnostic=lookup_pr_payload_diagnostic,
        reconcile_parent_review_state=(
            (
                lambda **kwargs: _reconcile_parent_review_state(
                    beads_root=beads_root,
                    repo_root=repo_root,
                    **kwargs,
                )
            )
            if beads_root is not None
            else None
        ),
    )
    normalized_strategy = pr_strategy.normalize_pr_strategy(branch_pr_strategy)
    if normalized_strategy != "sequential" or not preflight.ok:
        return preflight

    description = issue.get("description")
    fields = beads.parse_description_fields(description if isinstance(description, str) else "")
    policy_lineage = dependency_lineage.resolve_parent_lineage(
        issue,
        root_branch=fields.get("changeset.root_branch"),
        lookup_issue=lambda _issue_id: None,
    )
    if policy_lineage.dependency_ids and not preflight.dependencies_integrated:
        return preflight
    root_branch = _normalize_branch(changeset_root_branch(issue))
    parent_branch = _normalize_branch(changeset_fields.parent_branch(issue))
    workspace_parent_branch = _resolve_workspace_parent_branch(
        issue,
        root_branch=root_branch,
        parent_branch=parent_branch,
        workspace_parent_branch=str(fields.get("workspace.parent_branch") or ""),
        beads_root=beads_root,
        repo_root=repo_root,
    )
    if workspace_parent_branch and root_branch and workspace_parent_branch == root_branch:
        workspace_parent_branch = ""
    integration_parent_branch = workspace_parent_branch or _resolve_non_root_default_branch(
        root_branch=root_branch,
        repo_root=repo_root,
        git_path=git_path,
    )
    if not integration_parent_branch:
        return preflight

    resolved_base_branch = _normalize_branch(
        changeset_base_branch(
            issue,
            branch_pr_strategy=normalized_strategy,
            repo_slug=repo_slug,
            beads_root=beads_root,
            repo_root=repo_root,
            git_path=git_path,
            update_metadata=False,
        )
    )
    if resolved_base_branch == integration_parent_branch:
        return preflight

    return worker_pr_gate.StackIntegrityPreflightResult(
        ok=False,
        reason="sequential-base-policy-mismatch",
        detail=(
            "sequential PR base policy violation: "
            f"expected epic parent branch {integration_parent_branch!r}, "
            f"computed base {resolved_base_branch or None!r}"
        ),
        remediation=(
            "Set sequential PR base metadata to the epic parent branch and rerun finalize."
        ),
    )


def changeset_parent_lifecycle_state(
    issue: dict[str, object],
    *,
    repo_slug: str | None,
    repo_root: Path,
    git_path: str | None,
) -> str | None:
    """Changeset parent lifecycle state.

    Args:
        issue: Value for `issue`.
        repo_slug: Value for `repo_slug`.
        repo_root: Value for `repo_root`.
        git_path: Value for `git_path`.

    Returns:
        Function result.
    """
    return worker_pr_gate.changeset_parent_lifecycle_state(
        issue,
        repo_slug=repo_slug,
        repo_root=repo_root,
        git_path=git_path,
        beads_root=None,
        lookup_pr_payload=lookup_pr_payload,
    )


def changeset_pr_creation_decision(
    issue: dict[str, object],
    *,
    repo_slug: str | None,
    repo_root: Path,
    git_path: str | None,
    branch_pr_strategy: object,
) -> pr_strategy.PrStrategyDecision:
    """Changeset pr creation decision.

    Args:
        issue: Value for `issue`.
        repo_slug: Value for `repo_slug`.
        repo_root: Value for `repo_root`.
        git_path: Value for `git_path`.
        branch_pr_strategy: Value for `branch_pr_strategy`.

    Returns:
        Function result.
    """
    return worker_pr_gate.changeset_pr_creation_decision(
        issue,
        repo_slug=repo_slug,
        repo_root=repo_root,
        git_path=git_path,
        branch_pr_strategy=branch_pr_strategy,
        beads_root=None,
        lookup_pr_payload=lookup_pr_payload,
    )


def recover_premature_merged_changeset(
    *,
    issue: dict[str, object],
    changeset_id: str,
    epic_id: str,
    agent_id: str,
    agent_bead_id: str | None,
    branch_pr: bool,
    branch_pr_mode: BranchPrMode,
    branch_history: str,
    branch_squash_message: str,
    branch_pr_strategy: pr_strategy.PrStrategy,
    repo_slug: str | None,
    beads_root: Path,
    repo_root: Path,
    project_data_dir: Path,
    squash_message_agent_spec: agents.AgentSpec | None,
    squash_message_agent_options: list[str],
    squash_message_agent_home: Path | None,
    squash_message_agent_env: dict[str, str] | None,
    git_path: str | None,
) -> FinalizeResult | None:
    """Recover premature merged changeset.

    Args:
        issue: Value for `issue`.
        changeset_id: Value for `changeset_id`.
        epic_id: Value for `epic_id`.
        agent_id: Value for `agent_id`.
        agent_bead_id: Value for `agent_bead_id`.
        branch_pr: Value for `branch_pr`.
        branch_pr_mode: Value for `branch_pr_mode`.
        branch_history: Value for `branch_history`.
        branch_squash_message: Value for `branch_squash_message`.
        branch_pr_strategy: Value for `branch_pr_strategy`.
        repo_slug: Value for `repo_slug`.
        beads_root: Value for `beads_root`.
        repo_root: Value for `repo_root`.
        project_data_dir: Value for `project_data_dir`.
        squash_message_agent_spec: Value for `squash_message_agent_spec`.
        squash_message_agent_options: Value for `squash_message_agent_options`.
        squash_message_agent_home: Value for `squash_message_agent_home`.
        squash_message_agent_env: Value for `squash_message_agent_env`.
        git_path: Value for `git_path`.

    Returns:
        Function result.
    """
    from .work_finalization_integration import finalize_terminal_changeset

    return worker_recovery.recover_premature_merged_changeset(
        issue=issue,
        changeset_id=changeset_id,
        epic_id=epic_id,
        agent_id=agent_id,
        agent_bead_id=agent_bead_id,
        branch_pr=branch_pr,
        branch_pr_mode=branch_pr_mode,
        branch_history=branch_history,
        branch_squash_message=branch_squash_message,
        branch_pr_strategy=branch_pr_strategy,
        repo_slug=repo_slug,
        beads_root=beads_root,
        repo_root=repo_root,
        project_data_dir=project_data_dir,
        squash_message_agent_spec=squash_message_agent_spec,
        squash_message_agent_options=squash_message_agent_options,
        squash_message_agent_home=squash_message_agent_home,
        squash_message_agent_env=squash_message_agent_env,
        git_path=git_path,
        changeset_work_branch=changeset_work_branch,
        lookup_pr_payload=lookup_pr_payload,
        lookup_pr_payload_diagnostic=lookup_pr_payload_diagnostic,
        changeset_integration_signal=changeset_integration_signal,
        finalize_terminal_changeset=finalize_terminal_changeset,
        mark_changeset_in_progress=mark_changeset_in_progress,
        update_changeset_review_from_pr=update_changeset_review_from_pr,
        handle_pushed_without_pr=handle_pushed_without_pr,
    )


def changeset_waiting_on_review_or_signals(
    issue: dict[str, object],
    *,
    repo_slug: str | None,
    repo_root: Path,
    branch_pr: bool,
    branch_pr_strategy: object,
    git_path: str | None,
) -> bool:
    """Changeset waiting on review or signals.

    Args:
        issue: Value for `issue`.
        repo_slug: Value for `repo_slug`.
        repo_root: Value for `repo_root`.
        branch_pr: Value for `branch_pr`.
        branch_pr_strategy: Value for `branch_pr_strategy`.
        git_path: Value for `git_path`.

    Returns:
        Function result.
    """
    if not branch_pr:
        return False
    work_branch = changeset_work_branch(issue)
    if work_branch:
        pushed = git.git_ref_exists(
            repo_root, f"refs/remotes/origin/{work_branch}", git_path=git_path
        )
        pr_payload = lookup_pr_payload(repo_slug, work_branch)
        review_requested = prs.has_review_requests(pr_payload)
        state = prs.lifecycle_state(pr_payload, pushed=pushed, review_requested=review_requested)
        if state in {"merged", "closed"}:
            return False
        if state in {"draft-pr", "pr-open", "in-review", "approved"}:
            return True
        if state == "pushed":
            decision = changeset_pr_creation_decision(
                issue,
                repo_slug=repo_slug,
                repo_root=repo_root,
                git_path=git_path,
                branch_pr_strategy=branch_pr_strategy,
            )
            return not decision.allow_pr
    review_state = changeset_review_state(issue)
    if review_state:
        if review_state in {"draft-pr", "pr-open", "in-review", "approved"}:
            return True
        if review_state == "pushed":
            decision = changeset_pr_creation_decision(
                issue,
                repo_slug=repo_slug,
                repo_root=repo_root,
                git_path=git_path,
                branch_pr_strategy=branch_pr_strategy,
            )
            return not decision.allow_pr
    return False


def is_changeset_recovery_candidate(
    issue: dict[str, object],
    *,
    repo_slug: str | None,
    repo_root: Path,
    branch_pr: bool,
    git_path: str | None,
) -> bool:
    """Return whether a blocked changeset has enough signals to recover.

    Args:
        issue: Changeset issue payload.
        repo_slug: Optional GitHub owner/repo slug.
        repo_root: Repository checkout path.
        branch_pr: Whether PR mode is enabled.
        git_path: Optional git binary path override.

    Returns:
        ``True`` when recovery should re-run finalize logic.
    """
    canonical_status = lifecycle.canonical_lifecycle_status(issue.get("status"))
    if canonical_status != "blocked":
        return False
    work_branch = changeset_work_branch(issue)
    if not work_branch:
        return False
    pushed = git.git_ref_exists(repo_root, f"refs/remotes/origin/{work_branch}", git_path=git_path)
    if branch_pr:
        pr_payload = lookup_pr_payload(repo_slug, work_branch)
        review_requested = prs.has_review_requests(pr_payload)
        lifecycle_state = prs.lifecycle_state(
            pr_payload, pushed=pushed, review_requested=review_requested
        )
        if lifecycle_state in {"pushed", "draft-pr", "pr-open", "in-review", "approved"}:
            return True
        review_state = changeset_review_state(issue)
        return review_state in {
            "pushed",
            "draft-pr",
            "pr-open",
            "in-review",
            "approved",
        }
    return pushed


def list_child_issues(
    parent_id: str, *, beads_root: Path, repo_root: Path, include_closed: bool = False
) -> list[dict[str, object]]:
    """List child issues.

    Args:
        parent_id: Value for `parent_id`.
        beads_root: Value for `beads_root`.
        repo_root: Value for `repo_root`.
        include_closed: Value for `include_closed`.

    Returns:
        Function result.
    """
    return worker_finalization_service.list_child_issues(
        parent_id,
        beads_root=beads_root,
        repo_root=repo_root,
        include_closed=include_closed,
    )


def changeset_parent_branch(
    issue: dict[str, object],
    *,
    root_branch: str,
    beads_root: Path | None = None,
    repo_root: Path | None = None,
) -> str:
    """Changeset parent branch.

    Args:
        issue: Value for `issue`.
        root_branch: Value for `root_branch`.

    Returns:
        Function result.
    """
    lineage = _resolve_parent_lineage(
        issue,
        root_branch=root_branch,
        beads_root=beads_root,
        repo_root=repo_root or Path("."),
    )
    parent_branch = _normalize_branch(lineage.effective_parent_branch)
    if parent_branch and (not root_branch or parent_branch != root_branch):
        return parent_branch

    resolved_repo_root = repo_root or Path(".")
    description = issue.get("description")
    fields = beads.parse_description_fields(description if isinstance(description, str) else "")
    workspace_parent_branch = _resolve_workspace_parent_branch(
        issue,
        root_branch=root_branch,
        parent_branch=parent_branch,
        workspace_parent_branch=str(fields.get("workspace.parent_branch") or ""),
        beads_root=beads_root,
        repo_root=resolved_repo_root,
    )
    if workspace_parent_branch and workspace_parent_branch != root_branch:
        return workspace_parent_branch
    if not workspace_parent_branch and (not parent_branch or parent_branch == root_branch):
        default_parent_branch = _resolve_non_root_default_branch(
            root_branch=root_branch,
            repo_root=resolved_repo_root,
            git_path=None,
        )
        if default_parent_branch:
            return default_parent_branch
    if parent_branch:
        return parent_branch
    return root_branch


def mark_changeset_in_progress(changeset_id: str, *, beads_root: Path, repo_root: Path) -> None:
    """Mark changeset in progress.

    Args:
        changeset_id: Value for `changeset_id`.
        beads_root: Value for `beads_root`.
        repo_root: Value for `repo_root`.

    Returns:
        Function result.
    """
    worker_finalization_service.mark_changeset_in_progress(
        changeset_id,
        beads_root=beads_root,
        repo_root=repo_root,
    )


def mark_changeset_closed(changeset_id: str, *, beads_root: Path, repo_root: Path) -> None:
    """Mark changeset closed.

    Args:
        changeset_id: Value for `changeset_id`.
        beads_root: Value for `beads_root`.
        repo_root: Value for `repo_root`.

    Returns:
        Function result.
    """
    worker_finalization_service.mark_changeset_closed(
        changeset_id,
        beads_root=beads_root,
        repo_root=repo_root,
    )


def mark_changeset_merged(changeset_id: str, *, beads_root: Path, repo_root: Path) -> None:
    """Mark changeset merged.

    Args:
        changeset_id: Value for `changeset_id`.
        beads_root: Value for `beads_root`.
        repo_root: Value for `repo_root`.

    Returns:
        Function result.
    """
    worker_finalization_service.mark_changeset_merged(
        changeset_id,
        beads_root=beads_root,
        repo_root=repo_root,
    )


def mark_changeset_abandoned(changeset_id: str, *, beads_root: Path, repo_root: Path) -> None:
    """Mark changeset abandoned.

    Args:
        changeset_id: Value for `changeset_id`.
        beads_root: Value for `beads_root`.
        repo_root: Value for `repo_root`.

    Returns:
        Function result.
    """
    worker_finalization_service.mark_changeset_abandoned(
        changeset_id,
        beads_root=beads_root,
        repo_root=repo_root,
    )


def mark_changeset_blocked(
    changeset_id: str, *, beads_root: Path, repo_root: Path, reason: str
) -> None:
    """Mark changeset blocked.

    Args:
        changeset_id: Value for `changeset_id`.
        beads_root: Value for `beads_root`.
        repo_root: Value for `repo_root`.
        reason: Value for `reason`.

    Returns:
        Function result.
    """
    worker_finalization_service.mark_changeset_blocked(
        changeset_id,
        beads_root=beads_root,
        repo_root=repo_root,
        reason=reason,
    )


def mark_changeset_children_in_progress(
    changeset_id: str, *, beads_root: Path, repo_root: Path
) -> None:
    """Mark changeset children in progress.

    Args:
        changeset_id: Value for `changeset_id`.
        beads_root: Value for `beads_root`.
        repo_root: Value for `repo_root`.

    Returns:
        Function result.
    """
    worker_finalization_service.mark_changeset_children_in_progress(
        changeset_id,
        beads_root=beads_root,
        repo_root=repo_root,
    )


def close_completed_container_changesets(
    epic_id: str, *, beads_root: Path, repo_root: Path
) -> list[str]:
    """Close completed container changesets.

    Args:
        epic_id: Value for `epic_id`.
        beads_root: Value for `beads_root`.
        repo_root: Value for `repo_root`.

    Returns:
        Function result.
    """
    return worker_finalization_service.close_completed_container_changesets(
        epic_id,
        beads_root=beads_root,
        repo_root=repo_root,
        has_open_descendant_changesets=lambda issue_id: has_open_descendant_changesets(
            issue_id, beads_root=beads_root, repo_root=repo_root
        ),
    )


def promote_planned_descendant_changesets(
    changeset_id: str, *, beads_root: Path, repo_root: Path
) -> list[str]:
    """Promote planned descendant changesets.

    Args:
        changeset_id: Value for `changeset_id`.
        beads_root: Value for `beads_root`.
        repo_root: Value for `repo_root`.

    Returns:
        Function result.
    """
    return worker_finalization_service.promote_planned_descendant_changesets(
        changeset_id, beads_root=beads_root, repo_root=repo_root
    )


def has_blocking_messages(
    *,
    thread_ids: set[str],
    started_at: dt.datetime,
    beads_root: Path,
    repo_root: Path,
) -> bool:
    """Has blocking messages.

    Args:
        thread_ids: Value for `thread_ids`.
        started_at: Value for `started_at`.
        beads_root: Value for `beads_root`.
        repo_root: Value for `repo_root`.

    Returns:
        Function result.
    """
    return worker_finalization_service.has_blocking_messages(
        thread_ids=thread_ids,
        started_at=started_at,
        beads_root=beads_root,
        repo_root=repo_root,
        parse_issue_time=parse_issue_time,
    )


def branch_ref_for_lookup(
    repo_root: Path, branch: str, *, git_path: str | None = None
) -> str | None:
    """Branch ref for lookup.

    Args:
        repo_root: Value for `repo_root`.
        branch: Value for `branch`.
        git_path: Value for `git_path`.

    Returns:
        Function result.
    """
    return worker_integration_service.branch_ref_for_lookup(repo_root, branch, git_path=git_path)


def epic_root_integrated_into_parent(
    epic_issue: dict[str, object],
    *,
    repo_root: Path,
    git_path: str | None = None,
) -> bool:
    """Epic root integrated into parent.

    Args:
        epic_issue: Value for `epic_issue`.
        repo_root: Value for `repo_root`.
        git_path: Value for `git_path`.

    Returns:
        Function result.
    """
    return worker_integration_service.epic_root_integrated_into_parent(
        epic_issue,
        repo_root=repo_root,
        git_path=git_path,
    )


def changeset_integration_signal(
    issue: dict[str, object],
    *,
    repo_slug: str | None,
    repo_root: Path,
    git_path: str | None = None,
    require_target_branch_proof: bool = False,
) -> tuple[bool, str | None]:
    """Changeset integration signal.

    Args:
        issue: Value for `issue`.
        repo_slug: Value for `repo_slug`.
        repo_root: Value for `repo_root`.
        git_path: Value for `git_path`.

    Returns:
        Function result.
    """
    return worker_integration_service.changeset_integration_signal(
        issue,
        repo_slug=repo_slug,
        repo_root=repo_root,
        lookup_pr_payload=lookup_pr_payload,
        git_path=git_path,
        require_target_branch_proof=require_target_branch_proof,
    )


def resolve_epic_id_for_changeset(
    issue: dict[str, object], *, beads_root: Path, repo_root: Path
) -> str | None:
    """Resolve epic id for changeset.

    Args:
        issue: Value for `issue`.
        beads_root: Value for `beads_root`.
        repo_root: Value for `repo_root`.

    Returns:
        Function result.
    """
    return worker_reconcile_service.resolve_epic_id_for_changeset(
        issue,
        beads_root=beads_root,
        repo_root=repo_root,
        issue_labels=issue_labels,
        issue_parent_id=issue_parent_id,
    )


__all__ = [
    "align_existing_pr_base",
    "attempt_create_draft_pr",
    "branch_ref_for_lookup",
    "changeset_base_branch",
    "changeset_has_review_handoff_signal",
    "changeset_integration_signal",
    "changeset_parent_branch",
    "changeset_parent_lifecycle_state",
    "changeset_pr_creation_decision",
    "changeset_pr_url",
    "changeset_review_state",
    "changeset_root_branch",
    "changeset_stack_integrity_preflight",
    "changeset_waiting_on_review",
    "changeset_waiting_on_review_or_signals",
    "changeset_work_branch",
    "close_completed_container_changesets",
    "epic_root_integrated_into_parent",
    "handle_pushed_without_pr",
    "has_blocking_messages",
    "has_open_descendant_changesets",
    "is_changeset_in_progress",
    "is_changeset_ready",
    "is_changeset_recovery_candidate",
    "list_child_issues",
    "lookup_pr_payload",
    "lookup_pr_payload_diagnostic",
    "mark_changeset_abandoned",
    "mark_changeset_blocked",
    "mark_changeset_children_in_progress",
    "mark_changeset_closed",
    "mark_changeset_in_progress",
    "mark_changeset_merged",
    "promote_planned_descendant_changesets",
    "recover_premature_merged_changeset",
    "release_epic_assignment",
    "render_changeset_pr_body",
    "resolve_epic_id_for_changeset",
    "send_no_ready_changesets",
    "send_planner_notification",
    "set_changeset_review_pending_state",
    "update_changeset_review_from_pr",
]

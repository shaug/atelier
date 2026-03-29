"""Shared refinement invariants for policy, approval, and budget handling."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Callable

from atelier import config as atelier_config
from atelier import git, paths
from atelier.commands.resolve import resolve_project_for_enlistment
from atelier.models import PlanningRefinementConfig
from atelier.planning_refinement import (
    DEFAULT_PLAN_EDIT_ROUNDS_MAX,
    DEFAULT_POST_IMPL_REVIEW_ROUNDS_MAX,
)


def resolve_refinement_policy_for_repo(*, repo_root: Path) -> PlanningRefinementConfig | None:
    """Resolve refinement policy defaults for a repository root.

    Args:
        repo_root: Repository root used to locate project configuration.

    Returns:
        Parsed refinement policy when project config is available, otherwise
        ``None``.
    """
    try:
        _repo_root, enlistment_path, _origin_raw, origin = git.resolve_repo_enlistment(repo_root)
        project_root, _project_config, _resolved_enlistment = resolve_project_for_enlistment(
            enlistment_path, origin
        )
        config_path = paths.project_config_path(project_root)
        project_config = atelier_config.load_project_config(config_path)
    except (Exception, SystemExit):
        return None
    if project_config is None:
        return None
    return atelier_config.resolve_refinement_policy(project_config)


def resolve_refinement_round_limits(
    *,
    cli_plan_edit_rounds_max: int | None,
    cli_post_impl_review_rounds_max: int | None,
    item_plan_edit_rounds_max: int | None,
    item_post_impl_review_rounds_max: int | None,
    policy: PlanningRefinementConfig | None,
) -> tuple[int, int]:
    """Resolve refinement round limits with global precedence.

    Precedence is ``CLI override > item metadata > project policy > defaults``.

    Args:
        cli_plan_edit_rounds_max: CLI override for plan-edit rounds.
        cli_post_impl_review_rounds_max: CLI override for post-impl rounds.
        item_plan_edit_rounds_max: Existing item metadata for plan-edit rounds.
        item_post_impl_review_rounds_max: Existing item metadata for
            post-impl rounds.
        policy: Project policy defaults when available.

    Returns:
        Tuple of ``(plan_edit_rounds_max, post_impl_review_rounds_max)``.
    """
    policy_plan_rounds = (
        int(policy.plan_edit_rounds_max) if policy is not None else DEFAULT_PLAN_EDIT_ROUNDS_MAX
    )
    policy_post_rounds = (
        int(policy.post_impl_review_rounds_max)
        if policy is not None
        else DEFAULT_POST_IMPL_REVIEW_ROUNDS_MAX
    )
    plan_edit_rounds_max = next(
        candidate
        for candidate in (
            cli_plan_edit_rounds_max,
            item_plan_edit_rounds_max,
            policy_plan_rounds,
            DEFAULT_PLAN_EDIT_ROUNDS_MAX,
        )
        if candidate is not None
    )
    post_impl_review_rounds_max = next(
        candidate
        for candidate in (
            cli_post_impl_review_rounds_max,
            item_post_impl_review_rounds_max,
            policy_post_rounds,
            DEFAULT_POST_IMPL_REVIEW_ROUNDS_MAX,
        )
        if candidate is not None
    )
    return int(plan_edit_rounds_max), int(post_impl_review_rounds_max)


def validate_required_refinement_approval(
    *,
    mode: str,
    approval_status: str | None,
    approval_source: str | None,
    approved_by: str | None,
    approved_at: str | None,
    policy: PlanningRefinementConfig | None,
    utc_now_iso8601: Callable[[], str] | None = None,
) -> tuple[str, str, str, str]:
    """Validate required-refinement approval evidence.

    Args:
        mode: Refinement mode (`requested`, `inherited`, or `project_policy`).
        approval_status: Approval status token.
        approval_source: Approval source token.
        approved_by: Approver principal id.
        approved_at: Approval timestamp.
        policy: Project refinement policy defaults.
        utc_now_iso8601: Optional timestamp generator for policy auto-approval.

    Returns:
        Canonical approval tuple:
        ``(approval_status, approval_source, approved_by, approved_at)``.

    Raises:
        ValueError: When required approval evidence is invalid or incomplete.
    """
    if approval_status not in {None, "approved"}:
        raise ValueError("required refinement must set approval_status=approved")
    if mode == "project_policy":
        if policy is None or not bool(policy.required_by_default):
            raise ValueError(
                "project_policy mode requires configured policy (required_by_default=true)"
            )
        if approval_source not in {None, "project_policy"}:
            raise ValueError("project_policy mode requires approval_source=project_policy")
        now_fn = utc_now_iso8601 or _utc_now_iso8601
        return (
            "approved",
            "project_policy",
            approved_by or "project_policy",
            approved_at or now_fn(),
        )
    if not approval_source or not approved_by or not approved_at:
        raise ValueError(
            "required refinement must include approval evidence: "
            "approval_source, approved_by, and approved_at"
        )
    return "approved", approval_source, approved_by, approved_at


def _utc_now_iso8601() -> str:
    now = dt.datetime.now(tz=dt.timezone.utc).replace(microsecond=0)
    return now.isoformat().replace("+00:00", "Z")


__all__ = [
    "resolve_refinement_policy_for_repo",
    "resolve_refinement_round_limits",
    "validate_required_refinement_approval",
]

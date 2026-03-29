#!/usr/bin/env python3
"""Append authoritative planning refinement metadata to an existing work item."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import cast

_SHARED_SCRIPTS_ROOT = Path(__file__).resolve().parents[2] / "shared" / "scripts"
if str(_SHARED_SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_SHARED_SCRIPTS_ROOT))

from projected_bootstrap import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    bootstrap_projected_atelier_script,
)

bootstrap_projected_atelier_script(
    script_path=Path(__file__).resolve(),
    argv=sys.argv[1:],
    require_runtime_health=__name__ == "__main__",
)

from atelier.beads_context import (  # noqa: E402
    resolve_runtime_repo_dir_hint,
    resolve_skill_beads_context,
)
from atelier.models import PlanningRefinementConfig  # noqa: E402
from atelier.planning_refinement import (  # noqa: E402
    ApprovalSource,
    ApprovalStatus,
    PlanningRefinementRecord,
    RefinementVerdict,
)
from atelier.refinement_invariants import (  # noqa: E402
    resolve_refinement_policy_for_repo,
    resolve_refinement_round_limits,
    validate_required_refinement_approval,
)
from atelier.store import AppendNotesRequest  # noqa: E402

_ALLOWED_LIFECYCLES = {"deferred", "open", "in_progress", "blocked"}


def _build_store(*, beads_root: Path, repo_root: Path):
    from atelier.lib.beads import SubprocessBeadsClient
    from atelier.store import build_atelier_store

    client = SubprocessBeadsClient(
        cwd=repo_root,
        beads_root=beads_root,
        env={"BEADS_DIR": str(beads_root)},
    )
    return build_atelier_store(beads=client)


def _resolve_context(
    *,
    beads_dir: str | None,
    repo_dir: str | None,
) -> tuple[Path, Path, str | None]:
    repo_hint, runtime_warning = resolve_runtime_repo_dir_hint(repo_dir=repo_dir)
    context = resolve_skill_beads_context(
        beads_dir=beads_dir,
        repo_dir=repo_hint,
    )
    return context.beads_root, context.repo_root, runtime_warning or context.override_warning


def _clean(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _lifecycle_token(value: object) -> str:
    if hasattr(value, "value") and isinstance(getattr(value, "value"), str):
        return str(getattr(value, "value")).strip().lower()
    return str(value).strip().lower()


async def _resolve_work_item(store, issue_id: str):
    try:
        return await store.get_epic(issue_id)
    except LookupError:
        pass
    try:
        return await store.get_changeset(issue_id)
    except LookupError as exc:
        raise RuntimeError(f"issue not found or not executable work: {issue_id}") from exc


def _render_note(record: PlanningRefinementRecord) -> str:
    payload = record.model_dump(exclude_none=True)
    ordered_keys = (
        "authoritative",
        "mode",
        "required",
        "lineage_root",
        "approval_status",
        "approval_source",
        "approved_by",
        "approved_at",
        "plan_edit_rounds_max",
        "post_impl_review_rounds_max",
        "plan_edit_rounds_used",
        "latest_verdict",
        "initial_plan_path",
        "latest_plan_path",
        "round_log_dir",
    )
    lines = ["planning_refinement.v1"]
    for key in ordered_keys:
        if key not in payload:
            continue
        value = payload[key]
        if isinstance(value, bool):
            rendered = "true" if value else "false"
        else:
            rendered = str(value)
        lines.append(f"{key}: {rendered}")
    return "\n".join(lines)


def _validate_approval_fields(
    args: argparse.Namespace,
    *,
    policy: PlanningRefinementConfig | None,
) -> tuple[ApprovalStatus, ApprovalSource | None, str | None, str | None]:
    approval_source = _clean(args.approval_source)
    approved_by = _clean(args.approved_by)
    approved_at = _clean(args.approved_at)
    approval_status = _clean(args.approval_status)

    if args.required:
        status, source, by, at = validate_required_refinement_approval(
            mode=args.mode,
            approval_status=approval_status,
            approval_source=approval_source,
            approved_by=approved_by,
            approved_at=approved_at,
            policy=policy,
        )
        return cast(ApprovalStatus, status), cast(ApprovalSource, source), by, at

    if approval_status is None:
        approval_status = "missing"
    if approval_status == "approved" and (
        not approval_source or not approved_by or not approved_at
    ):
        raise ValueError(
            "approved refinement status requires approval evidence: "
            "approval_source, approved_by, and approved_at"
        )
    return (
        cast(ApprovalStatus, approval_status),
        cast(ApprovalSource | None, approval_source),
        approved_by,
        approved_at,
    )


def _resolve_refinement_policy(*, repo_root: Path) -> PlanningRefinementConfig | None:
    return resolve_refinement_policy_for_repo(repo_root=repo_root)


def _resolve_round_limits(
    args: argparse.Namespace,
    *,
    policy: PlanningRefinementConfig | None,
) -> tuple[int, int]:
    return resolve_refinement_round_limits(
        cli_plan_edit_rounds_max=args.plan_edit_rounds_max,
        cli_post_impl_review_rounds_max=args.post_impl_review_rounds_max,
        item_plan_edit_rounds_max=None,
        item_post_impl_review_rounds_max=None,
        policy=policy,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issue-id", required=True, help="Epic or changeset issue id")
    parser.add_argument(
        "--mode",
        choices=("requested", "inherited", "project_policy"),
        default="requested",
        help="Refinement activation mode",
    )
    parser.add_argument(
        "--required",
        action="store_true",
        help="Mark refinement as required for claim-gate enforcement",
    )
    parser.add_argument("--lineage-root", default="", help="Lineage root id for inherited mode")
    parser.add_argument(
        "--approval-status",
        choices=("approved", "missing"),
        default="",
        help="Approval status override (defaults by required flag)",
    )
    parser.add_argument(
        "--approval-source",
        choices=("project_policy", "operator"),
        default="",
        help="Approval source when approved",
    )
    parser.add_argument("--approved-by", default="", help="Approver principal id")
    parser.add_argument("--approved-at", default="", help="Approval timestamp")
    parser.add_argument(
        "--plan-edit-rounds-max",
        type=int,
        default=None,
        help="Maximum planning edit rounds",
    )
    parser.add_argument(
        "--post-impl-review-rounds-max",
        type=int,
        default=None,
        help="Maximum post-implementation review rounds",
    )
    parser.add_argument(
        "--latest-verdict",
        choices=("READY", "REVISED", "USER_DECISION_REQUIRED"),
        default="",
        help="Latest refinement verdict",
    )
    parser.add_argument("--initial-plan-path", default="", help="Initial plan artifact path")
    parser.add_argument("--latest-plan-path", default="", help="Latest plan artifact path")
    parser.add_argument("--round-log-dir", default="", help="Round log directory path")
    parser.add_argument("--beads-dir", default="", help="Beads directory override")
    parser.add_argument("--repo-dir", default="", help="Repo root override")
    args = parser.parse_args()

    try:
        if args.mode == "inherited" and not _clean(args.lineage_root):
            raise ValueError("inherited mode requires --lineage-root")

        beads_root, repo_root, runtime_warning = _resolve_context(
            beads_dir=_clean(args.beads_dir),
            repo_dir=_clean(args.repo_dir),
        )
        if runtime_warning:
            print(runtime_warning, file=sys.stderr)

        policy = _resolve_refinement_policy(repo_root=repo_root)
        approval_status, approval_source, approved_by, approved_at = _validate_approval_fields(
            args,
            policy=policy,
        )
        plan_edit_rounds_max, post_impl_review_rounds_max = _resolve_round_limits(
            args,
            policy=policy,
        )

        store = _build_store(beads_root=beads_root, repo_root=repo_root)
        issue_id = args.issue_id.strip()
        work_item = asyncio.run(_resolve_work_item(store, issue_id))
        lifecycle = _lifecycle_token(getattr(work_item, "lifecycle", ""))
        if lifecycle not in _ALLOWED_LIFECYCLES:
            raise RuntimeError(
                "refinement can only be set on deferred/open/in_progress/blocked "
                f"items; got {lifecycle!r}"
            )

        latest_verdict = cast(RefinementVerdict | None, _clean(args.latest_verdict))

        record = PlanningRefinementRecord(
            authoritative=True,
            mode=args.mode,
            required=bool(args.required),
            lineage_root=_clean(args.lineage_root),
            approval_status=approval_status,
            approval_source=approval_source,
            approved_by=approved_by,
            approved_at=approved_at,
            plan_edit_rounds_max=plan_edit_rounds_max,
            post_impl_review_rounds_max=post_impl_review_rounds_max,
            latest_verdict=latest_verdict,
            initial_plan_path=_clean(args.initial_plan_path),
            latest_plan_path=_clean(args.latest_plan_path),
            round_log_dir=_clean(args.round_log_dir),
        )
        note = _render_note(record)
        asyncio.run(store.append_notes(AppendNotesRequest(issue_id=issue_id, notes=(note,))))

    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    print(issue_id)
    print(f"refinement_mode: {args.mode}")
    print(f"required: {'true' if args.required else 'false'}")


if __name__ == "__main__":
    main()

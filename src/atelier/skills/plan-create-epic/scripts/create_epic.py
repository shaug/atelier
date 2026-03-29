#!/usr/bin/env python3
"""Create an epic bead and apply default auto-export behavior."""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import replace
from pathlib import Path

_SHARED_SCRIPTS_ROOT = Path(__file__).resolve().parents[2] / "shared" / "scripts"
if str(_SHARED_SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_SHARED_SCRIPTS_ROOT))

from projected_bootstrap import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    bootstrap_projected_atelier_script,
)

_BOOTSTRAP_REPO_ROOT = bootstrap_projected_atelier_script(
    script_path=Path(__file__).resolve(),
    argv=sys.argv[1:],
    require_runtime_health=__name__ == "__main__",
)

from atelier import auto_export  # noqa: E402
from atelier.beads_context import resolve_runtime_repo_dir_hint  # noqa: E402
from atelier.executable_work_validation import (  # noqa: E402
    compact_excerpt,
    validate_executable_work_payload,
)


def _description(scope: str, changeset_strategy: str | None) -> str:
    parts: list[str] = []
    scope_text = scope.strip()
    if scope_text:
        parts.append(scope_text)
    if changeset_strategy:
        strategy = changeset_strategy.strip()
        if strategy:
            parts.append("Changeset strategy:\n" + strategy)
    return "\n\n".join(parts).strip()


def _fail_invalid_payload(*, title: str, scope: str) -> None:
    failures = validate_executable_work_payload(
        title=title,
        scope_text=scope,
        scope_field_name="scope",
        scope_optional=False,
    )
    if not failures:
        return

    print("error: invalid executable work payload for epic creation", file=sys.stderr)
    for failure in failures:
        print(
            f"- {failure.field_name}: [{failure.code}] {failure.detail}",
            file=sys.stderr,
        )
    print(
        "action: provide a concrete title and scope, then rerun plan-create-epic",
        file=sys.stderr,
    )
    print(
        "planner-context: NEEDS-DECISION: rejected low-information epic payload "
        f"(title='{compact_excerpt(title)}'; scope='{compact_excerpt(scope)}')",
        file=sys.stderr,
    )
    raise SystemExit(1)


def _build_store(*, beads_root: Path, repo_root: Path):
    from atelier.lib.beads import SubprocessBeadsClient
    from atelier.store import build_atelier_store

    client = SubprocessBeadsClient(
        cwd=repo_root,
        beads_root=beads_root,
        env={"BEADS_DIR": str(beads_root)},
    )
    return build_atelier_store(beads=client)


def _render_refinement_note(record: object) -> str:
    from typing import cast

    model_dump = getattr(record, "model_dump", None)
    if not callable(model_dump):
        raise RuntimeError("invalid refinement record payload")
    raw_payload = model_dump(exclude_none=True)
    if not isinstance(raw_payload, dict):
        raise RuntimeError("invalid refinement record payload")
    payload = cast(dict[str, object], raw_payload)
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


def _required_refinement_note(
    *,
    issue_id: str,
    approval_source: str,
    approved_by: str,
    approved_at: str,
) -> str:
    from typing import cast

    from atelier.planning_refinement import (
        DEFAULT_PLAN_EDIT_ROUNDS_MAX,
        DEFAULT_POST_IMPL_REVIEW_ROUNDS_MAX,
        ApprovalSource,
        PlanningRefinementRecord,
    )

    record = PlanningRefinementRecord(
        authoritative=True,
        mode="requested",
        required=True,
        lineage_root=issue_id,
        approval_status="approved",
        approval_source=cast(ApprovalSource, approval_source),
        approved_by=approved_by,
        approved_at=approved_at,
        plan_edit_rounds_max=DEFAULT_PLAN_EDIT_ROUNDS_MAX,
        post_impl_review_rounds_max=DEFAULT_POST_IMPL_REVIEW_ROUNDS_MAX,
    )
    return _render_refinement_note(record)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--title", required=True, help="Epic title")
    parser.add_argument("--scope", required=True, help="Scope summary")
    parser.add_argument("--acceptance", required=True, help="Acceptance criteria")
    parser.add_argument(
        "--changeset-strategy",
        help="Optional guardrail/decomposition strategy text",
    )
    parser.add_argument("--design", help="Optional design notes")
    parser.add_argument(
        "--required-refinement",
        action="store_true",
        help="Require refinement for this epic and persist approval evidence",
    )
    parser.add_argument(
        "--refinement-approval-source",
        choices=("project_policy", "operator"),
        default="",
        help="Approval source for required refinement",
    )
    parser.add_argument(
        "--refinement-approved-by",
        default="",
        help="Approver principal id for required refinement",
    )
    parser.add_argument(
        "--refinement-approved-at",
        default="",
        help="Approval timestamp for required refinement",
    )
    parser.add_argument(
        "--no-export",
        action="store_true",
        help="Opt out this bead from default auto-export behavior",
    )
    parser.add_argument(
        "--beads-dir",
        default="",
        help="Beads directory override (defaults to project config)",
    )
    parser.add_argument(
        "--repo-dir",
        default="",
        help="Repo root override (defaults to ./worktree, then cwd)",
    )
    args = parser.parse_args()

    _fail_invalid_payload(title=args.title, scope=args.scope)

    repo_hint_raw, runtime_warning = resolve_runtime_repo_dir_hint(
        repo_dir=str(args.repo_dir).strip() or None
    )
    if runtime_warning:
        print(runtime_warning, file=sys.stderr)
    context = auto_export.resolve_auto_export_context(
        repo_hint=Path(repo_hint_raw) if repo_hint_raw else None
    )
    beads_dir = str(args.beads_dir).strip()
    if beads_dir:
        context = replace(context, beads_root=Path(beads_dir))

    description = _description(args.scope, args.changeset_strategy)
    store = _build_store(beads_root=context.beads_root, repo_root=context.project_dir)
    from atelier.store import CreateEpicRequest, LifecycleStatus

    try:
        epic = asyncio.run(
            store.create_epic(
                CreateEpicRequest(
                    title=args.title,
                    description=description or None,
                    acceptance_criteria=args.acceptance,
                    design=args.design,
                    labels=("ext:no-export",) if args.no_export else (),
                    initial_status=LifecycleStatus.DEFERRED,
                )
            )
        )
        if args.required_refinement:
            approval_source = str(args.refinement_approval_source).strip()
            approved_by = str(args.refinement_approved_by).strip()
            approved_at = str(args.refinement_approved_at).strip()
            if not approval_source or not approved_by or not approved_at:
                raise RuntimeError(
                    "required refinement must include approval evidence: "
                    "refinement_approval_source, refinement_approved_by, and "
                    "refinement_approved_at"
                )
            note = _required_refinement_note(
                issue_id=epic.id,
                approval_source=approval_source,
                approved_by=approved_by,
                approved_at=approved_at,
            )
            from atelier.store import AppendNotesRequest

            asyncio.run(store.append_notes(AppendNotesRequest(issue_id=epic.id, notes=(note,))))
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    issue_id = epic.id

    print(issue_id)

    export_result = auto_export.auto_export_issue(
        issue_id,
        context=context,
    )
    print(f"auto-export: {export_result.status} ({export_result.message})")
    if export_result.retry_command:
        print(f"retry: {export_result.retry_command}", file=sys.stderr)


if __name__ == "__main__":
    main()

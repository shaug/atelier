#!/usr/bin/env python3
"""Create a changeset bead and apply default auto-export behavior."""

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
from atelier.planning_refinement import (  # noqa: E402
    PlanningRefinementRecord,
    parse_refinement_blocks,
    select_winning_refinement,
)
from atelier.store import AppendNotesRequest  # noqa: E402


def _fail_invalid_payload(*, title: str, description: str) -> None:
    failures = validate_executable_work_payload(
        title=title,
        scope_text=description,
        scope_field_name="description",
        scope_optional=True,
    )
    if not failures:
        return

    print("error: invalid executable work payload for changeset creation", file=sys.stderr)
    for failure in failures:
        print(
            f"- {failure.field_name}: [{failure.code}] {failure.detail}",
            file=sys.stderr,
        )
    print(
        "action: provide a concrete title/description, then rerun plan-changesets",
        file=sys.stderr,
    )
    print(
        "planner-context: NEEDS-DECISION: rejected low-information changeset "
        "payload "
        f"(title='{compact_excerpt(title)}'; description='{compact_excerpt(description)}')",
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


def _render_refinement_note(record: PlanningRefinementRecord) -> str:
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


def _parent_notes(*, store, epic_id: str, beads_root: Path, repo_root: Path) -> str | None:
    if not hasattr(store, "get_epic"):
        return None
    parent = asyncio.run(store.get_epic(epic_id))
    from_store = getattr(parent, "notes", None)
    if isinstance(from_store, str) and from_store.strip():
        return from_store
    if isinstance(from_store, (tuple, list)):
        joined = "\n".join(str(item).strip() for item in from_store if str(item).strip())
        if joined:
            return joined

    from atelier.lib.beads import ShowIssueRequest, SubprocessBeadsClient

    client = SubprocessBeadsClient(
        cwd=repo_root,
        beads_root=beads_root,
        env={"BEADS_DIR": str(beads_root)},
    )
    issue = asyncio.run(client.show(ShowIssueRequest(issue_id=epic_id)))
    notes = getattr(issue, "notes", None)
    if isinstance(notes, str) and notes.strip():
        return notes
    if isinstance(notes, (tuple, list)):
        joined = "\n".join(str(item).strip() for item in notes if str(item).strip())
        if joined:
            return joined
    return None


def _inherited_refinement_note(*, parent_notes: str | None, epic_id: str) -> str | None:
    if not parent_notes:
        return None
    selected = select_winning_refinement(parse_refinement_blocks(parent_notes))
    if selected is None or not selected.required:
        return None
    inherited = PlanningRefinementRecord(
        authoritative=True,
        mode="inherited",
        required=True,
        lineage_root=selected.lineage_root or epic_id,
        approval_status=selected.approval_status,
        approval_source=selected.approval_source,
        approved_by=selected.approved_by,
        approved_at=selected.approved_at,
        plan_edit_rounds_max=selected.plan_edit_rounds_max,
        post_impl_review_rounds_max=selected.post_impl_review_rounds_max,
        latest_verdict=selected.latest_verdict,
    )
    return _render_refinement_note(inherited)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--epic-id", required=True, help="Parent epic bead id")
    parser.add_argument("--title", required=True, help="Changeset title")
    parser.add_argument("--acceptance", required=True, help="Acceptance criteria")
    parser.add_argument(
        "--status",
        choices=("deferred", "open"),
        default="deferred",
        help="Lifecycle status to set after create",
    )
    parser.add_argument(
        "--description",
        default="",
        help="Optional scope/guardrail details",
    )
    parser.add_argument(
        "--notes",
        default="",
        help="Optional notes to write after creation",
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
    description = str(args.description).strip()

    _fail_invalid_payload(title=args.title, description=description)

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

    store = _build_store(beads_root=context.beads_root, repo_root=context.project_dir)
    from atelier.store import CreateChangesetRequest, LifecycleStatus

    initial_status = LifecycleStatus(args.status)
    notes = (str(args.notes).strip(),) if str(args.notes).strip() else ()
    try:
        parent_notes = _parent_notes(
            store=store,
            epic_id=args.epic_id,
            beads_root=context.beads_root,
            repo_root=context.project_dir,
        )
        refinement_note = _inherited_refinement_note(
            parent_notes=parent_notes,
            epic_id=args.epic_id,
        )
        changeset = asyncio.run(
            store.create_changeset(
                CreateChangesetRequest(
                    epic_id=args.epic_id,
                    title=args.title,
                    acceptance_criteria=args.acceptance,
                    description=description or None,
                    notes=notes,
                    labels=("ext:no-export",) if args.no_export else (),
                    initial_status=initial_status,
                )
            )
        )
        if refinement_note is not None:
            asyncio.run(
                store.append_notes(
                    AppendNotesRequest(issue_id=changeset.id, notes=(refinement_note,))
                )
            )
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    issue_id = changeset.id

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

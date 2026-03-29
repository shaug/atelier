#!/usr/bin/env python3
"""Split one parent work item into multiple child changesets."""

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
from atelier.planning_refinement import (  # noqa: E402
    PlanningRefinementRecord,
    parse_refinement_blocks,
    select_winning_refinement,
)
from atelier.store import AppendNotesRequest  # noqa: E402


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


def _normalize_notes(value: object) -> str | None:
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    if isinstance(value, (tuple, list)):
        joined = "\n".join(str(item).strip() for item in value if str(item).strip())
        return joined or None
    return None


def _task_specs(raw_tasks: tuple[str, ...]) -> tuple[tuple[str, str], ...]:
    specs: list[tuple[str, str]] = []
    for task in raw_tasks:
        if "::" not in task:
            raise ValueError(
                f"task entries must use '<title>::<acceptance>' format; received {task!r}"
            )
        title, acceptance = task.split("::", 1)
        title = title.strip()
        acceptance = acceptance.strip()
        if not title or not acceptance:
            raise ValueError(
                f"task entries must include non-empty title and acceptance text; received {task!r}"
            )
        specs.append((title, acceptance))
    if not specs:
        raise ValueError("at least one --task entry is required")
    return tuple(specs)


def _fallback_parent_notes(
    *,
    parent_id: str,
    beads_root: Path,
    repo_root: Path,
) -> str | None:
    from atelier.lib.beads import ShowIssueRequest, SubprocessBeadsClient

    client = SubprocessBeadsClient(
        cwd=repo_root,
        beads_root=beads_root,
        env={"BEADS_DIR": str(beads_root)},
    )
    issue = asyncio.run(client.show(ShowIssueRequest(issue_id=parent_id)))
    return _normalize_notes(getattr(issue, "notes", None))


def _resolve_parent(
    *,
    store,
    parent_id: str,
    beads_root: Path,
    repo_root: Path,
) -> tuple[str, str | None]:
    try:
        parent_changeset = asyncio.run(store.get_changeset(parent_id))
        epic_id = str(getattr(parent_changeset, "epic_id", "")).strip() or parent_id
        has_notes = hasattr(parent_changeset, "notes")
        notes = _normalize_notes(getattr(parent_changeset, "notes", None))
        if has_notes:
            return epic_id, notes
        return epic_id, _fallback_parent_notes(
            parent_id=parent_id,
            beads_root=beads_root,
            repo_root=repo_root,
        )
    except LookupError:
        pass
    parent_epic = asyncio.run(store.get_epic(parent_id))
    has_notes = hasattr(parent_epic, "notes")
    notes = _normalize_notes(getattr(parent_epic, "notes", None))
    if has_notes:
        return parent_epic.id, notes
    return parent_epic.id, _fallback_parent_notes(
        parent_id=parent_id,
        beads_root=beads_root,
        repo_root=repo_root,
    )


def _inherited_refinement_note(*, parent_notes: str | None, lineage_root: str) -> str | None:
    if not parent_notes:
        return None
    selected = select_winning_refinement(parse_refinement_blocks(parent_notes))
    if selected is None or not selected.required:
        return None
    inherited = PlanningRefinementRecord(
        authoritative=True,
        mode="inherited",
        required=True,
        lineage_root=selected.lineage_root or lineage_root,
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
    parser.add_argument("--parent-id", required=True, help="Parent epic or changeset id")
    parser.add_argument(
        "--task",
        action="append",
        default=[],
        help="Child task in '<title>::<acceptance>' format; repeat for multiple children",
    )
    parser.add_argument(
        "--status",
        choices=("deferred", "open"),
        default="deferred",
        help="Lifecycle status for created child changesets",
    )
    parser.add_argument(
        "--no-export",
        action="store_true",
        help="Opt out created children from default auto-export behavior",
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

    try:
        task_specs = _task_specs(tuple(str(value) for value in args.task))

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

        epic_id, parent_notes = _resolve_parent(
            store=store,
            parent_id=args.parent_id.strip(),
            beads_root=context.beads_root,
            repo_root=context.project_dir,
        )
        refinement_note = _inherited_refinement_note(
            parent_notes=parent_notes,
            lineage_root=epic_id,
        )

        created_ids: list[str] = []
        for title, acceptance in task_specs:
            created = asyncio.run(
                store.create_changeset(
                    CreateChangesetRequest(
                        epic_id=epic_id,
                        title=title,
                        acceptance_criteria=acceptance,
                        labels=("ext:no-export",) if args.no_export else (),
                        initial_status=LifecycleStatus(args.status),
                    )
                )
            )
            created_ids.append(created.id)
            if refinement_note is not None:
                asyncio.run(
                    store.append_notes(
                        AppendNotesRequest(issue_id=created.id, notes=(refinement_note,))
                    )
                )
            export_result = auto_export.auto_export_issue(
                created.id,
                context=context,
            )
            print(created.id)
            print(f"auto-export: {export_result.status} ({export_result.message})")
            if export_result.retry_command:
                print(f"retry: {export_result.retry_command}", file=sys.stderr)

        print("created_children: " + ", ".join(created_ids))

    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()

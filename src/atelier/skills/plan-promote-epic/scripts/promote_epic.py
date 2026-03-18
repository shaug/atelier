#!/usr/bin/env python3
"""Preview and promote a deferred epic via AtelierStore lifecycle mutations."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

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
from atelier.lib.beads import description_fields as bead_fields  # noqa: E402


def _build_store_and_client(*, beads_root: Path, repo_root: Path):
    from atelier.lib.beads import SubprocessBeadsClient
    from atelier.store import build_atelier_store

    client = SubprocessBeadsClient(
        cwd=repo_root,
        beads_root=beads_root,
        env={"BEADS_DIR": str(beads_root)},
    )
    return build_atelier_store(beads=client), client


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


def _clean_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned or cleaned.lower() == "null":
        return None
    return cleaned


def _issue_text(issue: object, field_name: str) -> str | None:
    return _clean_text(getattr(issue, field_name, None))


def _split_field_values(value: str | None) -> tuple[str, ...]:
    text = _clean_text(value)
    if text is None:
        return ()
    parts: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip().lstrip("-").strip()
        if line:
            parts.append(line)
    return tuple(parts)


def _note_lines(description: str | None) -> tuple[str, ...]:
    text = _clean_text(description)
    if text is None:
        return ()
    lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        lowered = line.lower()
        if (
            lowered.startswith("note")
            or lowered.startswith("promotion_")
            or lowered.startswith("worker_update")
            or lowered.startswith("changeset_note")
            or lowered.startswith("planner_note")
        ):
            lines.append(line)
    return tuple(lines)


def _related_context(issue: object) -> tuple[str, ...]:
    fields = bead_fields.parse_description_fields(_issue_text(issue, "description") or "")
    related = list(_split_field_values(fields.get("related_context")))
    related.extend(_split_field_values(fields.get("external_tickets")))
    deduped: list[str] = []
    seen: set[str] = set()
    for item in related:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return tuple(deduped)


def _missing_detail_sections(issue: object) -> tuple[str, ...]:
    missing: list[str] = []
    if _issue_text(issue, "description") is None:
        missing.append("description")
    if not _note_lines(_issue_text(issue, "description")):
        missing.append("notes")
    if _issue_text(issue, "acceptance_criteria") is None:
        missing.append("acceptance criteria")
    if not _related_context(issue):
        missing.append("related-context references")
    return tuple(missing)


def _has_decomposition_rationale(
    epic_issue: object,
    child_issues: tuple[object, ...],
) -> bool:
    haystacks = [_issue_text(epic_issue, "description") or ""]
    haystacks.extend((_issue_text(child, "description") or "") for child in child_issues)
    for text in haystacks:
        lowered = text.lower()
        if "changeset_strategy:" in lowered or "decomposition" in lowered or "split " in lowered:
            return True
    return False


def _dependency_ids(issue: object) -> tuple[str, ...]:
    values: list[str] = []
    for dependency in getattr(issue, "dependencies", ()):
        dependency_id = _clean_text(getattr(dependency, "id", None))
        if dependency_id:
            values.append(dependency_id)
    return tuple(values)


def _render_issue_preview(*, header: str, issue: object) -> str:
    dependencies = _dependency_ids(issue)
    related_context = _related_context(issue)
    notes = _note_lines(_issue_text(issue, "description"))
    missing = _missing_detail_sections(issue)
    lines = [
        header,
        f"Title: {_issue_text(issue, 'title') or _issue_text(issue, 'id') or '(untitled)'}",
        f"Status: {_issue_text(issue, 'status') or ''}",
        "Description:",
        _issue_text(issue, "description") or "(missing)",
        "Notes:",
        "\n".join(notes) if notes else "(missing)",
        "Acceptance Criteria:",
        _issue_text(issue, "acceptance_criteria") or "(missing)",
        "Dependencies:",
        "\n".join(f"- {dependency}" for dependency in dependencies) if dependencies else "none",
        "Related Context:",
        "\n".join(f"- {item}" for item in related_context) if related_context else "(missing)",
    ]
    if missing:
        lines.append("Missing detail sections: " + ", ".join(missing))
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--epic-id", required=True, help="Deferred epic bead id")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Apply the promotion after preview and explicit operator confirmation",
    )
    parser.add_argument(
        "--beads-dir",
        default="",
        help="Beads directory override (defaults to project-scoped store)",
    )
    parser.add_argument(
        "--repo-dir",
        default="",
        help="Repo root override (defaults to ./worktree, then cwd)",
    )
    args = parser.parse_args()

    beads_root, repo_root, runtime_warning = _resolve_context(
        beads_dir=str(args.beads_dir).strip() or None,
        repo_dir=str(args.repo_dir).strip() or None,
    )
    if runtime_warning:
        print(runtime_warning, file=sys.stderr)
    store, client = _build_store_and_client(beads_root=beads_root, repo_root=repo_root)

    try:
        from atelier.lib.beads import ShowIssueRequest
        from atelier.store import ChangesetQuery, LifecycleStatus, LifecycleTransitionRequest

        epic_id = args.epic_id.strip()
        epic = asyncio.run(store.get_epic(epic_id))
        if epic.lifecycle is not LifecycleStatus.DEFERRED:
            raise RuntimeError(f"epic {epic_id} must be deferred before promotion")

        epic_issue = asyncio.run(client.show(ShowIssueRequest(issue_id=epic_id)))
        changesets = tuple(
            sorted(
                asyncio.run(
                    store.list_changesets(
                        ChangesetQuery(
                            epic_id=epic_id,
                            include_closed=True,
                        )
                    )
                ),
                key=lambda record: record.id,
            )
        )
        child_issues = tuple(
            asyncio.run(client.show(ShowIssueRequest(issue_id=record.id))) for record in changesets
        )
        preview_blocks = [_render_issue_preview(header=f"EPIC {epic_id}", issue=epic_issue)]
        child_missing: dict[str, tuple[str, ...]] = {}
        promotable_children: list[str] = []
        for record, issue in zip(changesets, child_issues, strict=True):
            preview_blocks.append(
                _render_issue_preview(header=f"CHANGESET {record.id}", issue=issue)
            )
            missing = _missing_detail_sections(issue)
            child_missing[record.id] = missing
            if record.lifecycle is LifecycleStatus.DEFERRED and not missing:
                promotable_children.append(record.id)

        print("\n\n".join(preview_blocks))

        problems: list[str] = []
        epic_missing = _missing_detail_sections(epic_issue)
        if epic_missing:
            problems.append(f"epic missing detail sections: {', '.join(epic_missing)}")
        if len(changesets) == 1 and not _has_decomposition_rationale(epic_issue, child_issues):
            problems.append("one-child promotion requires explicit decomposition rationale")
        incomplete_children = [issue_id for issue_id, missing in child_missing.items() if missing]
        if incomplete_children:
            problems.append(
                "incomplete child changesets remain deferred: " + ", ".join(incomplete_children)
            )

        if problems:
            raise RuntimeError("; ".join(problems))

        if not args.yes:
            print("confirmation_required: rerun with --yes after explicit operator confirmation")
            return

        asyncio.run(
            store.transition_lifecycle(
                LifecycleTransitionRequest(
                    issue_id=epic_id,
                    target_status=LifecycleStatus.OPEN,
                    expected_current=LifecycleStatus.DEFERRED,
                )
            )
        )
        promoted_children: list[str] = []
        for child_id in promotable_children:
            asyncio.run(
                store.transition_lifecycle(
                    LifecycleTransitionRequest(
                        issue_id=child_id,
                        target_status=LifecycleStatus.OPEN,
                        expected_current=LifecycleStatus.DEFERRED,
                    )
                )
            )
            promoted_children.append(child_id)

    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    print(f"promoted_epic: {epic_id}")
    if promoted_children:
        print("promoted_children: " + ", ".join(promoted_children))
    else:
        print("promoted_children: none")


if __name__ == "__main__":
    main()

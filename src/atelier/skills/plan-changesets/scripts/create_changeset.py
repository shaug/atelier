#!/usr/bin/env python3
"""Create a changeset bead and apply default auto-export behavior."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import replace
from pathlib import Path


def _bootstrap_source_import() -> None:
    src_dir = Path(__file__).resolve().parents[4]
    if src_dir.is_dir() and str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))


_bootstrap_source_import()

from atelier import auto_export, beads  # noqa: E402

_STATUS_UPDATE_ATTEMPTS = 2
_FAIL_CLOSED_REASON = "automatic fail-closed: unable to set deferred status after create"
_ISSUE_ID_PATTERN = re.compile(r"\b[a-zA-Z][a-zA-Z0-9_-]*-[a-zA-Z0-9]+(?:\.[a-zA-Z0-9]+)*\b")
_CREATE_OUTPUT_EXCERPT_MAX = 160


def _command_detail(result: subprocess.CompletedProcess[str]) -> str:
    stderr = (result.stderr or "").strip()
    if stderr:
        return stderr
    return (result.stdout or "").strip()


def _list_child_issue_ids(*, epic_id: str, beads_root: Path, cwd: Path) -> set[str]:
    issues = beads.run_bd_json(["list", "--parent", epic_id], beads_root=beads_root, cwd=cwd)
    ids: set[str] = set()
    for issue in issues:
        issue_id = issue.get("id")
        if isinstance(issue_id, str):
            cleaned = issue_id.strip()
            if cleaned:
                ids.add(cleaned)
    return ids


def _extract_issue_ids_from_output(raw_output: str) -> list[str]:
    seen: set[str] = set()
    issue_ids: list[str] = []
    for match in _ISSUE_ID_PATTERN.findall(raw_output):
        if match in seen:
            continue
        issue_ids.append(match)
        seen.add(match)
    return issue_ids


def _compact_excerpt(raw_output: str) -> str:
    compacted = " ".join(str(raw_output).split())
    if not compacted:
        return "<empty>"
    if len(compacted) <= _CREATE_OUTPUT_EXCERPT_MAX:
        return compacted
    return f"{compacted[: _CREATE_OUTPUT_EXCERPT_MAX - 3]}..."


def _create_output_excerpt(*, create_stdout: str, create_stderr: str) -> str:
    stdout_excerpt = _compact_excerpt(create_stdout)
    stderr_excerpt = _compact_excerpt(create_stderr)
    return f"create output excerpt: stdout='{stdout_excerpt}'; stderr='{stderr_excerpt}'"


def _resolve_created_issue_id(
    *,
    epic_id: str,
    create_stdout: str,
    create_stderr: str,
    existing_child_ids: set[str],
    beads_root: Path,
    cwd: Path,
) -> str:
    current_child_ids = _list_child_issue_ids(epic_id=epic_id, beads_root=beads_root, cwd=cwd)
    newly_created_ids = sorted(current_child_ids - existing_child_ids)
    if len(newly_created_ids) == 1:
        return newly_created_ids[0]

    output_issue_ids = _extract_issue_ids_from_output(create_stdout)
    created_candidates = [
        issue_id for issue_id in output_issue_ids if issue_id in newly_created_ids
    ]
    if len(created_candidates) == 1:
        return created_candidates[0]

    excerpt = _create_output_excerpt(
        create_stdout=create_stdout,
        create_stderr=create_stderr,
    )
    if not newly_created_ids:
        print(
            "error: create did not produce a new child issue id; refusing to mutate existing "
            f"changesets ({excerpt})",
            file=sys.stderr,
        )
    else:
        print(
            "error: create returned ambiguous child ids; refusing to mutate existing changesets "
            f"({', '.join(newly_created_ids)}; {excerpt})",
            file=sys.stderr,
        )
    raise SystemExit(1)


def _apply_status_with_fail_closed(
    *,
    issue_id: str,
    status: str,
    beads_root: Path,
    cwd: Path,
) -> None:
    failure_detail = ""
    for _ in range(_STATUS_UPDATE_ATTEMPTS):
        status_result = beads.run_bd_command(
            ["update", issue_id, "--status", status],
            beads_root=beads_root,
            cwd=cwd,
            allow_failure=True,
        )
        if status_result.returncode == 0:
            return
        failure_detail = _command_detail(status_result)

    if status == "deferred":
        close_result = beads.run_bd_command(
            ["close", issue_id, "--reason", _FAIL_CLOSED_REASON],
            beads_root=beads_root,
            cwd=cwd,
            allow_failure=True,
        )
        if close_result.returncode == 0:
            detail = failure_detail or "status update failed"
            print(
                f"error: created changeset {issue_id} but failed to set status=deferred "
                f"after {_STATUS_UPDATE_ATTEMPTS} attempts; auto-closed to fail closed "
                f"({detail})",
                file=sys.stderr,
            )
            raise SystemExit(1)
        close_detail = _command_detail(close_result) or "close command failed"
        detail = failure_detail or "status update failed"
        print(
            f"error: created changeset {issue_id} but failed to set status=deferred "
            f"after {_STATUS_UPDATE_ATTEMPTS} attempts; auto-close failed ({detail}; "
            f"{close_detail})",
            file=sys.stderr,
        )
        raise SystemExit(1)

    detail = failure_detail or "status update failed"
    print(
        f"error: created changeset {issue_id} but failed to set status={status} "
        f"after {_STATUS_UPDATE_ATTEMPTS} attempts ({detail})",
        file=sys.stderr,
    )
    raise SystemExit(1)


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
    args = parser.parse_args()

    context = auto_export.resolve_auto_export_context()
    beads_dir = str(args.beads_dir).strip()
    if beads_dir:
        context = replace(context, beads_root=Path(beads_dir))

    create_args = [
        "create",
        "--parent",
        args.epic_id,
        "--type",
        "task",
        "--title",
        args.title,
        "--acceptance",
        args.acceptance,
        "--silent",
    ]
    description = str(args.description).strip()
    if description:
        create_args.extend(["--description", description])
    if args.no_export:
        create_args.extend(["--label", "ext:no-export"])

    existing_child_ids = _list_child_issue_ids(
        epic_id=args.epic_id,
        beads_root=context.beads_root,
        cwd=context.project_dir,
    )
    result = beads.run_bd_command(
        create_args,
        beads_root=context.beads_root,
        cwd=context.project_dir,
    )
    issue_id = _resolve_created_issue_id(
        epic_id=args.epic_id,
        create_stdout=(result.stdout or ""),
        create_stderr=(result.stderr or ""),
        existing_child_ids=existing_child_ids,
        beads_root=context.beads_root,
        cwd=context.project_dir,
    )

    _apply_status_with_fail_closed(
        issue_id=issue_id,
        status=args.status,
        beads_root=context.beads_root,
        cwd=context.project_dir,
    )

    notes = str(args.notes).strip()
    if notes:
        beads.run_bd_command(
            ["update", issue_id, "--notes", notes],
            beads_root=context.beads_root,
            cwd=context.project_dir,
        )

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

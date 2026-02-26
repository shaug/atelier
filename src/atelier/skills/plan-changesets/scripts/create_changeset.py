#!/usr/bin/env python3
"""Create a changeset bead and apply default auto-export behavior."""

from __future__ import annotations

import argparse
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


def _command_detail(result: subprocess.CompletedProcess[str]) -> str:
    stderr = (result.stderr or "").strip()
    if stderr:
        return stderr
    return (result.stdout or "").strip()


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
        "--label",
        "at:changeset",
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

    result = beads.run_bd_command(
        create_args,
        beads_root=context.beads_root,
        cwd=context.project_dir,
    )
    issue_id = (result.stdout or "").strip()
    if not issue_id:
        print("error: failed to create changeset bead", file=sys.stderr)
        raise SystemExit(1)

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

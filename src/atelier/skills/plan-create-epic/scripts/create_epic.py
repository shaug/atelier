#!/usr/bin/env python3
"""Create an epic bead and apply default auto-export behavior."""

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


def _set_deferred_with_fail_closed(*, issue_id: str, beads_root: Path, cwd: Path) -> None:
    failure_detail = ""
    for _ in range(_STATUS_UPDATE_ATTEMPTS):
        status_result = beads.run_bd_command(
            ["update", issue_id, "--status", "deferred"],
            beads_root=beads_root,
            cwd=cwd,
            allow_failure=True,
        )
        if status_result.returncode == 0:
            return
        failure_detail = _command_detail(status_result)

    close_result = beads.run_bd_command(
        ["close", issue_id, "--reason", _FAIL_CLOSED_REASON],
        beads_root=beads_root,
        cwd=cwd,
        allow_failure=True,
    )
    detail = failure_detail or "status update failed"
    if close_result.returncode == 0:
        print(
            f"error: created epic {issue_id} but failed to set status=deferred "
            f"after {_STATUS_UPDATE_ATTEMPTS} attempts; auto-closed to fail closed "
            f"({detail})",
            file=sys.stderr,
        )
        raise SystemExit(1)

    close_detail = _command_detail(close_result) or "close command failed"
    print(
        f"error: created epic {issue_id} but failed to set status=deferred "
        f"after {_STATUS_UPDATE_ATTEMPTS} attempts; auto-close failed ({detail}; "
        f"{close_detail})",
        file=sys.stderr,
    )
    raise SystemExit(1)


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
        "--type",
        "epic",
        "--label",
        "at:epic",
        "--title",
        args.title,
        "--acceptance",
        args.acceptance,
        "--silent",
    ]
    description = _description(args.scope, args.changeset_strategy)
    if description:
        create_args.extend(["--description", description])
    if args.design:
        create_args.extend(["--design", args.design])
    if args.no_export:
        create_args.extend(["--label", "ext:no-export"])

    result = beads.run_bd_command(
        create_args,
        beads_root=context.beads_root,
        cwd=context.project_dir,
    )
    issue_id = (result.stdout or "").strip()
    if not issue_id:
        print("error: failed to create epic bead", file=sys.stderr)
        raise SystemExit(1)

    _set_deferred_with_fail_closed(
        issue_id=issue_id,
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

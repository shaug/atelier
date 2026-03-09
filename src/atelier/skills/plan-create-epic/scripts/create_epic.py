#!/usr/bin/env python3
"""Create an epic bead and apply default auto-export behavior."""

from __future__ import annotations

import argparse
import subprocess
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

from atelier import auto_export, beads  # noqa: E402
from atelier.beads_context import resolve_runtime_repo_dir_hint  # noqa: E402
from atelier.executable_work_validation import (  # noqa: E402
    compact_excerpt,
    validate_executable_work_payload,
)

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

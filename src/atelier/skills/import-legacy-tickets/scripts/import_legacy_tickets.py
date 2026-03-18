#!/usr/bin/env python3
"""Run startup legacy-ticket migration/import and print explicit diagnostics."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
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

from atelier.bd_invocation import with_bd_mode  # noqa: E402
from atelier.beads_context import (  # noqa: E402
    resolve_runtime_repo_dir_hint,
    resolve_skill_beads_context,
)
from atelier.lib.beads import BeadsStartupState, build_sync_beads_client  # noqa: E402

_STARTUP_READY = "ready"


def _merge_warnings(*messages: str | None) -> str | None:
    lines = [message for message in messages if isinstance(message, str) and message.strip()]
    if not lines:
        return None
    return "\n".join(lines)


def _resolve_context(
    *, beads_dir: str | None, repo_dir: str | None
) -> tuple[Path, Path, str | None]:
    repo_hint, runtime_warning = resolve_runtime_repo_dir_hint(repo_dir=repo_dir)
    context = resolve_skill_beads_context(
        beads_dir=beads_dir,
        repo_dir=repo_hint,
    )
    return (
        context.beads_root,
        context.repo_root,
        _merge_warnings(
            runtime_warning,
            context.override_warning,
        ),
    )


def _status_reason(state: BeadsStartupState) -> str:
    has_legacy_sqlite = bool(getattr(state, "has_legacy_sqlite", False))
    if not has_legacy_sqlite:
        return "no recoverable legacy SQLite startup state detected"
    has_dolt_store = bool(getattr(state, "has_dolt_store", False))
    dolt_total = getattr(state, "dolt_issue_total", None)
    legacy_total = getattr(state, "legacy_issue_total", None)
    if state.migration_eligible and not has_dolt_store:
        return "legacy SQLite data exists but Dolt backend is missing"
    if state.migration_eligible and dolt_total is not None:
        rendered_dolt_total = dolt_total if dolt_total is not None else "unavailable"
        rendered_legacy_total = legacy_total if legacy_total is not None else "unavailable"
        return (
            "active Dolt issue count "
            f"({rendered_dolt_total}) is below legacy SQLite issue count "
            f"({rendered_legacy_total})"
        )
    if state.classification == _STARTUP_READY:
        return "active Dolt issue count already covers legacy SQLite issue count"
    return "no recoverable legacy SQLite startup state detected"


def _migration_verified(
    *,
    before: BeadsStartupState,
    after: BeadsStartupState,
) -> bool:
    if after.classification != _STARTUP_READY or after.migration_eligible:
        return False
    after_dolt_total = getattr(after, "dolt_issue_total", None)
    if after_dolt_total is None:
        return False
    before_legacy_total = getattr(before, "legacy_issue_total", None)
    if before_legacy_total is None:
        return True
    return after_dolt_total >= before_legacy_total


def _inspect_startup_state(*, beads_root: Path, repo_root: Path) -> BeadsStartupState:
    client = build_sync_beads_client(
        cwd=repo_root,
        beads_root=beads_root,
        readonly=True,
    )
    return client.inspect_startup_state()


def _run_prime(*, beads_root: Path, repo_root: Path) -> None:
    env = dict(os.environ)
    env["BEADS_DIR"] = str(beads_root)
    command = with_bd_mode("prime", beads_dir=str(beads_root), env=env)
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            cwd=repo_root,
            env=env,
        )
    except FileNotFoundError:
        print("error: missing required command: bd", file=sys.stderr)
        raise SystemExit(1)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        print(f"error: bd command failed ({' '.join(command)}): {detail}", file=sys.stderr)
        raise SystemExit(1)


def _format_startup_diagnostics(state: BeadsStartupState) -> str:
    return "Startup Beads state: " + "; ".join(state.diagnostics())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--beads-dir",
        default="",
        help="explicit beads root override (defaults to project-scoped store)",
    )
    parser.add_argument(
        "--repo-dir",
        default="",
        help="explicit repo root override (defaults to ./worktree, then cwd)",
    )
    args = parser.parse_args()

    beads_root, repo_root, override_warning = _resolve_context(
        beads_dir=args.beads_dir,
        repo_dir=str(args.repo_dir).strip() or None,
    )
    if override_warning:
        print(override_warning, file=sys.stderr)
    if not beads_root.exists():
        print(f"error: beads dir not found: {beads_root}", file=sys.stderr)
        raise SystemExit(1)

    before = _inspect_startup_state(beads_root=beads_root, repo_root=repo_root)
    _run_prime(beads_root=beads_root, repo_root=repo_root)
    after = _inspect_startup_state(beads_root=beads_root, repo_root=repo_root)

    if before.migration_eligible and _migration_verified(before=before, after=after):
        status = "migrated"
        reason = _status_reason(before)
    elif before.migration_eligible:
        status = "blocked"
        reason = "legacy migration remained unresolved after startup prime"
    else:
        status = "skipped"
        reason = _status_reason(before)

    print(f"Beads startup auto-upgrade {status}: {reason}")
    print("before=" + _format_startup_diagnostics(before))
    print("after=" + _format_startup_diagnostics(after))


if __name__ == "__main__":
    main()

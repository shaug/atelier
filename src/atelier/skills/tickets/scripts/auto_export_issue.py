#!/usr/bin/env python3
"""Retry or manually run ticket export for an existing bead."""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import replace
from pathlib import Path


def _repo_dir_from_argv(argv: list[str]) -> Path | None:
    for index, token in enumerate(argv):
        if token == "--repo-dir" and index + 1 < len(argv):
            value = argv[index + 1].strip()
            if value:
                return Path(value).expanduser()
        if token.startswith("--repo-dir="):
            value = token.split("=", 1)[1].strip()
            if value:
                return Path(value).expanduser()
    return None


def _bootstrap_source_import() -> Path | None:
    candidate_roots: list[Path] = []
    argv_repo_dir = _repo_dir_from_argv(sys.argv[1:])
    if argv_repo_dir is not None:
        candidate_roots.append(argv_repo_dir)

    current_dir = Path.cwd()
    candidate_roots.append(current_dir / "worktree")
    env_repo_dir = os.environ.get("ATELIER_PLANNER_WORKTREE", "").strip()
    if env_repo_dir:
        candidate_roots.append(Path(env_repo_dir).expanduser())
    candidate_roots.append(current_dir)
    candidate_roots.extend(Path(__file__).resolve().parents)

    seen: set[Path] = set()
    for root in candidate_roots:
        resolved = root.expanduser().resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        src_dir = resolved / "src"
        if not (src_dir / "atelier" / "__init__.py").is_file():
            continue
        src_dir_entry = str(src_dir)
        sys.path[:] = [entry for entry in sys.path if entry != src_dir_entry]
        sys.path.insert(0, src_dir_entry)
        return resolved
    return None


_BOOTSTRAP_REPO_ROOT = _bootstrap_source_import()

from atelier.runtime_env import (  # noqa: E402
    ensure_projected_runtime_dependency,
    maybe_reexec_projected_repo_runtime,
)

if __name__ == "__main__":
    maybe_reexec_projected_repo_runtime(
        repo_root=_BOOTSTRAP_REPO_ROOT,
        script_path=Path(__file__).resolve(),
    )
    ensure_projected_runtime_dependency(
        repo_root=_BOOTSTRAP_REPO_ROOT,
        script_path=Path(__file__).resolve(),
    )

from atelier import auto_export  # noqa: E402
from atelier.beads_context import resolve_runtime_repo_dir_hint  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issue-id", required=True, help="Bead id to export")
    parser.add_argument("--provider", default="", help="Optional provider override")
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
    parser.add_argument(
        "--force",
        action="store_true",
        help="Bypass project auto-export toggle",
    )
    args = parser.parse_args()

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

    result = auto_export.auto_export_issue(
        args.issue_id,
        context=context,
        provider_slug=str(args.provider).strip() or None,
        force=bool(args.force),
    )
    print(f"{result.status}: {result.message}")
    if result.retry_command:
        print(f"retry: {result.retry_command}", file=sys.stderr)
    if result.status == "failed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()

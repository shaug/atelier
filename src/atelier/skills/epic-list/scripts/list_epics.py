#!/usr/bin/env python3
"""Render epics in a stable, glanceable format for planner/overseer use."""

from __future__ import annotations

import argparse
import os
import sys
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


def _bootstrap_source_import() -> None:
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
        return


_bootstrap_source_import()

from atelier import planner_overview
from atelier.beads_context import resolve_runtime_repo_dir_hint, resolve_skill_beads_context

# Re-exported for tests that load this script directly.
_status_bucket = planner_overview._status_bucket  # pyright: ignore[reportPrivateUsage]
_render_epics = planner_overview.render_epics


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


def _run_bd_list(beads_dir: str | None, repo_dir: str | None = None) -> list[dict[str, object]]:
    beads_root, repo_root, _override_warning = _resolve_context(
        beads_dir=beads_dir,
        repo_dir=repo_dir,
    )
    return planner_overview.list_epics(beads_root=beads_root, repo_root=repo_root)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--show-drafts",
        action="store_true",
        help="include deferred epics alongside active non-closed epics",
    )
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

    beads_dir = str(args.beads_dir).strip() or None
    repo_dir = str(args.repo_dir).strip() or None
    beads_root, repo_root, override_warning = _resolve_context(
        beads_dir=beads_dir,
        repo_dir=repo_dir,
    )
    if override_warning:
        print(override_warning, file=sys.stderr)
    if not beads_root.exists():
        print(f"error: beads dir not found: {beads_root}", file=sys.stderr)
        raise SystemExit(1)
    issues = planner_overview.list_epics(beads_root=beads_root, repo_root=repo_root)
    print(_render_epics(issues, show_drafts=bool(args.show_drafts)))


if __name__ == "__main__":
    main()

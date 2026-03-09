#!/usr/bin/env python3
"""Render epics in a stable, glanceable format for planner/overseer use."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SKILLS_ROOT = Path(__file__).resolve().parents[2]
if str(_SKILLS_ROOT) not in sys.path:
    sys.path.insert(0, str(_SKILLS_ROOT))

from _projected_bootstrap import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    bootstrap_projected_atelier_script,
)

_BOOTSTRAP_REPO_ROOT = bootstrap_projected_atelier_script(
    script_path=Path(__file__).resolve(),
    argv=sys.argv[1:],
    require_runtime_health=__name__ == "__main__",
)

from atelier import planner_overview  # noqa: E402
from atelier.beads_context import (  # noqa: E402
    resolve_runtime_repo_dir_hint,
    resolve_skill_beads_context,
)

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

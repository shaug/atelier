#!/usr/bin/env python3
"""Mark a durable coordination message as read via AtelierStore."""

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


def _build_store(*, beads_root: Path, repo_root: Path):
    from atelier.lib.beads import SubprocessBeadsClient
    from atelier.store import build_atelier_store

    client = SubprocessBeadsClient(
        cwd=repo_root,
        beads_root=beads_root,
        env={"BEADS_DIR": str(beads_root)},
    )
    return build_atelier_store(beads=client)


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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--message-id", required=True, help="Message bead id")
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
    store = _build_store(beads_root=beads_root, repo_root=repo_root)

    try:
        from atelier.store import MarkMessageReadRequest

        message = asyncio.run(
            store.mark_message_read(
                MarkMessageReadRequest(message_id=args.message_id.strip()),
            )
        )
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    print(f"message_id: {message.id}")
    print("unread: false")


if __name__ == "__main__":
    main()

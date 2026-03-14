#!/usr/bin/env python3
"""Mark one store-backed coordination message as read."""

from __future__ import annotations

import argparse
import asyncio
import json
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

from atelier.beads_context import (  # noqa: E402
    resolve_runtime_repo_dir_hint,
    resolve_skill_beads_context,
)
from atelier.lib.beads import SubprocessBeadsClient  # noqa: E402
from atelier.store import MarkMessageReadRequest, build_atelier_store  # noqa: E402


def _merge_warnings(*messages: str | None) -> str | None:
    lines = [message for message in messages if isinstance(message, str) and message.strip()]
    if not lines:
        return None
    return "\n".join(lines)


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
    return (
        context.beads_root,
        context.repo_root,
        _merge_warnings(runtime_warning, context.override_warning),
    )


def _build_store(*, beads_root: Path, repo_root: Path):
    client = SubprocessBeadsClient(
        cwd=repo_root,
        beads_root=beads_root,
        env={"BEADS_DIR": str(beads_root)},
    )
    return build_atelier_store(beads=client)


def mark_message_read(*, message_id: str, beads_root: Path, repo_root: Path) -> dict[str, object]:
    store = _build_store(beads_root=beads_root, repo_root=repo_root)
    record = asyncio.run(store.mark_message_read(MarkMessageReadRequest(message_id=message_id)))
    return {
        "id": record.id,
        "thread_id": record.thread_id,
        "thread_kind": record.thread_kind.value if record.thread_kind else None,
        "queue": record.queue,
        "claimed_by": record.claimed_by,
        "read": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("message_id", help="message id to mark read")
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
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit machine-readable JSON",
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

    result = mark_message_read(
        message_id=args.message_id.strip(),
        beads_root=beads_root,
        repo_root=repo_root,
    )
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return
    print(f"message_id: {result['id']}")
    print("read: true")


if __name__ == "__main__":
    main()

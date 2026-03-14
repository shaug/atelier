#!/usr/bin/env python3
"""List store-backed inbox messages for one agent runtime."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
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
from atelier.store import MessageQuery, build_atelier_store  # noqa: E402
from atelier.worker.selection import agent_role  # noqa: E402


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


def _resolve_agent_id(requested_agent_id: str | None) -> str:
    candidate = str(requested_agent_id or "").strip()
    if candidate:
        return candidate
    env_agent_id = os.environ.get("ATELIER_AGENT_ID", "").strip()
    if env_agent_id:
        return env_agent_id
    raise ValueError("mail-inbox requires --agent-id or ATELIER_AGENT_ID")


def _render_message_title(record) -> str:
    title = str(record.title or "").strip() or "(untitled)"
    details: list[str] = []
    if record.thread_id:
        target = record.thread_kind.value if record.thread_kind is not None else "work"
        details.append(f"{target}={record.thread_id}")
    if record.kind:
        details.append(f"kind={record.kind}")
    if record.audience:
        details.append(f"audience={','.join(record.audience)}")
    if record.queue:
        details.append(f"queue={record.queue}")
    detail = f" ({'; '.join(details)})" if details else ""
    return f"{title}{detail}"


def list_inbox_messages(
    *,
    agent_id: str,
    beads_root: Path,
    repo_root: Path,
    unread_only: bool = True,
) -> list[dict[str, object]]:
    runtime_role = agent_role(agent_id)
    if runtime_role is None:
        return []
    store = _build_store(beads_root=beads_root, repo_root=repo_root)
    records = asyncio.run(store.list_messages(MessageQuery(unread_only=unread_only)))
    matches: list[dict[str, object]] = []
    for record in records:
        if runtime_role not in set(record.audience) | set(record.blocking_roles):
            continue
        matches.append(
            {
                "id": record.id,
                "title": _render_message_title(record),
                "thread_id": record.thread_id,
                "thread_kind": record.thread_kind.value if record.thread_kind else None,
                "audience": list(record.audience),
                "blocking_roles": list(record.blocking_roles),
                "queue": record.queue,
                "claimed_by": record.claimed_by,
            }
        )
    return sorted(matches, key=lambda item: (str(item["id"]), str(item["title"])))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--agent-id",
        default="",
        help="agent identity (defaults to ATELIER_AGENT_ID)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="include already-read messages",
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
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit machine-readable JSON",
    )
    args = parser.parse_args()

    agent_id = _resolve_agent_id(args.agent_id)
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

    messages_for_agent = list_inbox_messages(
        agent_id=agent_id,
        beads_root=beads_root,
        repo_root=repo_root,
        unread_only=not bool(args.all),
    )
    if args.json:
        print(json.dumps(messages_for_agent, indent=2, sort_keys=True))
        return
    for item in messages_for_agent:
        print(f"{item['id']}\t{item['title']}")


if __name__ == "__main__":
    main()

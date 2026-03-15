#!/usr/bin/env python3
"""Send a work-threaded message and persist it on the original work item."""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
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

from atelier import messages  # noqa: E402
from atelier.beads_context import (  # noqa: E402
    resolve_runtime_repo_dir_hint,
    resolve_skill_beads_context,
)
from atelier.lib.beads import (  # noqa: E402
    ShowIssueRequest,
    SubprocessBeadsClient,
    UpdateIssueRequest,
)
from atelier.store import (  # noqa: E402
    CreateMessageRequest,
    MessageThreadKind,
    build_atelier_store,
)

_MAX_ASSIGNMENT_ATTEMPTS = 3


@dataclass(frozen=True)
class DispatchOutcome:
    decision: str
    issue_id: str
    recipient: str


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


def _agent_role(agent_id: str) -> str | None:
    parts = [part for part in str(agent_id).split("/") if part]
    if len(parts) >= 2 and parts[0] == "atelier":
        value = parts[1].strip().lower()
        return value or None
    if not parts:
        return None
    return parts[0].strip().lower() or None


def dispatch_message(
    *,
    subject: str,
    body: str,
    to: str,
    from_agent: str,
    thread: str | None,
    reply_to: str | None,
    beads_root: Path,
    cwd: Path,
) -> DispatchOutcome:
    if not thread:
        raise RuntimeError(
            "mail-send requires --thread <epic-or-changeset>; "
            "agent-addressed delivery is not supported"
        )
    audience = _agent_role(to)
    thread_target = messages.infer_thread_target(thread)
    if thread_target not in {"changeset", "epic"}:
        raise RuntimeError("mail-send requires an epic or changeset thread id")

    client = SubprocessBeadsClient(
        cwd=cwd,
        beads_root=beads_root,
        env={"BEADS_DIR": str(beads_root)},
    )
    store = build_atelier_store(beads=client)
    message = asyncio.run(
        store.create_message(
            CreateMessageRequest(
                title=subject,
                body=body,
                sender=from_agent,
                thread_id=thread,
                thread_kind=MessageThreadKind(thread_target),
                audience=(audience,) if audience in {"worker", "planner", "operator"} else (),
                kind=_message_kind(subject=subject, reply_to=reply_to),
                blocking=subject.startswith("NEEDS-DECISION:") or audience == "worker",
                reply_to=reply_to,
            )
        )
    )
    message_id = str(message.id or "").strip()
    if not message_id:
        raise RuntimeError("created message is missing an id")
    _assign_recipient_hint(message_id=message_id, recipient=to, beads=client)
    return DispatchOutcome(decision="delivered", issue_id=message_id, recipient=to)


def _assign_recipient_hint(*, message_id: str, recipient: str, beads) -> None:
    normalized_recipient = recipient.strip()
    if not normalized_recipient:
        raise RuntimeError("mail-send requires a non-empty recipient")
    for _attempt in range(_MAX_ASSIGNMENT_ATTEMPTS):
        asyncio.run(
            beads.update(
                UpdateIssueRequest(
                    issue_id=message_id,
                    assignee=normalized_recipient,
                )
            )
        )
        verified = asyncio.run(beads.show(ShowIssueRequest(issue_id=message_id)))
        if (verified.assignee or "").strip() == normalized_recipient:
            return
    raise RuntimeError(f"message routing assignment could not be verified for {message_id}")


def _message_kind(*, subject: str, reply_to: str | None) -> str:
    normalized_subject = subject.strip()
    if normalized_subject.startswith("NEEDS-DECISION:"):
        return "needs-decision"
    if reply_to:
        return "reply"
    return "instruction"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subject", required=True, help="Message subject")
    parser.add_argument("--body", required=True, help="Message body")
    parser.add_argument("--to", required=True, help="Recipient agent id")
    parser.add_argument("--from", dest="from_agent", required=True, help="Sender agent id")
    parser.add_argument(
        "--thread",
        required=True,
        help="Work thread id (epic or changeset bead id)",
    )
    parser.add_argument("--reply-to", default="", help="Optional reply message id")
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

    try:
        outcome = dispatch_message(
            subject=args.subject,
            body=args.body,
            to=args.to.strip(),
            from_agent=args.from_agent.strip(),
            thread=args.thread.strip() or None,
            reply_to=args.reply_to.strip() or None,
            beads_root=beads_root,
            cwd=repo_root,
        )
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    print("dispatch: delivered")
    print(f"recipient: {outcome.recipient}")
    print(f"message_id: {outcome.issue_id}")


if __name__ == "__main__":
    main()

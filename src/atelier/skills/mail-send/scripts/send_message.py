#!/usr/bin/env python3
"""Send a threaded work message and persist it on the original work item."""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path


def _bootstrap_source_import() -> None:
    src_dir = Path(__file__).resolve().parents[4]
    if src_dir.is_dir() and str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))


_bootstrap_source_import()

from atelier import agent_home, beads, messages  # noqa: E402


@dataclass(frozen=True)
class DispatchOutcome:
    decision: str
    issue_id: str
    recipient: str


def _agent_role(agent_id: str) -> str | None:
    role, _name, _session = agent_home.parse_agent_identity(agent_id)
    if role:
        return role.strip().lower() or None
    parts = [part for part in str(agent_id).split("/") if part]
    if not parts:
        return None
    return parts[0].strip().lower() or None


def _thread_metadata(
    *,
    thread: str | None,
    recipient: str,
    subject: str,
) -> dict[str, object]:
    if not thread:
        return {}
    metadata: dict[str, object] = {}
    recipient_role = _agent_role(recipient)
    if recipient_role is None:
        return metadata
    if recipient_role == "worker":
        metadata["blocking_roles"] = ["worker"]
        return metadata
    if subject.startswith("NEEDS-DECISION:"):
        metadata["blocking_roles"] = [recipient_role]
    return metadata


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
    metadata: dict[str, object] = {
        "from": from_agent,
        "kind": _message_kind(subject=subject, reply_to=reply_to),
    }
    audience = _agent_role(to)
    if audience in {"worker", "planner", "operator"}:
        metadata["audience"] = [audience]
        metadata["audiences"] = [audience]
    if thread:
        metadata["thread"] = thread
        thread_target = messages.infer_thread_target(thread)
        if thread_target is not None:
            metadata["thread_kind"] = thread_target
            metadata["thread_target"] = thread_target
        metadata["delivery"] = "work-threaded"
        metadata.update(_thread_metadata(thread=thread, recipient=to, subject=subject))
    else:
        metadata["delivery"] = "agent-addressed"
    if subject.startswith("NEEDS-DECISION:"):
        metadata["blocking"] = True
    if reply_to:
        metadata["reply_to"] = reply_to

    message = beads.create_message_bead(
        subject=subject,
        body=body,
        metadata=metadata,
        assignee=to,
        beads_root=beads_root,
        cwd=cwd,
    )
    message_id = str(message.get("id") or "").strip()
    if not message_id:
        raise RuntimeError("created message bead is missing an id")
    return DispatchOutcome(decision="delivered", issue_id=message_id, recipient=to)


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
    parser.add_argument("--thread", default="", help="Optional thread id")
    parser.add_argument("--reply-to", default="", help="Optional reply message id")
    parser.add_argument(
        "--beads-dir",
        default="",
        help="Beads directory override (defaults to BEADS_DIR or repo .beads)",
    )
    args = parser.parse_args()

    beads_dir = str(args.beads_dir).strip() or None
    if beads_dir:
        beads_root = Path(beads_dir).expanduser().resolve()
    else:
        beads_root = Path(os.environ.get("BEADS_DIR", str(Path.cwd() / ".beads"))).expanduser()
        beads_root = beads_root.resolve()
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
            cwd=Path.cwd(),
        )
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    print("dispatch: delivered")
    print(f"recipient: {outcome.recipient}")
    print(f"message_id: {outcome.issue_id}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Send a planner message or reroute to executable work for inactive workers."""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from dataclasses import dataclass
from pathlib import Path


def _bootstrap_source_import() -> None:
    src_dir = Path(__file__).resolve().parents[4]
    if src_dir.is_dir() and str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))


_bootstrap_source_import()

from atelier import agent_home, beads  # noqa: E402


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


def _is_inactive_worker(agent_id: str) -> bool:
    return _agent_role(agent_id) == "worker" and not agent_home.is_session_agent_active(agent_id)


def _build_reroute_acceptance() -> str:
    return (
        "- Dispatch intent is executed by an active worker session.\n"
        "- Routing metadata identifies the inactive recipient and reroute decision."
    )


def _build_reroute_description(
    *,
    subject: str,
    body: str,
    sender: str,
    recipient: str,
    thread: str | None,
    reply_to: str | None,
) -> str:
    timestamp = dt.datetime.now(tz=dt.timezone.utc).replace(microsecond=0).isoformat()
    lines = [
        "Intent",
        "Planner dispatch was blocked because the recipient worker session is inactive.",
        "",
        "Routing diagnostics",
        "routing.decision: rerouted_inactive_worker",
        f"routing.inactive_worker: {recipient}",
        f"routing.sender: {sender}",
        f"routing.original_subject: {subject}",
        f"routing.generated_at: {timestamp}",
    ]
    if thread:
        lines.append(f"routing.thread: {thread}")
    if reply_to:
        lines.append(f"routing.reply_to: {reply_to}")
    body_text = body.strip()
    if body_text:
        lines.extend(["", "Original message", body_text])
    return "\n".join(lines).strip()


def _create_reroute_epic(
    *,
    subject: str,
    body: str,
    sender: str,
    recipient: str,
    thread: str | None,
    reply_to: str | None,
    beads_root: Path,
    cwd: Path,
) -> dict[str, object]:
    description = _build_reroute_description(
        subject=subject,
        body=body,
        sender=sender,
        recipient=recipient,
        thread=thread,
        reply_to=reply_to,
    )
    title = f"Rerouted worker dispatch: {subject}"
    result = beads.run_bd_command(
        [
            "create",
            "--type",
            "epic",
            "--label",
            "at:epic",
            "--status",
            "open",
            "--title",
            title,
            "--acceptance",
            _build_reroute_acceptance(),
            "--description",
            description,
            "--silent",
        ],
        beads_root=beads_root,
        cwd=cwd,
    )
    issue_id = (result.stdout or "").strip()
    if not issue_id:
        raise RuntimeError("failed to create rerouted executable epic")
    issues = beads.run_bd_json(["show", issue_id], beads_root=beads_root, cwd=cwd)
    return issues[0] if issues else {"id": issue_id, "title": title}


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
    if _agent_role(from_agent) == "planner" and _is_inactive_worker(to):
        rerouted = _create_reroute_epic(
            subject=subject,
            body=body,
            sender=from_agent,
            recipient=to,
            thread=thread,
            reply_to=reply_to,
            beads_root=beads_root,
            cwd=cwd,
        )
        rerouted_id = str(rerouted.get("id") or "").strip()
        if not rerouted_id:
            raise RuntimeError("rerouted executable epic is missing an id")
        return DispatchOutcome(
            decision="rerouted_inactive_worker",
            issue_id=rerouted_id,
            recipient=to,
        )

    metadata: dict[str, object] = {"from": from_agent}
    if thread:
        metadata["thread"] = thread
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

    if outcome.decision == "rerouted_inactive_worker":
        print("dispatch: rerouted_inactive_worker")
        print(f"inactive_worker: {outcome.recipient}")
        print(f"rerouted_epic: {outcome.issue_id}")
        return

    print("dispatch: delivered")
    print(f"recipient: {outcome.recipient}")
    print(f"message_id: {outcome.issue_id}")


if __name__ == "__main__":
    main()

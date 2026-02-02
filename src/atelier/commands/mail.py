"""Mail command helpers for message beads."""

from __future__ import annotations

from pathlib import Path

from .. import agent_home, beads, config
from ..io import die, say
from .resolve import resolve_current_project_with_repo_root


def _resolve_agent_id(
    project_root: Path,
    project_config: config.ProjectConfig,
    *,
    role: str,
    override: str | None = None,
) -> str:
    if override:
        return override.strip()
    home = agent_home.resolve_agent_home(project_root, project_config, role=role)
    return home.agent_id


def send_mail(args: object) -> None:
    """Send a message bead to a recipient."""
    project_root, project_config, _enlistment, repo_root = (
        resolve_current_project_with_repo_root()
    )
    project_data_dir = config.resolve_project_data_dir(project_root, project_config)
    beads_root = config.resolve_beads_root(project_data_dir, repo_root)

    subject = getattr(args, "subject", None) or ""
    if not subject:
        die("subject is required")
    body = getattr(args, "body", None) or ""
    body_file = getattr(args, "body_file", None)
    if body_file:
        body = Path(str(body_file)).read_text(encoding="utf-8")
    if not body:
        die("body is required")
    recipient = getattr(args, "to", None) or ""
    if not recipient:
        die("recipient is required")

    sender = _resolve_agent_id(
        project_data_dir,
        project_config,
        role="planner",
        override=getattr(args, "sender", None),
    )
    metadata = {"from": sender}
    thread = getattr(args, "thread", None)
    if thread:
        metadata["thread"] = thread
    reply_to = getattr(args, "reply_to", None)
    if reply_to:
        metadata["reply_to"] = reply_to

    message = beads.create_message_bead(
        subject=subject,
        body=body,
        metadata=metadata,
        assignee=recipient,
        beads_root=beads_root,
        cwd=repo_root,
    )
    message_id = message.get("id", "")
    say(f"Sent message {message_id}")


def inbox(args: object) -> None:
    """List message beads assigned to the agent."""
    project_root, project_config, _enlistment, repo_root = (
        resolve_current_project_with_repo_root()
    )
    project_data_dir = config.resolve_project_data_dir(project_root, project_config)
    beads_root = config.resolve_beads_root(project_data_dir, repo_root)

    agent_id = _resolve_agent_id(
        project_data_dir,
        project_config,
        role="worker",
        override=getattr(args, "agent", None),
    )
    unread_only = not bool(getattr(args, "all", False))
    messages = beads.list_inbox_messages(
        agent_id, beads_root=beads_root, cwd=repo_root, unread_only=unread_only
    )
    if not messages:
        say("No messages found.")
        return
    say("Inbox:")
    for message in messages:
        message_id = message.get("id") or ""
        title = message.get("title") or ""
        say(f"- {message_id} {title}")


def mark_read(args: object) -> None:
    """Mark a message bead as read."""
    message_id = getattr(args, "message_id", None) or ""
    if not message_id:
        die("message id is required")
    project_root, project_config, _enlistment, repo_root = (
        resolve_current_project_with_repo_root()
    )
    project_data_dir = config.resolve_project_data_dir(project_root, project_config)
    beads_root = config.resolve_beads_root(project_data_dir, repo_root)
    beads.mark_message_read(message_id, beads_root=beads_root, cwd=repo_root)
    say(f"Marked message {message_id} as read")

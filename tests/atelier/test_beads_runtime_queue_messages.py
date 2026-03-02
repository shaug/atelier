from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass, field
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from atelier import messages
from atelier.beads_runtime import queue_messages


@dataclass
class _QueueClient(queue_messages.QueueMessagesClient):
    issues: dict[str, dict[str, object]] = field(default_factory=dict)
    commands: list[list[str]] = field(default_factory=list)
    create_args: list[str] | None = None
    create_description: str | None = None

    def issue_write_lock(self, issue_id: str, beads_root: Path):
        del issue_id, beads_root
        return nullcontext()

    def run_bd_json(
        self,
        args: list[str],
        *,
        beads_root: Path,
        cwd: Path,
    ) -> list[dict[str, object]]:
        del beads_root, cwd
        if args[:1] == ["show"] and len(args) >= 2:
            issue = self.issues.get(args[1])
            return [dict(issue)] if issue else []
        if args[:1] == ["list"]:
            return [dict(issue) for issue in self.issues.values()]
        return []

    def run_bd_command(
        self,
        args: list[str],
        *,
        beads_root: Path,
        cwd: Path,
        allow_failure: bool = False,
    ) -> object:
        del beads_root, cwd, allow_failure
        self.commands.append(args)
        if args[:3] == ["update", "msg-1", "--claim"]:
            issue = self.issues.get("msg-1")
            if issue is not None:
                issue["assignee"] = "agent-1"
        return CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    def create_issue_with_body(
        self,
        args: list[str],
        description: str,
        *,
        beads_root: Path,
        cwd: Path,
    ) -> str:
        del beads_root, cwd
        self.create_args = list(args)
        self.create_description = description
        issue_id = "msg-created"
        self.issues[issue_id] = {"id": issue_id, "title": "Hello", "description": description}
        return issue_id

    def update_issue_description(
        self,
        issue_id: str,
        description: str,
        *,
        beads_root: Path,
        cwd: Path,
    ) -> None:
        del beads_root, cwd
        issue = self.issues[issue_id]
        issue["description"] = description

    def issue_label(self, name: str) -> str:
        return f"at:{name}"

    def die(self, message: str) -> None:
        raise RuntimeError(message)


def test_create_message_bead_uses_client_and_returns_created_issue() -> None:
    client = _QueueClient()

    created = queue_messages.create_message_bead(
        subject="Hello",
        body="Body",
        metadata={"from": "alice"},
        assignee="bob",
        beads_root=Path("/beads"),
        cwd=Path("/repo"),
        client=client,
    )

    assert created["id"] == "msg-created"
    assert client.create_args is not None
    assert "at:message" in " ".join(client.create_args)
    assert "at:unread" in " ".join(client.create_args)
    assert client.create_description is not None
    assert "from: alice" in client.create_description


def test_claim_queue_message_sets_claim_metadata() -> None:
    client = _QueueClient(
        issues={
            "msg-1": {
                "id": "msg-1",
                "description": messages.render_message({"queue": "triage"}, "Body"),
                "assignee": None,
            }
        }
    )

    claimed = queue_messages.claim_queue_message(
        "msg-1",
        "agent-1",
        beads_root=Path("/beads"),
        cwd=Path("/repo"),
        queue="triage",
        client=client,
        description_update_max_attempts=3,
    )

    description = str(claimed.get("description") or "")
    assert "claimed_by: agent-1" in description
    assert "claimed_at:" in description
    assert any(cmd[:3] == ["update", "msg-1", "--claim"] for cmd in client.commands)


def test_claim_queue_message_fails_closed_when_queue_mismatch() -> None:
    client = _QueueClient(
        issues={
            "msg-1": {
                "id": "msg-1",
                "description": messages.render_message({"queue": "triage"}, "Body"),
                "assignee": None,
            }
        }
    )

    with pytest.raises(RuntimeError, match="message msg-1 is not in queue 'ops'"):
        queue_messages.claim_queue_message(
            "msg-1",
            "agent-1",
            beads_root=Path("/beads"),
            cwd=Path("/repo"),
            queue="ops",
            client=client,
            description_update_max_attempts=3,
        )

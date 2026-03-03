from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass, field
from pathlib import Path
from subprocess import CompletedProcess
from typing import NoReturn

import pytest

from atelier import messages
from atelier.beads_runtime import queue_messages


@dataclass
class _QueueClient:
    issues: dict[str, dict[str, object]] = field(default_factory=dict)
    commands: list[list[str]] = field(default_factory=list)
    create_args: list[str] | None = None
    create_description: str | None = None
    beads_root: Path = Path("/beads")
    cwd: Path = Path("/repo")

    def issue_write_lock(self, issue_id: str):
        del issue_id
        return nullcontext()

    def show_issue(self, issue_id: str) -> dict[str, object] | None:
        issue = self.issues.get(issue_id)
        return dict(issue) if issue else None

    def create_issue_with_body(self, args: list[str], description: str) -> str:
        self.create_args = [*args, "--body-file", "/tmp/unused"]
        self.create_description = description
        issue_id = "msg-created"
        title = args[args.index("--title") + 1]
        self.issues[issue_id] = {"id": issue_id, "title": title, "description": description}
        return issue_id

    def update_issue_description(self, issue_id: str, description: str) -> None:
        issue = self.issues[issue_id]
        issue["description"] = description

    def bd(
        self,
        args: list[str],
        *,
        json_mode: bool = False,
        allow_failure: bool = False,
    ) -> CompletedProcess[str] | list[dict[str, object]]:
        del allow_failure
        if json_mode:
            if args[:1] == ["show"] and len(args) >= 2:
                issue = self.issues.get(args[1])
                return [dict(issue)] if issue else []
            if args[:1] == ["list"]:
                return [dict(issue) for issue in self.issues.values()]
            return []
        self.commands.append(list(args))
        if args[:1] == ["create"]:
            self.create_args = list(args)
            body_file = args[args.index("--body-file") + 1]
            description = Path(body_file).read_text(encoding="utf-8")
            self.create_description = description
            issue_id = "msg-created"
            title = args[args.index("--title") + 1]
            self.issues[issue_id] = {"id": issue_id, "title": title, "description": description}
            return CompletedProcess(args=args, returncode=0, stdout=f"{issue_id}\n", stderr="")
        if args[:3] == ["update", "msg-1", "--claim"]:
            issue = self.issues.get("msg-1")
            if issue is not None:
                issue["assignee"] = "agent-1"
        if args[:1] == ["update"] and "--body-file" in args and len(args) >= 2:
            issue_id = args[1]
            body_file = args[args.index("--body-file") + 1]
            self.update_issue_description(
                issue_id,
                Path(body_file).read_text(encoding="utf-8"),
            )
        return CompletedProcess(args=args, returncode=0, stdout="", stderr="")


def _fail(message: str) -> NoReturn:
    raise RuntimeError(message)


def test_create_message_bead_uses_client_and_returns_created_issue() -> None:
    client = _QueueClient()

    created = queue_messages.create_message_bead(
        subject="Hello",
        body="Body",
        metadata={"from": "alice"},
        assignee="bob",
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
        queue="triage",
        client=client,
        fail=_fail,
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
            queue="ops",
            client=client,
            fail=_fail,
            description_update_max_attempts=3,
        )

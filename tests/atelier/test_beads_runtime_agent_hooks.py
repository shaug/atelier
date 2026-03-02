from __future__ import annotations

import json
from contextlib import nullcontext
from dataclasses import dataclass, field
from pathlib import Path
from subprocess import CompletedProcess
from typing import NoReturn

import pytest

from atelier.beads_runtime import agent_hooks


@dataclass
class _AgentHooksClient:
    issues: dict[str, dict[str, object]]
    children: dict[str, list[dict[str, object]]] = field(default_factory=dict)
    slots: dict[str, str] = field(default_factory=dict)
    commands: list[list[str]] = field(default_factory=list)
    claim_assignee: str = "agent"
    beads_root: Path = Path("/beads")
    cwd: Path = Path("/repo")

    def issue_write_lock(self, issue_id: str):
        del issue_id
        return nullcontext()

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
            if args[:2] == ["list", "--parent"] and len(args) >= 3:
                return [dict(child) for child in self.children.get(args[2], [])]
            return []

        self.commands.append(list(args))

        if args[:2] == ["slot", "show"] and len(args) >= 3:
            hook = self.slots.get(args[2])
            payload = {"hook": hook} if hook else {}
            return CompletedProcess(
                args=args, returncode=0, stdout=json.dumps(payload) + "\n", stderr=""
            )
        if args[:2] == ["slot", "set"] and len(args) >= 5:
            self.slots[args[2]] = args[4]
            return CompletedProcess(args=args, returncode=0, stdout="", stderr="")
        if args[:2] == ["slot", "clear"] and len(args) >= 3:
            self.slots.pop(args[2], None)
            return CompletedProcess(args=args, returncode=0, stdout="", stderr="")

        if args[:3] == ["update", "epic-1", "--claim"]:
            self.issues["epic-1"]["assignee"] = self.claim_assignee
            return CompletedProcess(args=args, returncode=0, stdout="", stderr="")

        if args[:2] == ["update", "epic-1"] and "--status" in args:
            issue = self.issues["epic-1"]
            status_index = args.index("--status")
            issue["status"] = args[status_index + 1]
            labels = list(issue.get("labels") or [])
            for index, value in enumerate(args):
                if value != "--add-label" or index + 1 >= len(args):
                    continue
                label = args[index + 1]
                if label not in labels:
                    labels.append(label)
            issue["labels"] = labels
            return CompletedProcess(args=args, returncode=0, stdout="", stderr="")

        if args[:1] == ["update"] and "--body-file" in args and len(args) >= 2:
            issue_id = args[1]
            body_file = args[args.index("--body-file") + 1]
            self.issues[issue_id]["description"] = Path(body_file).read_text(encoding="utf-8")
            return CompletedProcess(args=args, returncode=0, stdout="", stderr="")

        return CompletedProcess(args=args, returncode=0, stdout="", stderr="")


def _fail(message: str) -> NoReturn:
    raise RuntimeError(message)


def test_get_agent_hook_backfills_slot_from_description() -> None:
    client = _AgentHooksClient(
        issues={"agent-1": {"id": "agent-1", "description": "hook_bead: epic-2\n"}}
    )

    hook = agent_hooks.get_agent_hook(
        "agent-1",
        client=client,
        hook_slot_name="hook",
    )

    assert hook == "epic-2"
    assert client.slots["agent-1"] == "epic-2"


def test_claim_epic_backfills_epic_label_for_standalone_changeset() -> None:
    client = _AgentHooksClient(
        issues={
            "epic-1": {
                "id": "epic-1",
                "status": "open",
                "labels": [],
                "assignee": None,
                "type": "task",
            }
        },
        claim_assignee="agent",
    )

    claimed = agent_hooks.claim_epic(
        "epic-1",
        "agent",
        allow_takeover_from=None,
        client=client,
        fail=_fail,
        hooked_label="at:hooked",
        epic_label="at:epic",
    )

    labels = list(claimed.get("labels") or [])
    assert "at:hooked" in labels
    assert "at:epic" in labels
    update_commands = [cmd for cmd in client.commands if "--status" in cmd]
    assert update_commands
    assert "--add-label" in update_commands[-1]


def test_claim_epic_rejects_planner_owned_executable_work() -> None:
    client = _AgentHooksClient(
        issues={
            "epic-1": {
                "id": "epic-1",
                "status": "open",
                "labels": ["at:epic"],
                "assignee": "atelier/planner/codex/p111",
            }
        }
    )

    with pytest.raises(RuntimeError, match="planner agents cannot own executable work"):
        agent_hooks.claim_epic(
            "epic-1",
            "atelier/worker/codex/p222",
            allow_takeover_from=None,
            client=client,
            fail=_fail,
            hooked_label="at:hooked",
            epic_label="at:epic",
        )


def test_set_agent_hook_updates_slot_and_description() -> None:
    issues = {"agent-1": {"id": "agent-1", "description": "role: worker\n"}}
    client = _AgentHooksClient(issues=issues)

    agent_hooks.set_agent_hook(
        "agent-1",
        "epic-9",
        client=client,
        fail=_fail,
        hook_slot_name="hook",
    )

    assert client.slots["agent-1"] == "epic-9"
    assert "hook_bead: epic-9" in str(issues["agent-1"].get("description") or "")

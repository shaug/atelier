from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

from atelier import messages
from atelier.store import MessageQuery, build_atelier_store
from atelier.testing.beads import IssueFixtureBuilder, build_in_memory_beads_client

BUILDER = IssueFixtureBuilder()


def _load_script(skill_name: str, script_name: str):
    path = (
        Path(__file__).resolve().parents[3]
        / "src"
        / "atelier"
        / "skills"
        / skill_name
        / "scripts"
        / script_name
    )
    spec = importlib.util.spec_from_file_location(f"test_{skill_name}_{script_name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_mail_inbox_lists_messages_for_runtime_role() -> None:
    module = _load_script("mail-inbox", "list_inbox.py")
    client, _store = build_in_memory_beads_client(
        issues=(
            BUILDER.issue(
                "at-msg-1",
                title="Planner decision",
                issue_type="message",
                labels=("at:message", "at:unread"),
                description=messages.render_message(
                    {
                        "from": "atelier/worker/codex/p100",
                        "thread": "at-epic.1",
                        "thread_kind": "changeset",
                        "audience": ["planner"],
                        "kind": "needs-decision",
                        "blocking": True,
                    },
                    "Choose the next action.",
                ),
            ),
            BUILDER.issue(
                "at-msg-2",
                title="Worker note",
                issue_type="message",
                labels=("at:message", "at:unread"),
                description=messages.render_message(
                    {
                        "from": "atelier/planner/codex/p200",
                        "thread": "at-epic.2",
                        "thread_kind": "changeset",
                        "audience": ["worker"],
                        "blocking": True,
                    },
                    "Worker follow-up.",
                ),
            ),
        )
    )
    module._build_store = lambda **_kwargs: build_atelier_store(beads=client)

    inbox = module.list_inbox_messages(
        agent_id="atelier/planner/codex/p200",
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
    )

    assert [item["id"] for item in inbox] == ["at-msg-1"]
    assert "changeset=at-epic.1" in inbox[0]["title"]
    assert inbox[0]["blocking_roles"] == ["planner"]


def test_mail_mark_read_updates_store_read_state() -> None:
    module = _load_script("mail-mark-read", "mark_read.py")
    client, _store = build_in_memory_beads_client(
        issues=(
            BUILDER.issue(
                "at-msg-1",
                title="Planner decision",
                issue_type="message",
                labels=("at:message", "at:unread"),
                description=messages.render_message(
                    {
                        "from": "atelier/worker/codex/p100",
                        "thread": "at-epic.1",
                        "thread_kind": "changeset",
                        "audience": ["planner"],
                    },
                    "Choose the next action.",
                ),
            ),
        )
    )
    module._build_store = lambda **_kwargs: build_atelier_store(beads=client)

    result = module.mark_message_read(
        message_id="at-msg-1",
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
    )

    unread_messages = asyncio.run(
        build_atelier_store(beads=client).list_messages(MessageQuery(unread_only=True))
    )
    assert result["id"] == "at-msg-1"
    assert result["read"] is True
    assert unread_messages == ()


def test_mail_queue_claim_sets_claim_metadata_via_store() -> None:
    module = _load_script("mail-queue-claim", "claim_message.py")
    client, _store = build_in_memory_beads_client(
        issues=(
            BUILDER.issue(
                "at-msg-1",
                title="Planner queue",
                issue_type="message",
                labels=("at:message", "at:unread"),
                description=messages.render_message(
                    {
                        "from": "atelier/worker/codex/p100",
                        "thread": "at-epic.1",
                        "thread_kind": "changeset",
                        "queue": "planner",
                    },
                    "Pick this up next.",
                ),
            ),
        )
    )
    module._build_store = lambda **_kwargs: build_atelier_store(beads=client)

    result = module.claim_message(
        message_id="at-msg-1",
        claimed_by="atelier/planner/codex/p200",
        queue="planner",
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
    )

    claimed = asyncio.run(build_atelier_store(beads=client).list_messages(MessageQuery()))[0]
    assert result["claimed_by"] == "atelier/planner/codex/p200"
    assert result["claimed_at"]
    assert claimed.claimed_by == "atelier/planner/codex/p200"
    assert claimed.queue == "planner"


def test_hook_status_reads_store_hook() -> None:
    module = _load_script("hook-status", "hook_status.py")
    client, issue_store = build_in_memory_beads_client(
        issues=(
            BUILDER.issue(
                "atelier/worker/codex/p200",
                title="atelier/worker/codex/p200",
                issue_type="agent",
                labels=("at:agent",),
                description="agent_id: atelier/worker/codex/p200\nhook_bead: null\n",
            ),
        )
    )
    issue_store.set_slot("atelier/worker/codex/p200", "hook", "at-epic")
    module._build_store = lambda **_kwargs: build_atelier_store(beads=client)

    result = module.hook_status(
        agent_id="atelier/worker/codex/p200",
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
    )

    assert result == {
        "agent_id": "atelier/worker/codex/p200",
        "hook_bead": "at-epic",
    }

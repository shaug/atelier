from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from atelier import messages


def _load_script_module():
    script_path = (
        Path(__file__).resolve().parents[3]
        / "src"
        / "atelier"
        / "skills"
        / "mail-send"
        / "scripts"
        / "send_message.py"
    )
    spec = importlib.util.spec_from_file_location("mail_send_script", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _FakeStore:
    def __init__(self, issue_id: str) -> None:
        self.issue_id = issue_id
        self.request = None

    async def create_message(self, request):
        self.request = request
        return SimpleNamespace(id=self.issue_id)


class _FakeBeads:
    def __init__(self, *, assignee: str) -> None:
        self.assignee = assignee
        self.update_request = None
        self.show_request = None

    async def update(self, request):
        self.update_request = request
        return SimpleNamespace(id=request.issue_id, assignee=request.assignee)

    async def show(self, request):
        self.show_request = request
        return SimpleNamespace(id=request.issue_id, assignee=self.assignee)


def _wire_store(module, *, store: _FakeStore, beads: _FakeBeads) -> None:
    module.build_atelier_store = lambda **_kwargs: store
    module.SubprocessBeadsClient = lambda **_kwargs: beads


def test_dispatch_message_delivers_store_backed_worker_message() -> None:
    module = _load_script_module()
    fake_store = _FakeStore("at-msg-1")
    fake_beads = _FakeBeads(assignee="atelier/worker/codex/p101-t1")
    _wire_store(module, store=fake_store, beads=fake_beads)

    result = module.dispatch_message(
        subject="Need follow-up",
        body="Please investigate.",
        to="atelier/worker/codex/p101-t1",
        from_agent="atelier/planner/codex/p202-t2",
        thread="at-thread-1.1",
        reply_to="at-msg-0",
        beads_root=Path("/beads"),
        cwd=Path("/repo"),
    )

    assert result.decision == "delivered"
    assert result.issue_id == "at-msg-1"
    request = fake_store.request
    assert request.title == "Need follow-up"
    assert request.body == "Please investigate."
    assert request.sender == "atelier/planner/codex/p202-t2"
    assert request.thread_id == "at-thread-1.1"
    assert request.thread_kind.value == "changeset"
    assert request.audience == ("worker",)
    assert request.kind == "reply"
    assert request.reply_to == "at-msg-0"
    assert request.blocking is True
    assert fake_beads.update_request.assignee == "atelier/worker/codex/p101-t1"
    assert fake_beads.show_request.issue_id == "at-msg-1"


def test_dispatch_message_infers_epic_thread_kind_for_top_level_work_thread() -> None:
    module = _load_script_module()
    fake_store = _FakeStore("at-msg-1")
    fake_beads = _FakeBeads(assignee="atelier/worker/codex/p101-t1")
    _wire_store(module, store=fake_store, beads=fake_beads)

    result = module.dispatch_message(
        subject="Need follow-up",
        body="Please investigate.",
        to="atelier/worker/codex/p101-t1",
        from_agent="atelier/planner/codex/p202-t2",
        thread="at-ue6aj",
        reply_to=None,
        beads_root=Path("/beads"),
        cwd=Path("/repo"),
    )

    assert result.decision == "delivered"
    assert result.issue_id == "at-msg-1"
    assert fake_store.request.thread_kind.value == "epic"


def test_inactive_worker_threaded_message_is_discoverable_by_later_worker() -> None:
    module = _load_script_module()
    fake_store = _FakeStore("at-msg-6")
    fake_beads = _FakeBeads(assignee="atelier/worker/codex/p404-t4")
    _wire_store(module, store=fake_store, beads=fake_beads)

    result = module.dispatch_message(
        subject="Resume blocked work",
        body="Finish the pending review feedback before coding.",
        to="atelier/worker/codex/p404-t4",
        from_agent="atelier/planner/codex/p202-t2",
        thread="at-es93n.1",
        reply_to=None,
        beads_root=Path("/beads"),
        cwd=Path("/repo"),
    )

    assert result.decision == "delivered"
    request = fake_store.request
    issue = {
        "id": result.issue_id,
        "title": request.title,
        "description": messages.render_message(
            {
                "from": request.sender,
                "delivery": "work-threaded",
                "thread": request.thread_id,
                "thread_kind": request.thread_kind.value,
                "audience": list(request.audience),
                "kind": request.kind,
                "blocking": request.blocking,
                "reply_to": request.reply_to,
            },
            request.body,
        ),
    }

    assert messages.message_blocks_runtime(
        issue,
        runtime_role="worker",
        thread_ids={"at-es93n.1"},
    )
    assert messages.work_thread_routing(issue).thread_id == "at-es93n.1"


def test_dispatch_message_without_thread_fails_closed() -> None:
    module = _load_script_module()

    with pytest.raises(RuntimeError, match="mail-send requires --thread"):
        module.dispatch_message(
            subject="Heads up",
            body="FYI",
            to="atelier/worker/codex/p404-t4",
            from_agent="atelier/worker/codex/p505-t5",
            thread=None,
            reply_to=None,
            beads_root=Path("/beads"),
            cwd=Path("/repo"),
        )


def test_dispatch_message_threaded_needs_decision_to_planner_sets_explicit_routing() -> None:
    module = _load_script_module()
    fake_store = _FakeStore("at-msg-3")
    fake_beads = _FakeBeads(assignee="atelier/planner/codex/p202-t2")
    _wire_store(module, store=fake_store, beads=fake_beads)

    result = module.dispatch_message(
        subject="NEEDS-DECISION: Publish incomplete (at-epic.1)",
        body="Pick the next publish action.",
        to="atelier/planner/codex/p202-t2",
        from_agent="atelier/worker/codex/p101-t1",
        thread="at-epic.1",
        reply_to=None,
        beads_root=Path("/beads"),
        cwd=Path("/repo"),
    )

    assert result.decision == "delivered"
    request = fake_store.request
    assert request.thread_kind.value == "changeset"
    assert request.audience == ("planner",)
    assert request.blocking is True
    assert request.kind == "needs-decision"


def test_dispatch_message_fails_closed_when_recipient_hint_cannot_be_verified() -> None:
    module = _load_script_module()
    fake_store = _FakeStore("at-msg-9")
    fake_beads = _FakeBeads(assignee="atelier/worker/codex/p000")
    _wire_store(module, store=fake_store, beads=fake_beads)

    with pytest.raises(RuntimeError, match="routing assignment could not be verified"):
        module.dispatch_message(
            subject="Need follow-up",
            body="Please investigate.",
            to="atelier/worker/codex/p101-t1",
            from_agent="atelier/planner/codex/p202-t2",
            thread="at-thread-1.1",
            reply_to=None,
            beads_root=Path("/beads"),
            cwd=Path("/repo"),
        )

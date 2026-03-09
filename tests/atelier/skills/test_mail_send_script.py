from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

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


def test_dispatch_message_delivers_to_active_worker() -> None:
    module = _load_script_module()
    with (
        patch.object(module.agent_home, "is_session_agent_active", return_value=True),
        patch.object(
            module.beads, "create_message_bead", return_value={"id": "at-msg-1"}
        ) as create,
    ):
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
    call = create.call_args.kwargs
    assert call["assignee"] == "atelier/worker/codex/p101-t1"
    assert call["metadata"]["from"] == "atelier/planner/codex/p202-t2"
    assert call["metadata"]["delivery"] == "work-threaded"
    assert call["metadata"]["thread"] == "at-thread-1.1"
    assert call["metadata"]["thread_kind"] == "changeset"
    assert call["metadata"]["thread_target"] == "changeset"
    assert call["metadata"]["audience"] == ["worker"]
    assert call["metadata"]["audiences"] == ["worker"]
    assert call["metadata"]["blocking_roles"] == ["worker"]
    assert call["metadata"]["kind"] == "reply"
    assert call["metadata"]["reply_to"] == "at-msg-0"


def test_dispatch_message_infers_epic_thread_kind_for_top_level_work_thread() -> None:
    module = _load_script_module()
    with (
        patch.object(module.agent_home, "is_session_agent_active", return_value=True),
        patch.object(
            module.beads, "create_message_bead", return_value={"id": "at-msg-1"}
        ) as create,
    ):
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
    assert create.call_args.kwargs["metadata"]["thread_kind"] == "epic"


def test_dispatch_message_keeps_threaded_message_on_original_work_when_worker_inactive() -> None:
    module = _load_script_module()
    with (
        patch.object(module.agent_home, "is_session_agent_active", return_value=False),
        patch.object(
            module.beads, "create_message_bead", return_value={"id": "at-msg-5"}
        ) as create_message,
    ):
        result = module.dispatch_message(
            subject="Fix failing check",
            body="Please investigate CI logs.",
            to="atelier/worker/codex/p303-t3",
            from_agent="atelier/planner/codex/p202-t2",
            thread="at-es93n.1",
            reply_to=None,
            beads_root=Path("/beads"),
            cwd=Path("/repo"),
        )

    assert result.decision == "delivered"
    assert result.issue_id == "at-msg-5"
    call = create_message.call_args.kwargs
    assert call["assignee"] == "atelier/worker/codex/p303-t3"
    assert call["metadata"]["delivery"] == "work-threaded"
    assert call["metadata"]["thread"] == "at-es93n.1"
    assert call["metadata"]["thread_kind"] == "changeset"
    assert call["metadata"]["thread_target"] == "changeset"
    assert call["metadata"]["audience"] == ["worker"]
    assert call["metadata"]["audiences"] == ["worker"]
    assert call["metadata"]["blocking_roles"] == ["worker"]


def test_inactive_worker_threaded_message_is_discoverable_by_later_worker() -> None:
    module = _load_script_module()
    with (
        patch.object(module.agent_home, "is_session_agent_active", return_value=False),
        patch.object(
            module.beads, "create_message_bead", return_value={"id": "at-msg-6"}
        ) as create_message,
    ):
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
    call = create_message.call_args.kwargs
    issue = {
        "id": result.issue_id,
        "title": "Resume blocked work",
        "assignee": call["assignee"],
        "description": messages.render_message(call["metadata"], call["body"]),
    }

    assert messages.message_blocks_runtime(
        issue,
        runtime_role="worker",
        thread_ids={"at-es93n.1"},
    )
    assert messages.work_thread_routing(issue).thread_id == "at-es93n.1"


def test_dispatch_message_non_planner_sender_does_not_reroute() -> None:
    module = _load_script_module()
    with (
        patch.object(module.agent_home, "is_session_agent_active", return_value=False),
        patch.object(
            module.beads, "create_message_bead", return_value={"id": "at-msg-2"}
        ) as create,
    ):
        result = module.dispatch_message(
            subject="Heads up",
            body="FYI",
            to="atelier/worker/codex/p404-t4",
            from_agent="atelier/worker/codex/p505-t5",
            thread=None,
            reply_to=None,
            beads_root=Path("/beads"),
            cwd=Path("/repo"),
        )

    assert result.decision == "delivered"
    assert result.issue_id == "at-msg-2"
    create.assert_called_once()
    assert create.call_args.kwargs["metadata"]["delivery"] == "agent-addressed"
    assert create.call_args.kwargs["metadata"]["audience"] == ["worker"]
    assert create.call_args.kwargs["metadata"]["kind"] == "instruction"


def test_dispatch_message_threaded_needs_decision_to_planner_sets_explicit_routing() -> None:
    module = _load_script_module()
    with patch.object(
        module.beads, "create_message_bead", return_value={"id": "at-msg-3"}
    ) as create:
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
    call = create.call_args.kwargs
    assert call["metadata"]["delivery"] == "work-threaded"
    assert call["metadata"]["thread_target"] == "changeset"
    assert call["metadata"]["thread_kind"] == "changeset"
    assert call["metadata"]["audience"] == ["planner"]
    assert call["metadata"]["audiences"] == ["planner"]
    assert call["metadata"]["blocking"] is True
    assert call["metadata"]["blocking_roles"] == ["planner"]
    assert call["metadata"]["kind"] == "needs-decision"

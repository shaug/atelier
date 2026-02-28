from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch


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
            thread="at-thread-1",
            reply_to="at-msg-0",
            beads_root=Path("/beads"),
            cwd=Path("/repo"),
        )

    assert result.decision == "delivered"
    assert result.issue_id == "at-msg-1"
    call = create.call_args.kwargs
    assert call["assignee"] == "atelier/worker/codex/p101-t1"
    assert call["metadata"]["from"] == "atelier/planner/codex/p202-t2"
    assert call["metadata"]["thread"] == "at-thread-1"
    assert call["metadata"]["reply_to"] == "at-msg-0"


def test_dispatch_message_reroutes_when_worker_inactive() -> None:
    module = _load_script_module()
    with (
        patch.object(module.agent_home, "is_session_agent_active", return_value=False),
        patch.object(module, "_create_reroute_epic", return_value={"id": "at-epic-5"}) as reroute,
        patch.object(module.beads, "create_message_bead") as create_message,
    ):
        result = module.dispatch_message(
            subject="Fix failing check",
            body="Please investigate CI logs.",
            to="atelier/worker/codex/p303-t3",
            from_agent="atelier/planner/codex/p202-t2",
            thread=None,
            reply_to=None,
            beads_root=Path("/beads"),
            cwd=Path("/repo"),
        )

    assert result.decision == "rerouted_inactive_worker"
    assert result.issue_id == "at-epic-5"
    reroute.assert_called_once()
    create_message.assert_not_called()


def test_create_reroute_epic_writes_diagnostics_without_status_flag() -> None:
    module = _load_script_module()
    captured_args: list[str] = []

    def _fake_run_bd_command(args: list[str], *, beads_root: Path, cwd: Path):
        captured_args.extend(args)
        return CompletedProcess(args=["bd", *args], returncode=0, stdout="at-epic-9\n", stderr="")

    with (
        patch.object(module.beads, "run_bd_command", side_effect=_fake_run_bd_command),
        patch.object(module.beads, "run_bd_json", return_value=[{"id": "at-epic-9"}]),
    ):
        created = module._create_reroute_epic(
            subject="Investigate stale task",
            body="Original payload",
            sender="atelier/planner/codex/p11",
            recipient="atelier/worker/codex/p22",
            thread="at-thread",
            reply_to="at-msg-2",
            beads_root=Path("/beads"),
            cwd=Path("/repo"),
        )

    assert created["id"] == "at-epic-9"
    assert "--label" in captured_args
    assert "at:epic" in captured_args
    assert "--status" not in captured_args
    description = captured_args[captured_args.index("--description") + 1]
    assert "routing.decision: rerouted_inactive_worker" in description
    assert "routing.inactive_worker: atelier/worker/codex/p22" in description
    assert "routing.thread: at-thread" in description
    assert "routing.reply_to: at-msg-2" in description


def test_dispatch_message_non_planner_sender_does_not_reroute() -> None:
    module = _load_script_module()
    with (
        patch.object(module.agent_home, "is_session_agent_active", return_value=False),
        patch.object(
            module.beads, "create_message_bead", return_value={"id": "at-msg-2"}
        ) as create,
        patch.object(module, "_create_reroute_epic") as reroute,
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
    reroute.assert_not_called()

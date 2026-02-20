from pathlib import Path
from unittest.mock import patch

from atelier.worker import queueing


def test_send_planner_notification_dry_run_logs_and_skips_beads() -> None:
    logs: list[str] = []

    with patch("atelier.worker.queueing.beads.create_message_bead") as create_message:
        queueing.send_planner_notification(
            subject="hello",
            body="world",
            agent_id="worker/1",
            thread_id="at-1",
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            dry_run=True,
            dry_run_log=logs.append,
        )

    assert create_message.call_count == 0
    assert logs == ["Would send message: hello", "world"]


def test_send_no_ready_changesets_uses_summary_counts() -> None:
    class _Summary:
        total = 4
        ready = 0
        remaining = 4

    with (
        patch(
            "atelier.worker.queueing.beads.epic_changeset_summary",
            return_value=_Summary(),
        ),
        patch("atelier.worker.queueing.beads.create_message_bead") as create_message,
    ):
        queueing.send_no_ready_changesets(
            epic_id="at-1",
            agent_id="worker/1",
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            dry_run=False,
            dry_run_log=lambda _value: None,
        )

    assert create_message.call_count == 1
    kwargs = create_message.call_args.kwargs
    assert kwargs["subject"] == "NEEDS-DECISION: No ready changesets for at-1"
    assert "Ready changesets: 0" in kwargs["body"]


def test_prompt_queue_claim_assume_yes_claims_first_message() -> None:
    emitted: list[str] = []
    queued = [{"id": "at-msg-1", "queue": "planner", "title": "Needs review"}]

    with patch("atelier.worker.queueing.beads.claim_queue_message") as claim_message:
        claimed = queueing.prompt_queue_claim(
            queued,
            agent_id="worker/1",
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            assume_yes=True,
            emit=emitted.append,
            prompt_fn=lambda _text: "",
            die_fn=lambda message: (_ for _ in ()).throw(RuntimeError(message)),
        )

    assert claimed is True
    assert claim_message.call_count == 1
    assert "Claimed queue message: at-msg-1" in emitted


def test_handle_queue_before_claim_dry_run_reports_messages() -> None:
    queued = [{"id": "at-msg-1", "queue": "planner", "title": "Needs review"}]
    emitted: list[str] = []
    dry_logs: list[str] = []

    with patch(
        "atelier.worker.queueing.beads.list_queue_messages", return_value=queued
    ):
        handled = queueing.handle_queue_before_claim(
            "worker/1",
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            queue_name="worker",
            force_prompt=False,
            dry_run=True,
            assume_yes=False,
            emit=emitted.append,
            prompt_fn=lambda _text: "",
            die_fn=lambda message: (_ for _ in ()).throw(RuntimeError(message)),
            dry_run_log=dry_logs.append,
        )

    assert handled is True
    assert emitted[0] == "Queued messages:"
    assert dry_logs == ["Would prompt to claim a queue message."]


def test_check_inbox_before_claim_reports_unread() -> None:
    emitted: list[str] = []
    with patch(
        "atelier.worker.queueing.beads.list_inbox_messages",
        return_value=[{"id": "at-msg-1"}],
    ):
        blocked = queueing.check_inbox_before_claim(
            "worker/1",
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            emit=emitted.append,
        )

    assert blocked is True
    assert emitted == ["Inbox has 1 unread message(s); review before claiming work."]

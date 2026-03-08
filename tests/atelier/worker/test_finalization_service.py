from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from atelier import messages
from atelier.worker import finalization_service


def test_has_blocking_messages_ignores_planner_only_thread_notifications(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = dt.datetime.now(dt.timezone.utc)

    issues = [
        {
            "id": "at-msg-1",
            "title": "NEEDS-DECISION: Publish incomplete (at-epic.1)",
            "created_at": now.isoformat(),
            "description": messages.render_message(
                {
                    "from": "atelier/worker/codex/p100",
                    "queue": "planner",
                    "thread": "at-epic.1",
                    "msg_type": "notification",
                },
                "Planner decision required before publish continues.",
            ),
        }
    ]

    monkeypatch.setattr(
        finalization_service.beads,
        "run_bd_json",
        lambda *_args, **_kwargs: issues,
    )

    blocked = finalization_service.has_blocking_messages(
        thread_ids={"at-epic.1"},
        started_at=now - dt.timedelta(minutes=1),
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
        parse_issue_time=lambda value: dt.datetime.fromisoformat(str(value)),
    )

    assert blocked is False


def test_has_blocking_messages_honors_worker_thread_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = dt.datetime.now(dt.timezone.utc)

    issues = [
        {
            "id": "at-msg-2",
            "title": "Worker handoff",
            "assignee": "atelier/worker/codex/p100",
            "created_at": now.isoformat(),
            "description": messages.render_message(
                {
                    "from": "atelier/planner/codex/p200",
                    "thread": "at-epic.1",
                },
                "Resume the queued review-feedback work before finalize.",
            ),
        }
    ]

    monkeypatch.setattr(
        finalization_service.beads,
        "run_bd_json",
        lambda *_args, **_kwargs: issues,
    )

    blocked = finalization_service.has_blocking_messages(
        thread_ids={"at-epic.1"},
        started_at=now - dt.timedelta(minutes=1),
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
        parse_issue_time=lambda value: dt.datetime.fromisoformat(str(value)),
    )

    assert blocked is True

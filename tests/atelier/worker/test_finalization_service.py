from __future__ import annotations

import datetime as dt
from pathlib import Path
from unittest.mock import patch

from atelier.worker import finalization_service


def test_has_blocking_messages_keeps_thread_compatibility_with_new_contract() -> None:
    started_at = dt.datetime(2026, 3, 8, tzinfo=dt.timezone.utc)
    issues = [
        {
            "id": "at-msg-1",
            "created_at": "2026-03-08T00:00:00+00:00",
            "description": (
                "---\n"
                "from: atelier/planner/codex/p1\n"
                "delivery: work-threaded\n"
                "thread: at-ue6aj.1\n"
                "thread_kind: changeset\n"
                "audience: [worker]\n"
                "kind: instruction\n"
                "blocking: true\n"
                "---\n\n"
                "Finish the pending step.\n"
            ),
        }
    ]

    with patch("atelier.worker.finalization_service.beads.run_bd_json", return_value=issues):
        blocking = finalization_service.has_blocking_messages(
            thread_ids={"at-ue6aj.1"},
            started_at=started_at,
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            parse_issue_time=dt.datetime.fromisoformat,
        )

    assert blocking is True

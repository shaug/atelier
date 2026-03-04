"""Tests for worker runtime telemetry output."""

from __future__ import annotations

from atelier.worker.models import WorkerRunSummary
from atelier.worker.telemetry import report_worker_summary


def test_report_worker_summary_started_session() -> None:
    lines: list[str] = []
    debug_lines: list[str] = []

    report_worker_summary(
        WorkerRunSummary(started=True, reason="agent_session_complete"),
        dry_run=False,
        say=lines.append,
        log_debug=debug_lines.append,
    )

    assert lines == [
        "Summary: started worker session",
        "- Reason: agent_session_complete",
    ]
    assert debug_lines == [
        "summary continuation_started=True agent_session_started=True "
        "reason=agent_session_complete epic=none changeset=none dry_run=False"
    ]


def test_report_worker_summary_startup_finalize_only_does_not_report_agent_started() -> None:
    lines: list[str] = []
    debug_lines: list[str] = []

    report_worker_summary(
        WorkerRunSummary(
            started=True,
            reason="startup_finalize_only",
            epic_id="at-epic",
            changeset_id="at-epic.1",
        ),
        dry_run=False,
        say=lines.append,
        log_debug=debug_lines.append,
    )

    assert lines == [
        "Summary: continued without agent session (startup finalize-only)",
        "- Reason: startup_finalize_only",
        "- Epic: at-epic",
        "- Changeset: at-epic.1",
    ]
    assert debug_lines == [
        "summary continuation_started=True agent_session_started=False "
        "reason=startup_finalize_only epic=at-epic "
        "changeset=at-epic.1 dry_run=False"
    ]

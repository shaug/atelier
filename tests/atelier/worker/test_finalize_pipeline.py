from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

from atelier.worker import finalize_pipeline


def _pipeline_kwargs(**overrides: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "changeset_id": "at-epic.1",
        "epic_id": "at-epic",
        "agent_id": "atelier/worker/codex/p100",
        "agent_bead_id": "at-agent",
        "started_at": dt.datetime.now(dt.timezone.utc),
        "repo_slug": None,
        "beads_root": Path("/beads"),
        "repo_root": Path("/repo"),
        "branch_pr": True,
        "branch_pr_strategy": "on-ready",
        "branch_history": "manual",
        "branch_squash_message": "deterministic",
        "project_data_dir": Path("/project"),
        "squash_message_agent_spec": None,
        "squash_message_agent_options": None,
        "squash_message_agent_home": None,
        "squash_message_agent_env": None,
        "git_path": "git",
        "issue_labels": lambda issue: set(issue.get("labels") or []),
        "find_invalid_changeset_labels": lambda *_args, **_kwargs: [],
        "send_invalid_changeset_labels_notification": lambda **_kwargs: "",
        "has_open_descendant_changesets": lambda *_args, **_kwargs: False,
        "has_blocking_messages": lambda **_kwargs: False,
        "mark_changeset_children_in_progress": lambda *_args, **_kwargs: None,
        "close_completed_container_changesets": lambda *_args, **_kwargs: [],
        "promote_planned_descendant_changesets": lambda *_args, **_kwargs: None,
        "changeset_integration_signal": lambda *_args, **_kwargs: (False, None),
        "recover_premature_merged_changeset": lambda **_kwargs: None,
        "mark_changeset_blocked": lambda *_args, **_kwargs: None,
        "send_planner_notification": lambda **_kwargs: None,
        "mark_changeset_closed": lambda *_args, **_kwargs: None,
        "finalize_epic_if_complete": lambda **_kwargs: None,
        "mark_changeset_in_progress": lambda *_args, **_kwargs: None,
        "changeset_waiting_on_review_or_signals": lambda *_args, **_kwargs: False,
        "lookup_pr_payload": lambda *_args, **_kwargs: None,
        "lookup_pr_payload_diagnostic": lambda *_args, **_kwargs: (None, None),
        "log_warning": lambda _message: None,
        "log_debug": lambda _message: None,
        "update_changeset_review_from_pr": lambda *_args, **_kwargs: None,
        "finalize_terminal_changeset": lambda **_kwargs: None,
        "handle_pushed_without_pr": lambda **_kwargs: None,
        "attempt_push_work_branch": lambda *_args, **_kwargs: (False, None),
        "collect_publish_signal_diagnostics": lambda **_kwargs: type(
            "Diag", (), {"has_recoverable_local_state": False}
        )(),
        "format_publish_diagnostics": lambda *_args, **_kwargs: "diag",
        "set_changeset_review_pending_state": lambda **_kwargs: None,
    }
    kwargs.update(overrides)
    return kwargs


def test_run_finalize_pipeline_missing_changeset_id() -> None:
    result = finalize_pipeline.run_finalize_pipeline(
        **_pipeline_kwargs(changeset_id="")
    )

    assert result.reason == "changeset_missing"
    assert result.continue_running is False


def test_run_finalize_pipeline_blocks_on_invalid_labels(monkeypatch) -> None:
    monkeypatch.setattr(
        finalize_pipeline.beads,
        "run_bd_json",
        lambda *_args, **_kwargs: [{"id": "at-epic.1", "labels": ["at:changeset"]}],
    )
    notified: list[dict[str, Any]] = []

    result = finalize_pipeline.run_finalize_pipeline(
        **_pipeline_kwargs(
            find_invalid_changeset_labels=lambda *_args, **_kwargs: ["at-epic.2"],
            send_invalid_changeset_labels_notification=lambda **kwargs: (
                notified.append(kwargs) or "sent"
            ),
        )
    )

    assert result.reason == "changeset_label_violation"
    assert result.continue_running is False
    assert len(notified) == 1


def test_run_finalize_pipeline_waiting_on_review_returns_pending(monkeypatch) -> None:
    issue = {
        "id": "at-epic.1",
        "labels": ["at:changeset", "cs:in_progress"],
        "description": "changeset.work_branch: feat/root-at-epic.1\n",
    }
    monkeypatch.setattr(
        finalize_pipeline.beads,
        "run_bd_json",
        lambda *_args, **_kwargs: [issue],
    )

    result = finalize_pipeline.run_finalize_pipeline(
        **_pipeline_kwargs(
            changeset_waiting_on_review_or_signals=lambda *_args, **_kwargs: True
        )
    )

    assert result.reason == "changeset_review_pending"
    assert result.continue_running is True

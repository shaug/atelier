from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

from atelier.worker.review import ReviewFeedbackSelection
from atelier.worker.session import startup


def _startup_kwargs(**overrides: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "agent_id": "atelier/worker/codex/p100",
        "agent_bead_id": "at-agent",
        "beads_root": Path("/beads"),
        "repo_root": Path("/repo"),
        "mode": "auto",
        "explicit_epic_id": None,
        "queue_only": False,
        "dry_run": False,
        "assume_yes": False,
        "repo_slug": None,
        "branch_pr": False,
        "branch_pr_strategy": "on-ready",
        "git_path": "git",
        "worker_queue_name": "worker",
        "handle_queue_before_claim": lambda *_args, **_kwargs: False,
        "list_epics": lambda **_kwargs: [],
        "next_changeset_fn": lambda **_kwargs: None,
        "resolve_hooked_epic": lambda *_args, **_kwargs: None,
        "filter_epics": lambda issues, assignee: [
            issue for issue in issues if issue.get("assignee") == assignee
        ],
        "sort_by_created_at": lambda issues: issues,
        "stale_family_assigned_epics": lambda issues, agent_id: [],
        "select_review_feedback_changeset": lambda **_kwargs: None,
        "parse_issue_time": lambda _value: None,
        "select_global_review_feedback_changeset": lambda **_kwargs: None,
        "is_feedback_eligible_epic_status": lambda _status: True,
        "issue_labels": lambda issue: set(issue.get("labels") or []),
        "check_inbox_before_claim": lambda *_args, **_kwargs: False,
        "select_epic_auto": lambda issues, agent_id, is_actionable: None,
        "select_epic_prompt": lambda issues, agent_id, is_actionable, assume_yes: None,
        "select_epic_from_ready_changesets": lambda **_kwargs: None,
        "send_needs_decision": lambda **_kwargs: None,
        "log_debug": lambda _message: None,
        "log_warning": lambda _message: None,
        "dry_run_log": lambda _message: None,
        "emit": lambda _message: None,
        "run_bd_json": lambda *_args, **_kwargs: [],
        "agent_family_id": lambda value: str(value).split("/p", 1)[0],
        "is_agent_session_active": lambda _agent_id: False,
        "die_fn": lambda message: (_ for _ in ()).throw(RuntimeError(message)),
    }
    kwargs.update(overrides)
    return kwargs


def test_run_startup_contract_supports_explicit_epic() -> None:
    result = startup.run_startup_contract(
        **_startup_kwargs(explicit_epic_id="at-explicit")
    )

    assert result.epic_id == "at-explicit"
    assert result.should_exit is False
    assert result.reason == "explicit_epic"


def test_run_startup_contract_queue_only_exits_after_queue() -> None:
    queue_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def handle_queue(*args: Any, **kwargs: Any) -> bool:
        queue_calls.append((args, kwargs))
        return False

    result = startup.run_startup_contract(
        **_startup_kwargs(queue_only=True, handle_queue_before_claim=handle_queue)
    )

    assert result.should_exit is True
    assert result.reason == "queue_only"
    assert len(queue_calls) == 1
    assert queue_calls[0][1]["force_prompt"] is True


def test_run_startup_contract_prioritizes_review_feedback() -> None:
    feedback = ReviewFeedbackSelection(
        epic_id="at-epic",
        changeset_id="at-epic.1",
        feedback_at="2026-02-20T00:00:00Z",
    )
    next_changeset_calls = 0

    def next_changeset(**_kwargs: Any) -> dict[str, object] | None:
        nonlocal next_changeset_calls
        next_changeset_calls += 1
        return {"id": "at-epic.2"}

    result = startup.run_startup_contract(
        **_startup_kwargs(
            branch_pr=True,
            repo_slug="org/repo",
            resolve_hooked_epic=lambda *_args, **_kwargs: "at-epic",
            select_review_feedback_changeset=lambda **_kwargs: feedback,
            next_changeset_fn=next_changeset,
            run_bd_json=lambda *_args, **_kwargs: [
                {"id": "at-epic", "assignee": "atelier/worker/codex/p010"}
            ],
        )
    )

    assert result.reason == "review_feedback"
    assert result.epic_id == "at-epic"
    assert result.changeset_id == "at-epic.1"
    assert next_changeset_calls == 0


def test_run_startup_contract_reclaims_stale_family_assignment() -> None:
    issues = [{"id": "at-epic", "assignee": "atelier/worker/codex/p099"}]

    result = startup.run_startup_contract(
        **_startup_kwargs(
            agent_bead_id=None,
            list_epics=lambda **_kwargs: issues,
            stale_family_assigned_epics=lambda _issues, agent_id: issues,
            next_changeset_fn=lambda **_kwargs: {"id": "at-epic.1"},
        )
    )

    assert result.reason == "stale_assignee_epic"
    assert result.epic_id == "at-epic"
    assert result.reassign_from == "atelier/worker/codex/p099"


def test_run_startup_contract_uses_ready_changeset_fallback() -> None:
    issues = [{"id": "at-other"}]

    result = startup.run_startup_contract(
        **_startup_kwargs(
            list_epics=lambda **_kwargs: issues,
            mode="prompt",
            select_epic_prompt=lambda *_args, **_kwargs: None,
            select_epic_from_ready_changesets=lambda **_kwargs: "at-ready",
        )
    )

    assert result.reason == "selected_ready_changeset"
    assert result.epic_id == "at-ready"


def test_run_startup_contract_selects_auto_epic() -> None:
    issues = [{"id": "at-auto"}]

    result = startup.run_startup_contract(
        **_startup_kwargs(
            list_epics=lambda **_kwargs: issues,
            select_epic_auto=lambda _issues, agent_id, is_actionable: "at-auto",
        )
    )

    assert result.reason == "selected_auto"
    assert result.epic_id == "at-auto"


def test_run_startup_contract_sends_needs_decision_when_no_eligible_epics() -> None:
    sent: list[dict[str, Any]] = []

    result = startup.run_startup_contract(
        **_startup_kwargs(
            send_needs_decision=lambda **kwargs: sent.append(kwargs),
            parse_issue_time=lambda value: dt.datetime.now(dt.timezone.utc),
        )
    )

    assert result.should_exit is True
    assert result.reason == "no_eligible_epics"
    assert len(sent) == 1

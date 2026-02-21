from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from atelier.worker.finalization import pr_gate


def test_changeset_pr_creation_decision_on_ready_blocks_when_parent_only_pushed(
    monkeypatch,
) -> None:
    issue = {
        "description": (
            "changeset.parent_branch: feature-parent\n"
            "changeset.root_branch: feature-root\n"
        )
    }
    monkeypatch.setattr(pr_gate.git, "git_ref_exists", lambda *_args, **_kwargs: True)

    decision = pr_gate.changeset_pr_creation_decision(
        issue,
        repo_slug="org/repo",
        repo_root=Path("/repo"),
        git_path="git",
        branch_pr_strategy="on-ready",
        lookup_pr_payload=lambda *_args, **_kwargs: None,
    )

    assert decision.allow_pr is False
    assert decision.reason == "blocked:pushed"


def test_handle_pushed_without_pr_returns_review_pending_when_strategy_blocks(
    monkeypatch,
) -> None:
    issue = {
        "description": (
            "changeset.parent_branch: feature-parent\n"
            "changeset.root_branch: feature-root\n"
        )
    }
    marked: list[str] = []
    monkeypatch.setattr(pr_gate.git, "git_ref_exists", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        pr_gate.beads, "update_changeset_review", lambda *_args, **_kwargs: None
    )

    result = pr_gate.handle_pushed_without_pr(
        issue=issue,
        changeset_id="at-123.1",
        agent_id="atelier/worker/codex/p1",
        repo_slug="org/repo",
        repo_root=Path("/repo"),
        beads_root=Path("/beads"),
        branch_pr_strategy="on-ready",
        git_path="git",
        changeset_base_branch=lambda *_args, **_kwargs: "main",
        changeset_work_branch=lambda _issue: "feature-work",
        render_changeset_pr_body=lambda _issue: "summary",
        lookup_pr_payload=lambda *_args, **_kwargs: None,
        lookup_pr_payload_diagnostic=lambda *_args, **_kwargs: (None, None),
        mark_changeset_in_progress=lambda *_args, **_kwargs: marked.append(
            "in_progress"
        ),
        send_planner_notification=lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("planner notification should not be sent")
        ),
        update_changeset_review_from_pr=lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("no PR payload should be applied")
        ),
        emit=lambda _message: None,
        log_warning=lambda _message: None,
    )

    assert marked == ["in_progress"]
    assert result.finalize_result.continue_running is True
    assert result.finalize_result.reason == "changeset_review_pending"


def test_handle_pushed_without_pr_reports_failure_when_pr_create_fails(
    monkeypatch,
) -> None:
    issue = {
        "description": (
            "changeset.parent_branch: feature-parent\n"
            "changeset.root_branch: feature-root\n"
        ),
        "title": "Example",
    }
    planner_messages: list[str] = []
    notes: list[list[str]] = []

    monkeypatch.setattr(pr_gate.git, "git_ref_exists", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        pr_gate.exec,
        "try_run_command",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=1, stdout="", stderr="boom"
        ),
    )
    monkeypatch.setattr(
        pr_gate.beads,
        "run_bd_command",
        lambda args, **_kwargs: notes.append(args),
    )

    result = pr_gate.handle_pushed_without_pr(
        issue=issue,
        changeset_id="at-123.1",
        agent_id="atelier/worker/codex/p1",
        repo_slug="org/repo",
        repo_root=Path("/repo"),
        beads_root=Path("/beads"),
        branch_pr_strategy="parallel",
        git_path="git",
        changeset_base_branch=lambda *_args, **_kwargs: "main",
        changeset_work_branch=lambda _issue: "feature-work",
        render_changeset_pr_body=lambda _issue: "summary",
        lookup_pr_payload=lambda *_args, **_kwargs: None,
        lookup_pr_payload_diagnostic=lambda *_args, **_kwargs: (None, None),
        mark_changeset_in_progress=lambda *_args, **_kwargs: None,
        send_planner_notification=lambda **kwargs: planner_messages.append(
            str(kwargs.get("subject"))
        ),
        update_changeset_review_from_pr=lambda **_kwargs: None,
        emit=lambda _message: None,
        log_warning=lambda _message: None,
    )

    assert result.finalize_result.continue_running is False
    assert result.finalize_result.reason == "changeset_pr_create_failed"
    assert notes and "update" in notes[0]
    assert (
        planner_messages and "NEEDS-DECISION: PR creation failed" in planner_messages[0]
    )

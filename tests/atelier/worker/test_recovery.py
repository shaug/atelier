from __future__ import annotations

from pathlib import Path

from atelier.worker.finalization import recovery
from atelier.worker.models import FinalizeResult


def test_recovery_moves_back_to_review_pending_when_pr_is_open(monkeypatch) -> None:
    issue = {"description": "changeset.work_branch: feature-branch\n"}
    mark_calls: list[str] = []
    update_calls: list[str] = []

    monkeypatch.setattr(recovery.git, "git_ref_exists", lambda *_args, **_kwargs: True)

    result = recovery.recover_premature_merged_changeset(
        issue=issue,
        changeset_id="at-epic.1",
        epic_id="at-epic",
        agent_id="atelier/worker/codex/p1",
        agent_bead_id="at-agent",
        branch_pr=True,
        branch_history="rebase",
        branch_squash_message="deterministic",
        branch_pr_strategy="parallel",
        repo_slug="org/repo",
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
        project_data_dir=Path("/project"),
        squash_message_agent_spec=None,
        squash_message_agent_options=[],
        squash_message_agent_home=None,
        squash_message_agent_env=None,
        git_path="git",
        changeset_work_branch=lambda _issue: "feature-branch",
        lookup_pr_payload=lambda *_args, **_kwargs: {
            "state": "OPEN",
            "isDraft": False,
            "reviewDecision": None,
        },
        lookup_pr_payload_diagnostic=lambda *_args, **_kwargs: (None, None),
        changeset_integration_signal=lambda *_args, **_kwargs: (False, None),
        finalize_terminal_changeset=lambda **_kwargs: FinalizeResult(
            continue_running=False, reason="terminal"
        ),
        mark_changeset_in_progress=lambda *_args, **_kwargs: mark_calls.append(
            "in_progress"
        ),
        update_changeset_review_from_pr=lambda *_args, **_kwargs: update_calls.append(
            "updated"
        ),
        handle_pushed_without_pr=lambda **_kwargs: FinalizeResult(
            continue_running=False, reason="pushed_without_pr"
        ),
        log_warning=lambda _message: None,
    )

    assert result == FinalizeResult(
        continue_running=True, reason="changeset_review_pending"
    )
    assert mark_calls == ["in_progress"]
    assert update_calls == ["updated"]


def test_recovery_routes_pushed_without_pr_back_to_pr_gate(monkeypatch) -> None:
    issue = {"description": "changeset.work_branch: feature-branch\n"}

    monkeypatch.setattr(recovery.git, "git_ref_exists", lambda *_args, **_kwargs: True)

    result = recovery.recover_premature_merged_changeset(
        issue=issue,
        changeset_id="at-epic.1",
        epic_id="at-epic",
        agent_id="atelier/worker/codex/p1",
        agent_bead_id="at-agent",
        branch_pr=True,
        branch_history="rebase",
        branch_squash_message="deterministic",
        branch_pr_strategy="parallel",
        repo_slug="org/repo",
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
        project_data_dir=Path("/project"),
        squash_message_agent_spec=None,
        squash_message_agent_options=[],
        squash_message_agent_home=None,
        squash_message_agent_env=None,
        git_path="git",
        changeset_work_branch=lambda _issue: "feature-branch",
        lookup_pr_payload=lambda *_args, **_kwargs: None,
        lookup_pr_payload_diagnostic=lambda *_args, **_kwargs: (None, None),
        changeset_integration_signal=lambda *_args, **_kwargs: (False, None),
        finalize_terminal_changeset=lambda **_kwargs: FinalizeResult(
            continue_running=False, reason="terminal"
        ),
        mark_changeset_in_progress=lambda *_args, **_kwargs: None,
        update_changeset_review_from_pr=lambda *_args, **_kwargs: None,
        handle_pushed_without_pr=lambda **_kwargs: FinalizeResult(
            continue_running=False, reason="changeset_pr_create_failed"
        ),
        log_warning=lambda _message: None,
    )

    assert result == FinalizeResult(
        continue_running=False, reason="changeset_pr_create_failed"
    )

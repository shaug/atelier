from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from atelier.worker.finalization import pr_gate


def test_changeset_pr_creation_decision_on_ready_blocks_when_parent_only_pushed(
    monkeypatch,
) -> None:
    issue = {
        "description": (
            "changeset.parent_branch: feature-parent\nchangeset.root_branch: feature-root\n"
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
            "changeset.parent_branch: feature-parent\nchangeset.root_branch: feature-root\n"
        )
    }
    marked: list[str] = []
    monkeypatch.setattr(pr_gate.git, "git_ref_exists", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(pr_gate.beads, "update_changeset_review", lambda *_args, **_kwargs: None)

    result = pr_gate.handle_pushed_without_pr(
        issue=issue,
        changeset_id="at-123.1",
        agent_id="atelier/worker/codex/p1",
        repo_slug="org/repo",
        repo_root=Path("/repo"),
        beads_root=Path("/beads"),
        branch_pr_strategy="on-ready",
        git_path="git",
        create_as_draft=True,
        changeset_base_branch=lambda *_args, **_kwargs: "main",
        changeset_work_branch=lambda _issue: "feature-work",
        render_changeset_pr_body=lambda _issue: "summary",
        lookup_pr_payload=lambda *_args, **_kwargs: None,
        lookup_pr_payload_diagnostic=lambda *_args, **_kwargs: (None, None),
        mark_changeset_in_progress=lambda *_args, **_kwargs: marked.append("in_progress"),
        send_planner_notification=lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("planner notification should not be sent")
        ),
        update_changeset_review_from_pr=lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("no PR payload should be applied")
        ),
        emit=lambda _message: None,
    )

    assert marked == ["in_progress"]
    assert result.finalize_result.continue_running is True
    assert result.finalize_result.reason == "changeset_review_pending"


def test_handle_pushed_without_pr_reports_failure_when_pr_create_fails(
    monkeypatch,
) -> None:
    issue = {
        "description": (
            "changeset.parent_branch: feature-parent\nchangeset.root_branch: feature-root\n"
        ),
        "title": "Example",
    }
    planner_messages: list[str] = []
    notes: list[list[str]] = []

    monkeypatch.setattr(pr_gate.git, "git_ref_exists", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        pr_gate.exec,
        "try_run_command",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=1, stdout="", stderr="boom"),
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
        create_as_draft=True,
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
    )

    assert result.finalize_result.continue_running is False
    assert result.finalize_result.reason == "changeset_pr_create_failed"
    assert notes and "update" in notes[0]
    assert planner_messages and "NEEDS-DECISION: PR creation failed" in planner_messages[0]


def test_changeset_pr_creation_decision_resolves_collapsed_dependency_parent(monkeypatch) -> None:
    issue = {
        "description": (
            "changeset.parent_branch: feature-root\nchangeset.root_branch: feature-root\n"
        ),
        "dependencies": ["at-epic.1"],
    }

    def _show_issue(args: list[str], **_kwargs) -> list[dict[str, object]]:
        if args == ["show", "at-epic.1"]:
            return [{"description": "changeset.work_branch: feature-parent\n"}]
        return []

    monkeypatch.setattr(pr_gate.beads, "run_bd_json", _show_issue)
    monkeypatch.setattr(pr_gate.git, "git_ref_exists", lambda *_args, **_kwargs: True)

    decision = pr_gate.changeset_pr_creation_decision(
        issue,
        repo_slug="org/repo",
        repo_root=Path("/repo"),
        git_path="git",
        branch_pr_strategy="sequential",
        beads_root=Path("/beads"),
        lookup_pr_payload=lambda *_args, **_kwargs: {"state": "OPEN", "isDraft": False},
    )

    assert decision.allow_pr is False
    assert decision.reason == "blocked:pr-open"


def test_changeset_pr_creation_decision_blocks_on_ambiguous_dependency_lineage(
    monkeypatch,
) -> None:
    issue = {
        "description": (
            "changeset.parent_branch: feature-root\nchangeset.root_branch: feature-root\n"
        ),
        "dependencies": ["at-epic.1", "at-epic.2"],
    }

    def _show_issue(args: list[str], **_kwargs) -> list[dict[str, object]]:
        if args == ["show", "at-epic.1"]:
            return [{"description": "changeset.work_branch: feature-parent-1\n"}]
        if args == ["show", "at-epic.2"]:
            return [{"description": "changeset.work_branch: feature-parent-2\n"}]
        return []

    monkeypatch.setattr(pr_gate.beads, "run_bd_json", _show_issue)

    decision = pr_gate.changeset_pr_creation_decision(
        issue,
        repo_slug="org/repo",
        repo_root=Path("/repo"),
        git_path="git",
        branch_pr_strategy="sequential",
        beads_root=Path("/beads"),
        lookup_pr_payload=lambda *_args, **_kwargs: None,
    )

    assert decision.allow_pr is False
    assert decision.reason.startswith("blocked:dependency-lineage-ambiguous")


def test_attempt_create_pr_uses_body_file_for_markdown(monkeypatch) -> None:
    commands: list[list[str]] = []
    observed: dict[str, object] = {}

    def fake_try_run_command(cmd: list[str], **_kwargs) -> SimpleNamespace:
        commands.append(list(cmd))
        body_path = Path(cmd[cmd.index("--body-file") + 1])
        observed["body_path"] = body_path
        observed["body_exists_during_call"] = body_path.exists()
        observed["body"] = body_path.read_text(encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="created", stderr="")

    monkeypatch.setattr(pr_gate.exec, "try_run_command", fake_try_run_command)

    created, detail = pr_gate.attempt_create_pr(
        repo_slug="org/repo",
        issue={"title": "Title with `ticks` and $(echo safe)"},
        work_branch="feature/work",
        is_draft=False,
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
        git_path="git",
        changeset_base_branch=lambda *_args, **_kwargs: "main",
        render_changeset_pr_body=lambda _issue: "Body with `code`\n$(echo safe)",
    )

    assert created is True
    assert detail == "created"
    assert commands
    command = commands[0]
    assert "--body-file" in command
    assert "--body" not in command
    assert "--draft" not in command
    assert "Title with `ticks` and $(echo safe)" in command
    assert observed["body_exists_during_call"] is True
    assert observed["body"] == "Body with `code`\n$(echo safe)"
    body_path = observed["body_path"]
    assert isinstance(body_path, Path)
    assert not body_path.exists()


def test_handle_pushed_without_pr_ready_mode_sets_pr_open_fallback(monkeypatch) -> None:
    issue = {
        "description": (
            "changeset.parent_branch: feature-parent\nchangeset.root_branch: feature-root\n"
        ),
        "title": "Example",
    }
    observed_states: list[str] = []
    monkeypatch.setattr(pr_gate.git, "git_ref_exists", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        pr_gate.beads,
        "update_changeset_review",
        lambda _changeset_id, metadata, **_kwargs: observed_states.append(
            str(metadata.pr_state or "")
        ),
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
        create_as_draft=False,
        changeset_base_branch=lambda *_args, **_kwargs: "main",
        changeset_work_branch=lambda _issue: "feature-work",
        render_changeset_pr_body=lambda _issue: "summary",
        lookup_pr_payload=lambda *_args, **_kwargs: None,
        lookup_pr_payload_diagnostic=lambda *_args, **_kwargs: (None, None),
        mark_changeset_in_progress=lambda *_args, **_kwargs: None,
        send_planner_notification=lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("planner notification should not be sent")
        ),
        update_changeset_review_from_pr=lambda **_kwargs: None,
        emit=lambda _message: None,
        attempt_create_pr_fn=lambda **_kwargs: (True, "created"),
    )

    assert result.finalize_result.continue_running is True
    assert result.finalize_result.reason == "changeset_review_pending"
    assert observed_states == ["pr-open"]

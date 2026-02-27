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


def test_handle_pushed_without_pr_keeps_deeper_dependency_gated(monkeypatch) -> None:
    issue = {
        "description": (
            "changeset.parent_branch: feature-root\n"
            "changeset.root_branch: feature-root\n"
            "changeset.work_branch: feature-kid-3\n"
        ),
        "dependencies": ["at-kid.2"],
    }
    marked: list[str] = []
    observed_states: list[str] = []

    monkeypatch.setattr(
        pr_gate.beads,
        "run_bd_json",
        lambda args, **_kwargs: (
            [{"description": "changeset.work_branch: feature-kid-2\n"}]
            if args == ["show", "at-kid.2"]
            else []
        ),
    )
    monkeypatch.setattr(pr_gate.git, "git_ref_exists", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        pr_gate.beads,
        "update_changeset_review",
        lambda _changeset_id, metadata, **_kwargs: observed_states.append(
            str(metadata.pr_state or "")
        ),
    )

    result = pr_gate.handle_pushed_without_pr(
        issue=issue,
        changeset_id="at-kid.3",
        agent_id="atelier/worker/codex/p1",
        repo_slug="org/repo",
        repo_root=Path("/repo"),
        beads_root=Path("/beads"),
        branch_pr_strategy="sequential",
        git_path="git",
        create_as_draft=True,
        changeset_base_branch=lambda *_args, **_kwargs: "main",
        changeset_work_branch=lambda _issue: "feature-kid-3",
        render_changeset_pr_body=lambda _issue: "summary",
        lookup_pr_payload=lambda _repo_slug, branch: (
            {"state": "OPEN", "isDraft": False} if branch == "feature-kid-2" else None
        ),
        lookup_pr_payload_diagnostic=lambda *_args, **_kwargs: (None, None),
        mark_changeset_in_progress=lambda *_args, **_kwargs: marked.append("in_progress"),
        send_planner_notification=lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("planner notification should not be sent")
        ),
        update_changeset_review_from_pr=lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("no PR payload should be applied")
        ),
        emit=lambda _message: None,
        attempt_create_pr_fn=lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("PR creation should stay gated for downstream changesets")
        ),
    )

    assert result.finalize_result.continue_running is True
    assert result.finalize_result.reason == "changeset_review_pending"
    assert result.detail == "blocked:pr-open"
    assert marked == ["in_progress"]
    assert observed_states == ["pushed"]


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


def test_changeset_pr_creation_decision_collapses_transitive_duplicate_dependencies(
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
            return [{"id": "at-epic.1", "description": "changeset.work_branch: feature-parent-1\n"}]
        if args == ["show", "at-epic.2"]:
            return [
                {
                    "id": "at-epic.2",
                    "description": "changeset.work_branch: feature-parent-2\n",
                    "dependencies": ["at-epic.1"],
                }
            ]
        return []

    monkeypatch.setattr(pr_gate.beads, "run_bd_json", _show_issue)
    monkeypatch.setattr(pr_gate.git, "git_ref_exists", lambda *_args, **_kwargs: True)

    def _lookup(_repo_slug: str, branch: str) -> dict[str, object] | None:
        if branch == "feature-parent-2":
            return {"state": "OPEN", "isDraft": False}
        if branch == "feature-parent-1":
            return {"state": "CLOSED", "closedAt": "2026-02-25T00:00:00Z"}
        return None

    decision = pr_gate.changeset_pr_creation_decision(
        issue,
        repo_slug="org/repo",
        repo_root=Path("/repo"),
        git_path="git",
        branch_pr_strategy="sequential",
        beads_root=Path("/beads"),
        lookup_pr_payload=_lookup,
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


def test_changeset_pr_creation_decision_blocks_dependency_lineage_when_parent_state_missing(
    monkeypatch,
) -> None:
    issue = {
        "description": (
            "changeset.parent_branch: legacy-parent\nchangeset.root_branch: feature-root\n"
        ),
        "dependencies": ["at-epic.1"],
    }

    monkeypatch.setattr(
        pr_gate.beads,
        "run_bd_json",
        lambda args, **_kwargs: (
            [{"description": "changeset.work_branch: active-parent\n"}]
            if args == ["show", "at-epic.1"]
            else []
        ),
    )

    decision = pr_gate.changeset_pr_creation_decision(
        issue,
        repo_slug=None,
        repo_root=Path("/repo"),
        git_path="git",
        branch_pr_strategy="sequential",
        beads_root=Path("/beads"),
        lookup_pr_payload=lambda *_args, **_kwargs: None,
    )

    assert decision.allow_pr is False
    assert decision.reason == "blocked:dependency-parent-state-unavailable"


def test_changeset_pr_creation_decision_ignores_parent_child_dependency_variants() -> None:
    issue = {
        "description": (
            "changeset.parent_branch: feature-root\nchangeset.root_branch: feature-root\n"
        ),
        "dependencies": [
            {"dependencyType": "parent_child", "issue": {"id": "at-epic"}},
            "at-epic (open, dependency_type=parent_child)",
        ],
    }

    decision = pr_gate.changeset_pr_creation_decision(
        issue,
        repo_slug="org/repo",
        repo_root=Path("/repo"),
        git_path="git",
        branch_pr_strategy="sequential",
        beads_root=Path("/beads"),
        lookup_pr_payload=lambda *_args, **_kwargs: None,
    )

    assert decision.allow_pr is True
    assert decision.reason == "no-parent"


def test_changeset_pr_creation_decision_uses_dependency_frontier_parent_state(monkeypatch) -> None:
    issue = {
        "description": (
            "changeset.parent_branch: legacy-parent\nchangeset.root_branch: feature-root\n"
        ),
        "dependencies": ["at-epic.1"],
    }

    monkeypatch.setattr(
        pr_gate.beads,
        "run_bd_json",
        lambda args, **_kwargs: (
            [{"description": "changeset.work_branch: active-parent\n"}]
            if args == ["show", "at-epic.1"]
            else []
        ),
    )
    monkeypatch.setattr(pr_gate.git, "git_ref_exists", lambda *_args, **_kwargs: True)

    def _lookup(_repo_slug: str, branch: str) -> dict[str, object] | None:
        if branch == "active-parent":
            return {"state": "OPEN", "isDraft": False}
        if branch == "legacy-parent":
            return {"state": "CLOSED", "closedAt": "2026-02-25T00:00:00Z"}
        return None

    decision = pr_gate.changeset_pr_creation_decision(
        issue,
        repo_slug="org/repo",
        repo_root=Path("/repo"),
        git_path="git",
        branch_pr_strategy="sequential",
        beads_root=Path("/beads"),
        lookup_pr_payload=_lookup,
    )

    assert decision.allow_pr is False
    assert decision.reason == "blocked:pr-open"


def test_changeset_pr_creation_decision_blocks_when_dependency_parent_pr_closed(
    monkeypatch,
) -> None:
    issue = {
        "description": (
            "changeset.parent_branch: legacy-parent\nchangeset.root_branch: feature-root\n"
        ),
        "dependencies": ["at-epic.1"],
    }

    monkeypatch.setattr(
        pr_gate.beads,
        "run_bd_json",
        lambda args, **_kwargs: (
            [{"description": "changeset.work_branch: active-parent\n"}]
            if args == ["show", "at-epic.1"]
            else []
        ),
    )
    monkeypatch.setattr(pr_gate.git, "git_ref_exists", lambda *_args, **_kwargs: True)

    decision = pr_gate.changeset_pr_creation_decision(
        issue,
        repo_slug="org/repo",
        repo_root=Path("/repo"),
        git_path="git",
        branch_pr_strategy="sequential",
        beads_root=Path("/beads"),
        lookup_pr_payload=lambda *_args, **_kwargs: {
            "state": "CLOSED",
            "closedAt": "2026-02-25T00:00:00Z",
        },
    )

    assert decision.allow_pr is False
    assert decision.reason.startswith("blocked:dependency-parent-pr-closed")


def test_changeset_pr_creation_decision_blocks_when_dependency_parent_pr_missing(
    monkeypatch,
) -> None:
    issue = {
        "description": (
            "changeset.parent_branch: legacy-parent\nchangeset.root_branch: feature-root\n"
        ),
        "dependencies": ["at-epic.1"],
    }

    monkeypatch.setattr(
        pr_gate.beads,
        "run_bd_json",
        lambda args, **_kwargs: (
            [
                {
                    "description": (
                        "changeset.work_branch: active-parent\n"
                        "pr_url: https://github.com/org/repo/pull/11\n"
                        "pr_number: 11\n"
                        "pr_state: pr-open\n"
                    )
                }
            ]
            if args == ["show", "at-epic.1"]
            else []
        ),
    )
    monkeypatch.setattr(pr_gate.git, "git_ref_exists", lambda *_args, **_kwargs: True)

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
    assert decision.reason.startswith("blocked:dependency-parent-pr-missing")


def test_sequential_stack_integrity_preflight_reconciles_stale_parent_review_metadata(
    monkeypatch,
) -> None:
    issue = {
        "id": "at-kid.2",
        "description": (
            "changeset.parent_branch: feature-root\nchangeset.root_branch: feature-root\n"
        ),
        "dependencies": ["at-kid.1"],
    }

    monkeypatch.setattr(
        pr_gate.beads,
        "run_bd_json",
        lambda args, **_kwargs: (
            [{"description": "changeset.work_branch: feature-parent\npr_state: closed\n"}]
            if args == ["show", "at-kid.1"]
            else []
        ),
    )
    monkeypatch.setattr(pr_gate.git, "git_ref_exists", lambda *_args, **_kwargs: True)

    reconciled: list[tuple[str, str]] = []
    preflight = pr_gate.sequential_stack_integrity_preflight(
        issue,
        repo_slug="org/repo",
        repo_root=Path("/repo"),
        git_path="git",
        branch_pr_strategy="sequential",
        beads_root=Path("/beads"),
        lookup_pr_payload=lambda *_args, **_kwargs: {"state": "OPEN", "isDraft": False},
        reconcile_parent_review_state=lambda **kwargs: reconciled.append(
            (str(kwargs.get("parent_issue_id")), str(kwargs.get("parent_state")))
        ),
    )

    assert preflight.ok is True
    assert reconciled == [("at-kid.1", "pr-open")]


def test_changeset_pr_creation_decision_treats_integration_parent_as_top_level(
    monkeypatch,
) -> None:
    issue = {
        "description": (
            "changeset.parent_branch: main\n"
            "changeset.root_branch: feature-root\n"
            "workspace.parent_branch: main\n"
        ),
    }
    ref_lookups: list[str] = []
    monkeypatch.setattr(
        pr_gate.git,
        "git_default_branch",
        lambda *_args, **_kwargs: "main",
    )
    monkeypatch.setattr(
        pr_gate.git,
        "git_ref_exists",
        lambda _repo_root, ref, **_kwargs: (ref_lookups.append(ref), True)[1],
    )

    decision = pr_gate.changeset_pr_creation_decision(
        issue,
        repo_slug="org/repo",
        repo_root=Path("/repo"),
        git_path="git",
        branch_pr_strategy="sequential",
        lookup_pr_payload=lambda *_args, **_kwargs: None,
    )

    assert decision.allow_pr is True
    assert decision.reason == "no-parent"
    assert ref_lookups == []


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


def test_handle_pushed_without_pr_uses_diagnostic_payload_after_create(monkeypatch) -> None:
    issue = {
        "description": (
            "changeset.parent_branch: feature-parent\nchangeset.root_branch: feature-root\n"
        ),
        "title": "Example",
    }
    applied_payloads: list[dict[str, object] | None] = []
    monkeypatch.setattr(pr_gate.git, "git_ref_exists", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        pr_gate.beads,
        "update_changeset_review",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("fallback state should not be used when diagnostic returns a PR payload")
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
        create_as_draft=True,
        changeset_base_branch=lambda *_args, **_kwargs: "main",
        changeset_work_branch=lambda _issue: "feature-work",
        render_changeset_pr_body=lambda _issue: "summary",
        lookup_pr_payload=lambda *_args, **_kwargs: None,
        lookup_pr_payload_diagnostic=lambda *_args, **_kwargs: (
            {"number": 165, "state": "OPEN", "isDraft": False},
            None,
        ),
        mark_changeset_in_progress=lambda *_args, **_kwargs: None,
        send_planner_notification=lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("planner notification should not be sent")
        ),
        update_changeset_review_from_pr=lambda *_args, **kwargs: applied_payloads.append(
            kwargs.get("pr_payload")
        ),
        emit=lambda _message: None,
        attempt_create_pr_fn=lambda **_kwargs: (True, "created"),
    )

    assert result.finalize_result.continue_running is True
    assert result.finalize_result.reason == "changeset_review_pending"
    assert applied_payloads == [{"number": 165, "state": "OPEN", "isDraft": False}]

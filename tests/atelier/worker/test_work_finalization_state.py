from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from atelier.worker import work_finalization_state


def test_changeset_base_branch_prefers_workspace_parent_for_first_reviewable(monkeypatch) -> None:
    issue = {
        "id": "at-epic.1",
        "description": ("changeset.root_branch: feat/root\nchangeset.parent_branch: feat/root\n"),
    }

    monkeypatch.setattr(
        work_finalization_state,
        "resolve_epic_id_for_changeset",
        lambda *_args, **_kwargs: "at-epic",
    )
    monkeypatch.setattr(
        work_finalization_state.beads,
        "run_bd_json",
        lambda args, **_kwargs: (
            [{"description": "workspace.parent_branch: main\n"}]
            if args == ["show", "at-epic"]
            else []
        ),
    )
    monkeypatch.setattr(
        work_finalization_state.beads,
        "update_changeset_branch_metadata",
        lambda *_args, **_kwargs: {},
    )

    base = work_finalization_state.changeset_base_branch(
        issue,
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
        git_path="git",
    )

    assert base == "main"


def test_changeset_parent_branch_normalizes_collapsed_root_to_default(monkeypatch) -> None:
    issue = {
        "description": ("changeset.root_branch: feat/root\nchangeset.parent_branch: feat/root\n"),
    }
    monkeypatch.setattr(
        work_finalization_state.git,
        "git_default_branch",
        lambda *_args, **_kwargs: "main",
    )

    parent_branch = work_finalization_state.changeset_parent_branch(
        issue,
        root_branch="feat/root",
        repo_root=Path("/repo"),
    )

    assert parent_branch == "main"


def test_changeset_base_branch_normalizes_collapsed_parent_to_default(monkeypatch) -> None:
    issue = {
        "id": "at-epic.1",
        "description": (
            "changeset.root_branch: feat/root\n"
            "changeset.parent_branch: feat/root\n"
            "changeset.work_branch: feat/work\n"
        ),
    }
    updates: list[dict[str, object]] = []
    monkeypatch.setattr(
        work_finalization_state,
        "resolve_epic_id_for_changeset",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        work_finalization_state.git,
        "git_default_branch",
        lambda *_args, **_kwargs: "main",
    )
    monkeypatch.setattr(
        work_finalization_state.git,
        "git_rev_parse",
        lambda *_args, **_kwargs: "abc1234",
    )
    monkeypatch.setattr(
        work_finalization_state.beads,
        "update_changeset_branch_metadata",
        lambda *args, **kwargs: updates.append(kwargs),
    )

    base = work_finalization_state.changeset_base_branch(
        issue,
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
        git_path="git",
    )

    assert base == "main"
    assert updates
    assert updates[0]["parent_branch"] == "main"


def test_changeset_base_branch_rejects_root_base_without_non_root_fallback(monkeypatch) -> None:
    issue = {
        "description": ("changeset.root_branch: feat/root\nchangeset.parent_branch: feat/root\n"),
    }
    monkeypatch.setattr(
        work_finalization_state.git,
        "git_default_branch",
        lambda *_args, **_kwargs: "feat/root",
    )

    base = work_finalization_state.changeset_base_branch(
        issue,
        repo_root=Path("/repo"),
        git_path="git",
    )

    assert base is None


def test_changeset_parent_branch_resolves_dependency_parent_lineage(monkeypatch) -> None:
    issue = {
        "description": ("changeset.root_branch: feat/root\nchangeset.parent_branch: feat/root\n"),
        "dependencies": ["at-epic.1"],
    }

    monkeypatch.setattr(
        work_finalization_state.beads,
        "run_bd_json",
        lambda args, **_kwargs: (
            [{"description": "changeset.work_branch: feat/at-epic.1\n"}]
            if args == ["show", "at-epic.1"]
            else []
        ),
    )

    parent_branch = work_finalization_state.changeset_parent_branch(
        issue,
        root_branch="feat/root",
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
    )

    assert parent_branch == "feat/at-epic.1"


def test_changeset_base_branch_fails_closed_on_ambiguous_dependency_lineage(monkeypatch) -> None:
    issue = {
        "description": ("changeset.root_branch: feat/root\nchangeset.parent_branch: feat/root\n"),
        "dependencies": ["at-epic.1", "at-epic.2"],
    }

    monkeypatch.setattr(
        work_finalization_state.beads,
        "run_bd_json",
        lambda args, **_kwargs: (
            [{"description": "changeset.work_branch: feat/at-epic.1\n"}]
            if args == ["show", "at-epic.1"]
            else (
                [{"description": "changeset.work_branch: feat/at-epic.2\n"}]
                if args == ["show", "at-epic.2"]
                else []
            )
        ),
    )

    base = work_finalization_state.changeset_base_branch(
        issue,
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
        git_path="git",
    )

    assert base is None


def test_changeset_base_branch_keeps_stacked_parent_before_integration(monkeypatch) -> None:
    issue = {
        "description": (
            "changeset.root_branch: feat/root\n"
            "changeset.parent_branch: feat/parent\n"
            "workspace.parent_branch: main\n"
        )
    }

    monkeypatch.setattr(
        work_finalization_state,
        "branch_ref_for_lookup",
        lambda _repo_root, branch, **_kwargs: branch,
    )
    monkeypatch.setattr(
        work_finalization_state.git,
        "git_is_ancestor",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        work_finalization_state.git,
        "git_branch_fully_applied",
        lambda *_args, **_kwargs: False,
    )

    base = work_finalization_state.changeset_base_branch(
        issue,
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
        git_path="git",
    )

    assert base == "feat/parent"


def test_changeset_base_branch_promotes_to_workspace_parent_after_integration(monkeypatch) -> None:
    issue = {
        "description": (
            "changeset.root_branch: feat/root\n"
            "changeset.parent_branch: feat/parent\n"
            "workspace.parent_branch: main\n"
        )
    }

    monkeypatch.setattr(
        work_finalization_state,
        "branch_ref_for_lookup",
        lambda _repo_root, branch, **_kwargs: branch,
    )
    monkeypatch.setattr(
        work_finalization_state.git,
        "git_is_ancestor",
        lambda _repo, ancestor, descendant, **_kwargs: (
            ancestor == "feat/parent" and descendant == "main"
        ),
    )

    base = work_finalization_state.changeset_base_branch(
        issue,
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
        git_path="git",
    )

    assert base == "main"


def test_changeset_base_branch_persists_lineage_after_dependency_parent_integration(
    monkeypatch,
) -> None:
    issue = {
        "id": "at-epic.2",
        "description": (
            "changeset.root_branch: feat/root\n"
            "changeset.parent_branch: feat/root\n"
            "changeset.work_branch: feat/work\n"
            "workspace.parent_branch: main\n"
        ),
        "dependencies": ["at-epic.1"],
    }
    updates: list[dict[str, object]] = []

    monkeypatch.setattr(
        work_finalization_state.beads,
        "run_bd_json",
        lambda args, **_kwargs: (
            [{"description": "changeset.work_branch: feat/parent\n"}]
            if args == ["show", "at-epic.1"]
            else []
        ),
    )
    monkeypatch.setattr(
        work_finalization_state,
        "branch_ref_for_lookup",
        lambda _repo_root, branch, **_kwargs: branch,
    )
    monkeypatch.setattr(
        work_finalization_state.git,
        "git_is_ancestor",
        lambda _repo, ancestor, descendant, **_kwargs: (
            ancestor == "feat/parent" and descendant == "main"
        ),
    )
    monkeypatch.setattr(
        work_finalization_state.git,
        "git_rev_parse",
        lambda _repo_root, ref, **_kwargs: f"{ref}-sha",
    )
    monkeypatch.setattr(
        work_finalization_state.beads,
        "update_changeset_branch_metadata",
        lambda *_args, **kwargs: updates.append(kwargs),
    )

    base = work_finalization_state.changeset_base_branch(
        issue,
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
        git_path="git",
    )

    assert base == "main"
    assert updates
    assert updates[-1]["parent_branch"] == "main"
    assert updates[-1]["parent_base"] == "main-sha"


def test_changeset_base_branch_keeps_downstream_stacked_on_frontier_dependency(
    monkeypatch,
) -> None:
    issue = {
        "id": "at-kid.3",
        "description": (
            "changeset.root_branch: feat/at-kid\n"
            "changeset.parent_branch: feat/at-kid\n"
            "changeset.work_branch: feat/at-kid.3\n"
            "workspace.parent_branch: main\n"
        ),
        "dependencies": ["at-kid.2"],
    }

    monkeypatch.setattr(
        work_finalization_state.beads,
        "run_bd_json",
        lambda args, **_kwargs: (
            [{"description": "changeset.work_branch: feat/at-kid.2\n"}]
            if args == ["show", "at-kid.2"]
            else []
        ),
    )
    monkeypatch.setattr(
        work_finalization_state,
        "branch_ref_for_lookup",
        lambda _repo_root, branch, **_kwargs: branch,
    )
    monkeypatch.setattr(
        work_finalization_state.git,
        "git_is_ancestor",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        work_finalization_state.git,
        "git_branch_fully_applied",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        work_finalization_state.git,
        "git_rev_parse",
        lambda _repo_root, ref, **_kwargs: f"{ref}-sha",
    )
    monkeypatch.setattr(
        work_finalization_state.beads,
        "update_changeset_branch_metadata",
        lambda *_args, **_kwargs: {},
    )

    base = work_finalization_state.changeset_base_branch(
        issue,
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
        git_path="git",
    )

    assert base == "feat/at-kid.2"


def test_align_existing_pr_base_rebases_and_retargets(monkeypatch) -> None:
    issue = {
        "description": (
            "changeset.root_branch: feat/root\n"
            "changeset.parent_branch: feat/parent\n"
            "changeset.work_branch: feat/work\n"
            "workspace.parent_branch: main\n"
        )
    }
    commands: list[list[str]] = []

    monkeypatch.setattr(
        work_finalization_state,
        "changeset_base_branch",
        lambda *_args, **_kwargs: "main",
    )
    monkeypatch.setattr(work_finalization_state.git, "git_is_clean", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        work_finalization_state.git,
        "git_ref_exists",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        work_finalization_state,
        "branch_ref_for_lookup",
        lambda _repo_root, branch, **_kwargs: branch,
    )
    monkeypatch.setattr(
        work_finalization_state.git,
        "git_current_branch",
        lambda *_args, **_kwargs: "main",
    )
    monkeypatch.setattr(
        work_finalization_state.git,
        "git_rev_parse",
        lambda *_args, **_kwargs: "abc1234",
    )
    monkeypatch.setattr(
        work_finalization_state.beads,
        "update_changeset_branch_metadata",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        work_finalization_state.beads,
        "run_bd_command",
        lambda *_args, **_kwargs: None,
    )

    def _record_command(cmd: list[str]):
        commands.append(list(cmd))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(work_finalization_state.exec, "try_run_command", _record_command)

    ok, detail = work_finalization_state.align_existing_pr_base(
        issue=issue,
        changeset_id="at-epic.2",
        pr_payload={"number": 12, "baseRefName": "feat/parent"},
        repo_slug="org/repo",
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
        git_path="git",
    )

    assert ok is True
    assert detail is not None
    assert "expected=main" in detail
    assert any(
        command[-5:] == ["rebase", "--onto", "main", "feat/parent", "feat/work"]
        for command in commands
    )
    assert any(
        command[-4:] == ["push", "--force-with-lease", "origin", "feat/work"]
        for command in commands
    )
    assert any(
        command[:7] == ["gh", "pr", "edit", "12", "--repo", "org/repo", "--base"]
        and command[-1] == "main"
        for command in commands
    )


def test_attempt_create_pr_accepts_pr_gate_keyword_contract(monkeypatch) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        work_finalization_state.worker_pr_gate,
        "attempt_create_pr",
        lambda **kwargs: (calls.append(kwargs) or True, "created"),
    )

    created, detail = work_finalization_state.attempt_create_pr(
        repo_slug="org/repo",
        issue={"title": "Example"},
        work_branch="feature-work",
        is_draft=False,
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
        git_path="git",
        changeset_base_branch=lambda *_args, **_kwargs: "main",
        render_changeset_pr_body=lambda _issue: "summary",
    )

    assert created is True
    assert detail == "created"
    assert calls
    assert calls[0]["is_draft"] is False
    assert calls[0]["changeset_base_branch"]("ignored", beads_root=None, repo_root=None) == "main"
    assert calls[0]["render_changeset_pr_body"]({"title": "Example"}) == "summary"


def test_handle_pushed_without_pr_uses_injected_create_callback_contract(monkeypatch) -> None:
    issue = {
        "title": "Example",
        "description": (
            "changeset.parent_branch: feature-parent\n"
            "changeset.root_branch: feature-root\n"
            "changeset.work_branch: feature-work\n"
        ),
    }
    review_states: list[str] = []

    monkeypatch.setattr(
        work_finalization_state.worker_pr_gate.git,
        "git_ref_exists",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        work_finalization_state.worker_pr_gate,
        "attempt_create_pr",
        lambda **_kwargs: (True, "created"),
    )
    monkeypatch.setattr(
        work_finalization_state,
        "lookup_pr_payload",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        work_finalization_state,
        "lookup_pr_payload_diagnostic",
        lambda *_args, **_kwargs: (None, None),
    )
    monkeypatch.setattr(
        work_finalization_state,
        "mark_changeset_in_progress",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        work_finalization_state.beads,
        "update_changeset_review",
        lambda _changeset_id, metadata, **_kwargs: review_states.append(
            str(metadata.pr_state or "")
        ),
    )
    monkeypatch.setattr(work_finalization_state, "say", lambda _message: None)

    result = work_finalization_state.handle_pushed_without_pr(
        issue=issue,
        changeset_id="at-123.1",
        agent_id="atelier/worker/codex/p1",
        repo_slug="org/repo",
        repo_root=Path("/repo"),
        beads_root=Path("/beads"),
        branch_pr_strategy="parallel",
        git_path="git",
    )

    assert result.continue_running is True
    assert result.reason == "changeset_review_pending"
    assert review_states == ["draft-pr"]


def test_changeset_waiting_on_review_prefers_live_pr_over_stale_closed_metadata(
    monkeypatch,
) -> None:
    issue = {
        "description": (
            "changeset.root_branch: feat/at-kid\n"
            "changeset.parent_branch: main\n"
            "changeset.work_branch: feat/at-kid.2\n"
            "pr_state: closed\n"
        )
    }

    monkeypatch.setattr(
        work_finalization_state.git,
        "git_ref_exists",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        work_finalization_state,
        "lookup_pr_payload",
        lambda *_args, **_kwargs: {"state": "OPEN", "isDraft": False},
    )

    waiting = work_finalization_state.changeset_waiting_on_review_or_signals(
        issue,
        repo_slug="org/repo",
        repo_root=Path("/repo"),
        branch_pr=True,
        branch_pr_strategy="sequential",
        git_path="git",
    )

    assert waiting is True


def test_changeset_stack_integrity_preflight_reconciles_parent_review_metadata(
    monkeypatch,
) -> None:
    issue = {
        "id": "at-kid.2",
        "description": (
            "changeset.root_branch: feat/at-kid\n"
            "changeset.parent_branch: feat/at-kid\n"
            "changeset.work_branch: feat/at-kid.2\n"
        ),
        "dependencies": ["at-kid.1"],
    }
    observed_states: list[str] = []

    monkeypatch.setattr(
        work_finalization_state.beads,
        "run_bd_json",
        lambda args, **_kwargs: (
            [
                {
                    "description": (
                        "changeset.work_branch: feat/at-kid.1\npr_state: closed\npr_number: 101\n"
                    )
                }
            ]
            if args == ["show", "at-kid.1"]
            else []
        ),
    )
    monkeypatch.setattr(
        work_finalization_state.git,
        "git_ref_exists",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        work_finalization_state,
        "lookup_pr_payload",
        lambda *_args, **_kwargs: {"number": 101, "state": "OPEN", "isDraft": False},
    )
    monkeypatch.setattr(
        work_finalization_state,
        "lookup_pr_payload_diagnostic",
        lambda *_args, **_kwargs: (None, None),
    )
    monkeypatch.setattr(
        work_finalization_state.beads,
        "update_changeset_review",
        lambda _changeset_id, metadata, **_kwargs: observed_states.append(
            str(metadata.pr_state or "")
        ),
    )

    preflight = work_finalization_state.changeset_stack_integrity_preflight(
        issue,
        repo_slug="org/repo",
        repo_root=Path("/repo"),
        git_path="git",
        branch_pr_strategy="sequential",
        beads_root=Path("/beads"),
    )

    assert preflight.ok is True
    assert observed_states == ["pr-open"]

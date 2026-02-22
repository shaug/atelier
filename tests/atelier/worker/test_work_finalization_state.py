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

    base = work_finalization_state.changeset_base_branch(
        issue,
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
        git_path="git",
    )

    assert base == "main"


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

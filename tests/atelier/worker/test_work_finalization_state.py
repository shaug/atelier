from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

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


@pytest.mark.parametrize(
    "legacy_parent_branch",
    [
        "scott/migrate-lifecycle-to-graph-nat-at-o1y4.1",
        "scott/enforce-sequential-dag-depende-at-qc4b.5",
        "scott/enforce-sequential-dag-depende-at-qc4b.3",
    ],
)
def test_changeset_base_branch_sequential_always_uses_epic_parent_branch(
    monkeypatch, legacy_parent_branch: str
) -> None:
    issue = {
        "id": "at-qc4b.8",
        "description": (
            "changeset.root_branch: scott/enforce-sequential-dag-depende\n"
            f"changeset.parent_branch: {legacy_parent_branch}\n"
            "changeset.work_branch: scott/enforce-sequential-dag-depende-at-qc4b.8\n"
            "workspace.parent_branch: main\n"
        ),
    }

    base = work_finalization_state.changeset_base_branch(
        issue,
        beads_root=None,
        repo_root=Path("/repo"),
        git_path="git",
    )

    assert base == "main"


def test_changeset_base_branch_sequential_uses_default_when_workspace_parent_is_missing(
    monkeypatch,
) -> None:
    issue = {
        "id": "at-epic.2",
        "description": (
            "changeset.root_branch: feat/root\n"
            "changeset.parent_branch: feat/parent\n"
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


def test_changeset_base_branch_sequential_resolves_epic_parent_for_noncollapsed_lineage(
    monkeypatch,
) -> None:
    issue = {
        "id": "at-epic.2",
        "description": (
            "changeset.root_branch: feat/root\n"
            "changeset.parent_branch: feat/parent\n"
            "changeset.work_branch: feat/work\n"
        ),
    }
    updates: list[dict[str, object]] = []

    monkeypatch.setattr(
        work_finalization_state,
        "resolve_epic_id_for_changeset",
        lambda *_args, **_kwargs: "at-epic",
    )
    monkeypatch.setattr(
        work_finalization_state.beads,
        "run_bd_json",
        lambda args, **_kwargs: (
            [{"description": "workspace.parent_branch: release/2026.03\n"}]
            if args == ["show", "at-epic"]
            else []
        ),
    )
    monkeypatch.setattr(
        work_finalization_state.git,
        "git_default_branch",
        lambda *_args, **_kwargs: "main",
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

    assert base == "release/2026.03"
    assert updates
    assert updates[-1]["parent_branch"] == "release/2026.03"
    assert updates[-1]["parent_base"] == "release/2026.03-sha"


def test_changeset_base_branch_legacy_strategy_still_uses_integration_parent(monkeypatch) -> None:
    issue = {
        "description": (
            "changeset.root_branch: feat/root\n"
            "changeset.parent_branch: feat/parent\n"
            "workspace.parent_branch: main\n"
        )
    }
    monkeypatch.setattr(
        work_finalization_state.git,
        "git_default_branch",
        lambda *_args, **_kwargs: "main",
    )

    base = work_finalization_state.changeset_base_branch(
        issue,
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
        git_path="git",
    )

    assert base == "main"


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


def test_changeset_base_branch_uses_integration_parent_for_integrated_join_dependencies(
    monkeypatch,
) -> None:
    issue = {
        "id": "at-epic.3",
        "description": (
            "changeset.root_branch: feat/root\n"
            "changeset.parent_branch: feat/root\n"
            "changeset.work_branch: feat/work\n"
            "workspace.parent_branch: main\n"
        ),
        "dependencies": ["at-epic.1", "at-epic.2"],
    }
    updates: list[dict[str, object]] = []

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
    monkeypatch.setattr(
        work_finalization_state.worker_integration_service,
        "changeset_integration_signal",
        lambda *_args, **_kwargs: (True, "abc1234"),
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


def test_changeset_base_branch_blocks_join_default_fallback_without_explicit_heritage_parent(
    monkeypatch,
) -> None:
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
    monkeypatch.setattr(
        work_finalization_state.worker_integration_service,
        "changeset_integration_signal",
        lambda *_args, **_kwargs: (True, "abc1234"),
    )
    monkeypatch.setattr(
        work_finalization_state.git,
        "git_default_branch",
        lambda *_args, **_kwargs: "main",
    )

    base = work_finalization_state.changeset_base_branch(
        issue,
        repo_slug="org/repo",
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
        git_path="git",
    )

    assert base == "main"


def test_changeset_base_branch_uses_same_dependency_integration_signal_as_pr_gate(
    monkeypatch,
) -> None:
    issue = {
        "description": (
            "changeset.root_branch: feat/root\n"
            "changeset.parent_branch: feat/root\n"
            "workspace.parent_branch: main\n"
        ),
        "dependencies": ["at-epic.1", "at-epic.2"],
    }
    observed_repo_slugs: list[str | None] = []
    observed_lookup_payloads: list[dict[str, object] | None] = []

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

    def fake_lookup(repo_slug: str | None, branch: str) -> dict[str, object] | None:
        return {"repo_slug": repo_slug or "", "branch": branch}

    def fake_integration_signal(
        _issue: dict[str, object],
        *,
        repo_slug: str | None,
        repo_root: Path,
        lookup_pr_payload,
        git_path: str | None,
    ) -> tuple[bool, str | None]:
        del repo_root, git_path
        observed_repo_slugs.append(repo_slug)
        observed_lookup_payloads.append(lookup_pr_payload(repo_slug, "feature/dependency"))
        return True, "abc1234"

    monkeypatch.setattr(
        work_finalization_state.worker_integration_service,
        "changeset_integration_signal",
        fake_integration_signal,
    )

    base = work_finalization_state.changeset_base_branch(
        issue,
        repo_slug="org/repo",
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
        git_path="git",
        lookup_pr_payload_fn=fake_lookup,
    )

    assert base == "main"
    assert observed_repo_slugs == []
    assert observed_lookup_payloads == []


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

    assert base == "main"


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

    assert base == "main"


def test_changeset_base_branch_scopes_lineage_to_epic_heritage_at_join_node(monkeypatch) -> None:
    issue = {
        "id": "at-epic.3",
        "parent": "at-epic",
        "description": (
            "changeset.root_branch: feat/at-epic\n"
            "changeset.parent_branch: feat/at-epic\n"
            "changeset.work_branch: feat/at-epic.3\n"
            "workspace.parent_branch: main\n"
        ),
        "dependencies": ["at-epic.2", "at-other.9"],
    }

    monkeypatch.setattr(
        work_finalization_state.beads,
        "run_bd_json",
        lambda args, **_kwargs: (
            [
                {
                    "parent": "at-epic",
                    "description": "changeset.work_branch: feat/at-epic.2\n",
                }
            ]
            if args == ["show", "at-epic.2"]
            else (
                [
                    {
                        "parent": "at-other",
                        "description": "changeset.work_branch: feat/at-other.9\n",
                    }
                ]
                if args == ["show", "at-other.9"]
                else []
            )
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
    assert any(command[-4:] == ["rebase", "--onto", "main", "feat/parent"] for command in commands)
    assert any(
        command[-4:] == ["push", "--force-with-lease", "origin", "feat/work"]
        for command in commands
    )
    assert any(
        command[:7] == ["gh", "pr", "edit", "12", "--repo", "org/repo", "--base"]
        and command[-1] == "main"
        for command in commands
    )


def test_align_existing_pr_base_rebases_from_checked_out_worktree(monkeypatch) -> None:
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
        lambda repo_path, **_kwargs: (
            "feat/work" if str(repo_path) == "/worktrees/at-epic.2" else "main"
        ),
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
        if cmd[:4] == ["git", "-C", "/repo", "worktree"]:
            return SimpleNamespace(
                returncode=0,
                stdout=(
                    "worktree /repo\n"
                    "HEAD abc1234\n"
                    "branch refs/heads/main\n\n"
                    "worktree /worktrees/at-epic.2\n"
                    "HEAD def5678\n"
                    "branch refs/heads/feat/work\n"
                ),
                stderr="",
            )
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
        command[:3] == ["git", "-C", "/worktrees/at-epic.2"]
        and command[3:] == ["rebase", "--onto", "main", "feat/parent"]
        for command in commands
    )
    assert not any(
        command[:3] == ["git", "-C", "/repo"] and command[3:5] == ["checkout", "feat/work"]
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


def test_attempt_create_pr_normalizes_sequential_base_to_epic_parent(monkeypatch) -> None:
    issue = {
        "id": "at-epic.2",
        "title": "Example",
        "description": (
            "changeset.root_branch: feat/root\n"
            "changeset.parent_branch: feat/parent\n"
            "changeset.work_branch: feat/work\n"
            "workspace.parent_branch: main\n"
        ),
    }
    commands: list[list[str]] = []
    metadata_updates: list[dict[str, object]] = []

    monkeypatch.setattr(
        work_finalization_state.worker_pr_gate.exec,
        "try_run_command",
        lambda cmd, **_kwargs: (
            commands.append(list(cmd)) or SimpleNamespace(returncode=0, stdout="created", stderr="")
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
        lambda *_args, **kwargs: metadata_updates.append(kwargs),
    )

    created, detail = work_finalization_state.attempt_create_pr(
        repo_slug="org/repo",
        issue=issue,
        work_branch="feat/work",
        is_draft=True,
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
        git_path="git",
        render_changeset_pr_body=lambda _issue: "summary",
    )

    assert created is True
    assert detail == "created"
    assert commands
    assert commands[0][:8] == [
        "gh",
        "pr",
        "create",
        "--repo",
        "org/repo",
        "--base",
        "main",
        "--head",
    ]
    assert commands[0][8] == "feat/work"
    assert metadata_updates
    assert metadata_updates[-1]["parent_branch"] == "main"
    assert metadata_updates[-1]["parent_base"] == "main-sha"


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
        git_path="git",
    )

    assert waiting is True


def test_changeset_waiting_on_review_treats_closed_pushed_state_as_active(monkeypatch) -> None:
    issue = {
        "status": "closed",
        "description": (
            "changeset.root_branch: feat/at-kid\n"
            "changeset.parent_branch: main\n"
            "changeset.work_branch: feat/at-kid.2\n"
            "pr_state: pushed\n"
        ),
    }

    monkeypatch.setattr(
        work_finalization_state.git,
        "git_ref_exists",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        work_finalization_state,
        "lookup_pr_payload",
        lambda *_args, **_kwargs: None,
    )

    waiting = work_finalization_state.changeset_waiting_on_review_or_signals(
        issue,
        repo_slug="org/repo",
        repo_root=Path("/repo"),
        branch_pr=True,
        git_path="git",
    )

    assert waiting is True


def test_changeset_waiting_on_review_uses_beads_root_for_dependency_parent_gate(
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

    monkeypatch.setattr(
        work_finalization_state.git,
        "git_ref_exists",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        work_finalization_state.beads,
        "run_bd_json",
        lambda args, **_kwargs: (
            [{"description": "changeset.work_branch: feat/at-kid.1\n"}]
            if args == ["show", "at-kid.1"]
            else []
        ),
    )
    monkeypatch.setattr(
        work_finalization_state,
        "lookup_pr_payload",
        lambda _repo_slug, branch: (
            {"state": "CLOSED", "mergedAt": "2026-02-28T00:00:00Z"}
            if branch == "feat/at-kid.1"
            else None
        ),
    )

    waiting_without_beads_context = work_finalization_state.changeset_waiting_on_review_or_signals(
        issue,
        repo_slug="org/repo",
        repo_root=Path("/repo"),
        branch_pr=True,
        git_path="git",
    )
    waiting_with_beads_context = work_finalization_state.changeset_waiting_on_review_or_signals(
        issue,
        repo_slug="org/repo",
        repo_root=Path("/repo"),
        branch_pr=True,
        git_path="git",
        beads_root=Path("/beads"),
    )

    assert waiting_without_beads_context is True
    assert waiting_with_beads_context is False


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
        beads_root=Path("/beads"),
    )

    assert preflight.ok is True
    assert observed_states == ["pr-open"]


def test_changeset_stack_integrity_preflight_fails_closed_when_sequential_base_mismatch(
    monkeypatch,
) -> None:
    issue = {
        "description": (
            "changeset.root_branch: feat/root\n"
            "changeset.parent_branch: feat/root\n"
            "workspace.parent_branch: main\n"
        ),
    }
    monkeypatch.setattr(
        work_finalization_state.worker_pr_gate,
        "sequential_stack_integrity_preflight",
        lambda *_args, **_kwargs: (
            work_finalization_state.worker_pr_gate.StackIntegrityPreflightResult(ok=True)
        ),
    )
    monkeypatch.setattr(
        work_finalization_state,
        "changeset_base_branch",
        lambda *_args, **_kwargs: "feat/parent",
    )

    preflight = work_finalization_state.changeset_stack_integrity_preflight(
        issue,
        repo_slug="org/repo",
        repo_root=Path("/repo"),
        git_path="git",
        beads_root=Path("/beads"),
    )

    assert preflight.ok is False
    assert preflight.reason == "sequential-base-policy-mismatch"


def test_changeset_stack_integrity_preflight_resolves_epic_parent_without_metadata_writes(
    monkeypatch,
) -> None:
    issue = {
        "id": "at-qc4b.8",
        "description": ("changeset.root_branch: feat/root\nchangeset.parent_branch: feat/root\n"),
    }
    metadata_updates: list[dict[str, object]] = []

    monkeypatch.setattr(
        work_finalization_state.worker_pr_gate,
        "sequential_stack_integrity_preflight",
        lambda *_args, **_kwargs: (
            work_finalization_state.worker_pr_gate.StackIntegrityPreflightResult(ok=True)
        ),
    )
    monkeypatch.setattr(
        work_finalization_state,
        "resolve_epic_id_for_changeset",
        lambda *_args, **_kwargs: "at-qc4b",
    )
    monkeypatch.setattr(
        work_finalization_state.beads,
        "run_bd_json",
        lambda args, **_kwargs: (
            [{"description": "workspace.parent_branch: release/2026.03\n"}]
            if args == ["show", "at-qc4b"]
            else []
        ),
    )
    monkeypatch.setattr(
        work_finalization_state.beads,
        "update_changeset_branch_metadata",
        lambda *_args, **kwargs: metadata_updates.append(kwargs),
    )
    monkeypatch.setattr(
        work_finalization_state.git,
        "git_default_branch",
        lambda *_args, **_kwargs: "main",
    )

    preflight = work_finalization_state.changeset_stack_integrity_preflight(
        issue,
        repo_slug="org/repo",
        repo_root=Path("/repo"),
        git_path="git",
        beads_root=Path("/beads"),
    )

    assert preflight.ok is True
    assert metadata_updates == []


def test_release_epic_assignment_uses_runtime_identity_precondition(monkeypatch) -> None:
    state = {"assignee": "atelier/worker/codex/p200", "released": False}

    monkeypatch.setattr(
        work_finalization_state.beads,
        "run_bd_json",
        lambda *_args, **_kwargs: [{"id": "at-epic", "assignee": state["assignee"]}],
    )

    def fake_release_epic_assignment(_epic_id: str, **kwargs: object) -> bool:
        if kwargs["expected_assignee"] == state["assignee"]:
            state["released"] = True
            state["assignee"] = None
            return True
        return False

    monkeypatch.setattr(
        work_finalization_state.beads,
        "release_epic_assignment",
        fake_release_epic_assignment,
    )

    work_finalization_state.release_epic_assignment(
        "at-epic",
        agent_id="atelier/worker/codex/p200",
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
    )

    assert state["released"] is True
    assert state["assignee"] is None


def test_release_epic_assignment_mismatched_runtime_identity_is_no_op(monkeypatch) -> None:
    state = {"assignee": "atelier/worker/codex/p300", "released": False}

    monkeypatch.setattr(
        work_finalization_state.beads,
        "run_bd_json",
        lambda *_args, **_kwargs: [{"id": "at-epic", "assignee": state["assignee"]}],
    )

    def fake_release_epic_assignment(_epic_id: str, **kwargs: object) -> bool:
        if kwargs["expected_assignee"] == state["assignee"]:
            state["released"] = True
            state["assignee"] = None
            return True
        return False

    monkeypatch.setattr(
        work_finalization_state.beads,
        "release_epic_assignment",
        fake_release_epic_assignment,
    )

    work_finalization_state.release_epic_assignment(
        "at-epic",
        agent_id="atelier/worker/codex/p999",
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
    )

    assert state["released"] is False
    assert state["assignee"] == "atelier/worker/codex/p300"

from __future__ import annotations

from pathlib import Path

from atelier.worker.session import runner


def test_select_changeset_uses_startup_override_when_epic_matches() -> None:
    override_issue = {"id": "at-epic.2"}

    selected = runner.select_changeset(
        selected_epic="at-epic",
        startup_changeset_id="at-epic.2",
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
        repo_slug=None,
        branch_pr=False,
        branch_pr_strategy="on-ready",
        git_path="git",
        run_bd_json=lambda args, **_kwargs: (
            [override_issue] if args[:2] == ["show", "at-epic.2"] else []
        ),
        resolve_epic_id_for_changeset=lambda _issue, **_kwargs: "at-epic",
        next_changeset=lambda **_kwargs: {"id": "at-epic.1"},
    )

    assert selected.issue == override_issue
    assert selected.selected_override == "at-epic.2"


def test_select_changeset_falls_back_to_next_ready() -> None:
    selected = runner.select_changeset(
        selected_epic="at-epic",
        startup_changeset_id="at-epic.2",
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
        repo_slug="org/repo",
        branch_pr=True,
        branch_pr_strategy="on-ready",
        git_path="git",
        run_bd_json=lambda _args, **_kwargs: [],
        resolve_epic_id_for_changeset=lambda _issue, **_kwargs: None,
        next_changeset=lambda **_kwargs: {"id": "at-epic.1"},
    )

    assert selected.issue == {"id": "at-epic.1"}
    assert selected.selected_override == "at-epic.2"

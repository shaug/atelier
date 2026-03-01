from pathlib import Path
from unittest.mock import patch

import pytest

import atelier.root_branch as root_branch


def test_partition_root_branch_conflicts_treats_hooked_as_active() -> None:
    issues = [
        {
            "id": "at-open",
            "status": "open",
            "labels": ["at:epic"],
            "title": "Open epic",
        },
        {
            "id": "at-hooked",
            "status": "blocked",
            "labels": ["at:epic", "at:hooked"],
            "title": "Hooked via label",
        },
        {
            "id": "at-closed",
            "status": "closed",
            "labels": ["at:epic"],
            "title": "Closed epic",
        },
    ]

    blocking, reusable = root_branch.partition_root_branch_conflicts(issues)

    assert [issue["id"] for issue in blocking] == ["at-open", "at-hooked"]
    assert [issue["id"] for issue in reusable] == ["at-closed"]


def test_partition_root_branch_conflicts_excludes_current_owner() -> None:
    issues = [
        {"id": "at-current", "status": "hooked", "labels": ["at:epic", "at:hooked"]},
        {"id": "at-other", "status": "in_progress", "labels": ["at:epic"]},
    ]

    blocking, reusable = root_branch.partition_root_branch_conflicts(
        issues,
        owner_issue_id="at-current",
    )

    assert [issue["id"] for issue in blocking] == ["at-other"]
    assert reusable == []


def test_prompt_root_branch_assume_yes_fails_when_active_owner_exists() -> None:
    conflicts = [
        {
            "id": "at-owner",
            "status": "hooked",
            "labels": ["at:epic", "at:hooked"],
            "title": "Owner",
        }
    ]
    with (
        patch("atelier.root_branch.branching.suggest_root_branch", return_value="feat/root"),
        patch("atelier.root_branch.beads.find_epics_by_root_branch", return_value=conflicts),
    ):
        with pytest.raises(SystemExit):
            root_branch.prompt_root_branch(
                title="Example",
                branch_prefix="",
                beads_root=Path("/beads"),
                repo_root=Path("/repo"),
                assume_yes=True,
            )


def test_prompt_root_branch_assume_yes_uses_epic_suffix_for_unique_default() -> None:
    looked_up_branches: list[str] = []

    def fake_find_epics_by_root_branch(
        root_branch: str, *, beads_root: Path, cwd: Path
    ) -> list[dict[str, object]]:
        del beads_root, cwd
        looked_up_branches.append(root_branch)
        return []

    with (
        patch(
            "atelier.root_branch.beads.find_epics_by_root_branch",
            side_effect=fake_find_epics_by_root_branch,
        ),
        patch("atelier.root_branch.git.git_ref_exists", return_value=False),
    ):
        resolved = root_branch.prompt_root_branch(
            title="Example Root Branch",
            branch_prefix="scott/",
            epic_id="at-uuzc",
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            assume_yes=True,
        )

    assert resolved == "scott/example-root-branch-at-uuzc"
    assert looked_up_branches == ["scott/example-root-branch-at-uuzc"]


def test_prompt_root_branch_allows_interactive_reuse_when_confirmed() -> None:
    reusable = [
        {
            "id": "at-closed",
            "status": "closed",
            "labels": ["at:epic"],
            "title": "Closed epic",
        }
    ]
    with (
        patch("atelier.root_branch.prompt", return_value="feat/reused"),
        patch("atelier.root_branch.beads.find_epics_by_root_branch", return_value=reusable),
        patch("atelier.root_branch.confirm", return_value=True),
        patch("atelier.root_branch.git.git_ref_exists", return_value=False),
    ):
        resolved = root_branch.prompt_root_branch(
            title="Ignored",
            branch_prefix="feat/",
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            assume_yes=False,
        )

    assert resolved == "feat/reused"

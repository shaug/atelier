from pathlib import Path
from unittest.mock import patch

from atelier import worktrees
from atelier.worker import integration


def test_branch_ref_for_lookup_prefers_local_head() -> None:
    with patch("atelier.worker.integration.git.git_ref_exists") as ref_exists:
        ref_exists.side_effect = [True]
        resolved = integration.branch_ref_for_lookup(Path("/repo"), "feature/test")

    assert resolved == "feature/test"


def test_changeset_integration_signal_uses_integrated_sha_from_notes() -> None:
    issue = {
        "description": (
            "changeset.root_branch: feat/root\n"
            "changeset.parent_branch: main\n"
            "changeset.work_branch: feat/work\n"
        ),
        "notes": (
            "implementation complete\n"
            "changeset.integrated_sha: abcdef1234567890abcdef1234567890abcdef12\n"
        ),
    }

    with (
        patch(
            "atelier.worker.integration.git.git_rev_parse",
            return_value="abcdef1234567890abcdef1234567890abcdef12",
        ),
        patch("atelier.worker.integration.branch_ref_for_lookup", return_value="main"),
        patch("atelier.worker.integration.git.git_is_ancestor", return_value=True),
    ):
        ok, integrated_sha = integration.changeset_integration_signal(
            issue,
            repo_slug=None,
            repo_root=Path("/repo"),
            lookup_pr_payload=lambda _repo, _branch: None,
        )

    assert ok is True
    assert integrated_sha == "abcdef1234567890abcdef1234567890abcdef12"


def test_changeset_integration_signal_uses_merged_pr_signal() -> None:
    issue = {
        "description": ("changeset.root_branch: feat/root\nchangeset.work_branch: feat/work\n")
    }
    ok, integrated_sha = integration.changeset_integration_signal(
        issue,
        repo_slug="org/repo",
        repo_root=Path("/repo"),
        lookup_pr_payload=lambda _repo, _branch: {"mergedAt": "2026-02-20T00:00:00Z"},
    )

    assert ok is True
    assert integrated_sha is None


def test_cleanup_epic_branches_and_worktrees_invokes_git_actions() -> None:
    mapping = worktrees.WorktreeMapping(
        epic_id="at-1",
        worktree_path="worktrees/at-1",
        root_branch="feat/root",
        changesets={"at-1": "feat/root-at-1"},
        changeset_worktrees={"at-1": "worktrees/at-1.1"},
    )
    calls: list[list[str]] = []

    def fake_run_git_status(
        args: list[str],
        *,
        repo_root: Path,
        git_path: str | None = None,
        cwd: Path | None = None,
    ) -> tuple[bool, str | None]:
        calls.append(args)
        return True, None

    with (
        patch(
            "atelier.worker.integration.worktrees.mapping_path",
            return_value=Path("/tmp/mapping.json"),
        ),
        patch("atelier.worker.integration.worktrees.load_mapping", return_value=mapping),
        patch("pathlib.Path.exists", return_value=True),
        patch("pathlib.Path.unlink", return_value=None),
    ):
        integration.cleanup_epic_branches_and_worktrees(
            project_data_dir=Path("/tmp/project"),
            repo_root=Path("/repo"),
            epic_id="at-1",
            keep_branches={"main"},
            run_git_status=fake_run_git_status,
        )

    assert ["push", "origin", "--delete", "feat/root"] in calls
    assert ["branch", "-D", "feat/root-at-1"] in calls

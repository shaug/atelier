from pathlib import Path
from unittest.mock import patch

from atelier import prs
from atelier.worker import stale_pr_lifecycle


def test_classify_stale_terminal_pr_lifecycle_marks_candidate_fields() -> None:
    issue = {
        "status": "blocked",
        "description": "changeset.work_branch: feat/root-at-1.2\npr_state: in-review\n",
    }

    with (
        patch("atelier.worker.stale_pr_lifecycle.git.git_ref_exists", return_value=True),
        patch(
            "atelier.worker.stale_pr_lifecycle.prs.lookup_github_pr_status",
            return_value=prs.GithubPrLookup(
                outcome="found",
                payload={
                    "number": 12,
                    "state": "CLOSED",
                    "isDraft": False,
                    "reviewDecision": None,
                    "mergedAt": "2026-03-01T00:00:00Z",
                    "closedAt": "2026-03-01T00:00:00Z",
                },
            ),
        ),
    ):
        result = stale_pr_lifecycle.classify_stale_terminal_pr_lifecycle(
            issue,
            repo_slug="org/repo",
            repo_root=Path("/repo"),
            branch_pr=True,
            git_path="git",
        )

    assert result.kind == "candidate"
    assert result.reason == "terminal_pr_merged"
    assert result.live_pr_state == "merged"
    assert result.stale_fields == ("status", "pr_state")


def test_classify_stale_terminal_pr_lifecycle_tracks_status_only_when_review_state_matches() -> (
    None
):
    issue = {
        "status": "in_progress",
        "description": "changeset.work_branch: feat/root-at-1.3\npr_state: merged\n",
    }

    with (
        patch("atelier.worker.stale_pr_lifecycle.git.git_ref_exists", return_value=True),
        patch(
            "atelier.worker.stale_pr_lifecycle.prs.lookup_github_pr_status",
            return_value=prs.GithubPrLookup(
                outcome="found",
                payload={
                    "number": 13,
                    "state": "CLOSED",
                    "isDraft": False,
                    "reviewDecision": None,
                    "mergedAt": "2026-03-02T00:00:00Z",
                    "closedAt": "2026-03-02T00:00:00Z",
                },
            ),
        ),
    ):
        result = stale_pr_lifecycle.classify_stale_terminal_pr_lifecycle(
            issue,
            repo_slug="org/repo",
            repo_root=Path("/repo"),
            branch_pr=True,
            git_path="git",
        )

    assert result.kind == "candidate"
    assert result.stale_fields == ("status",)


def test_classify_stale_terminal_pr_lifecycle_excludes_active_pr_states() -> None:
    issue = {
        "status": "blocked",
        "description": "changeset.work_branch: feat/root-at-1.4\npr_state: closed\n",
    }

    with (
        patch("atelier.worker.stale_pr_lifecycle.git.git_ref_exists", return_value=True),
        patch(
            "atelier.worker.stale_pr_lifecycle.prs.lookup_github_pr_status",
            return_value=prs.GithubPrLookup(
                outcome="found",
                payload={
                    "number": 14,
                    "state": "OPEN",
                    "isDraft": False,
                    "reviewDecision": None,
                },
            ),
        ),
    ):
        result = stale_pr_lifecycle.classify_stale_terminal_pr_lifecycle(
            issue,
            repo_slug="org/repo",
            repo_root=Path("/repo"),
            branch_pr=True,
            git_path="git",
        )

    assert result.kind == "none"
    assert result.reason == "active_pr_lifecycle_pr-open"
    assert result.live_pr_state == "pr-open"


def test_classify_stale_terminal_pr_lifecycle_marks_lookup_failure_as_anomaly() -> None:
    issue = {
        "status": "blocked",
        "description": "changeset.work_branch: feat/root-at-1.5\npr_state: draft-pr\n",
    }

    with (
        patch("atelier.worker.stale_pr_lifecycle.git.git_ref_exists", return_value=True),
        patch(
            "atelier.worker.stale_pr_lifecycle.prs.lookup_github_pr_status",
            side_effect=[
                prs.GithubPrLookup(outcome="error", error="gh timeout"),
                prs.GithubPrLookup(outcome="error", error="gh timeout"),
            ],
        ),
    ):
        result = stale_pr_lifecycle.classify_stale_terminal_pr_lifecycle(
            issue,
            repo_slug="org/repo",
            repo_root=Path("/repo"),
            branch_pr=True,
            git_path="git",
        )

    assert result.kind == "anomaly"
    assert result.reason == "pr_lifecycle_lookup_failed"
    assert result.detail == "gh timeout"

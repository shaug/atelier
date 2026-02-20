from unittest.mock import patch

from atelier import prs


def test_github_repo_slug() -> None:
    assert prs.github_repo_slug("github.com/org/repo") == "org/repo"
    assert prs.github_repo_slug("https://github.com/org/repo.git") == "org/repo"
    assert prs.github_repo_slug("git@github.com:org/repo.git") == "org/repo"
    assert prs.github_repo_slug("git@bitbucket.org:org/repo.git") is None


def test_lifecycle_state_prefers_merged() -> None:
    payload = {"mergedAt": "2025-01-01T00:00:00Z"}
    assert prs.lifecycle_state(payload, pushed=True, review_requested=True) == "merged"


def test_lifecycle_state_handles_pr_open() -> None:
    payload = {"state": "OPEN", "isDraft": False, "reviewDecision": None}
    assert (
        prs.lifecycle_state(payload, pushed=True, review_requested=False) == "pr-open"
    )


def test_lifecycle_state_falls_back_to_pushed() -> None:
    assert prs.lifecycle_state(None, pushed=True, review_requested=False) == "pushed"


def test_latest_feedback_timestamp_prefers_non_bot_reviewer_events() -> None:
    payload = {
        "comments": [
            {
                "createdAt": "2026-02-20T10:00:00Z",
                "author": {"isBot": False},
            },
            {
                "updatedAt": "2026-02-20T11:00:00Z",
                "author": {"isBot": True},
            },
        ],
        "reviews": [
            {
                "state": "COMMENTED",
                "submittedAt": "2026-02-20T12:00:00Z",
                "author": {"isBot": False},
            },
            {
                "state": "APPROVED",
                "submittedAt": "2026-02-20T13:00:00Z",
                "author": {"isBot": False},
            },
        ],
    }
    assert prs.latest_feedback_timestamp(payload) == "2026-02-20T12:00:00Z"


def test_latest_feedback_timestamp_includes_review_comments() -> None:
    payload = {
        "number": 204,
        "comments": [],
        "reviews": [
            {
                "state": "COMMENTED",
                "submittedAt": "2026-02-20T02:57:05Z",
                "author": {"isBot": False},
            }
        ],
    }
    review_comments = [
        {
            "created_at": "2026-02-20T02:57:06Z",
            "updated_at": "2026-02-20T02:57:06Z",
            "user": {"login": "shaug", "type": "User"},
        }
    ]
    with patch("atelier.prs._run_json", return_value=review_comments):
        assert (
            prs.latest_feedback_timestamp_with_inline_comments(
                payload, repo="organicvideodev/tuber-service"
            )
            == "2026-02-20T02:57:06Z"
        )


def test_latest_feedback_timestamp_is_payload_only() -> None:
    payload = {"number": 204, "comments": [], "reviews": []}
    with patch("atelier.prs._run_json") as run_json:
        assert prs.latest_feedback_timestamp(payload) is None
    run_json.assert_not_called()


def test_unresolved_review_thread_count_counts_unresolved_threads() -> None:
    payload = {
        "data": {
            "repository": {
                "pullRequest": {
                    "reviewThreads": {
                        "nodes": [{"isResolved": False}, {"isResolved": True}],
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                    }
                }
            }
        }
    }
    with (
        patch("atelier.prs._gh_available", return_value=True),
        patch("atelier.prs._run_json", return_value=payload),
    ):
        assert prs.unresolved_review_thread_count("org/repo", 42) == 1


def test_unresolved_review_thread_count_returns_none_on_command_failure() -> None:
    with (
        patch("atelier.prs._gh_available", return_value=True),
        patch("atelier.prs._run_json", side_effect=RuntimeError("boom")),
    ):
        assert prs.unresolved_review_thread_count("org/repo", 42) is None

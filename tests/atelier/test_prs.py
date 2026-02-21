import subprocess
from unittest.mock import patch

import pytest

from atelier import prs


@pytest.fixture(autouse=True)
def _clear_pr_runtime_cache() -> object:
    prs.clear_runtime_cache()
    yield
    prs.clear_runtime_cache()


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


def test_lifecycle_state_invalid_payload_fails_deterministically() -> None:
    with pytest.raises(ValueError, match="invalid github PR payload"):
        prs.lifecycle_state(
            {"number": "not-a-number"},
            pushed=True,
            review_requested=False,
        )


def test_lookup_github_pr_status_reports_not_found() -> None:
    with (
        patch("atelier.prs._gh_available", return_value=True),
        patch("atelier.prs._find_latest_pr_number", return_value=None),
    ):
        result = prs.lookup_github_pr_status("org/repo", "feature/test")

    assert result.outcome == "not_found"
    assert result.payload is None
    assert result.error is None


def test_lookup_github_pr_status_reports_found_payload() -> None:
    with (
        patch("atelier.prs._gh_available", return_value=True),
        patch("atelier.prs._find_latest_pr_number", return_value=42),
        patch("atelier.prs._run_json", return_value={"number": 42, "state": "OPEN"}),
    ):
        result = prs.lookup_github_pr_status("org/repo", "feature/test")

    assert result.outcome == "found"
    assert result.payload == {"number": 42, "state": "OPEN"}
    assert result.error is None


def test_lookup_github_pr_status_reports_query_errors() -> None:
    with (
        patch("atelier.prs._gh_available", return_value=True),
        patch(
            "atelier.prs._find_latest_pr_number",
            side_effect=RuntimeError("gh auth failed"),
        ),
    ):
        result = prs.lookup_github_pr_status("org/repo", "feature/test")

    assert result.outcome == "error"
    assert result.payload is None
    assert result.error == "gh auth failed"


def test_run_retries_retryable_errors_before_success() -> None:
    transient = subprocess.CompletedProcess(
        args=["gh"], returncode=1, stdout="", stderr="TLS timeout"
    )
    success = subprocess.CompletedProcess(
        args=["gh"], returncode=0, stdout="ok", stderr=""
    )
    with (
        patch(
            "atelier.prs.subprocess.run", side_effect=[transient, success]
        ) as run_cmd,
        patch("atelier.prs.time.sleep") as sleep,
    ):
        output = prs._run(["gh", "pr", "list"])

    assert output == "ok"
    assert run_cmd.call_count == 2
    sleep.assert_called_once()


def test_lookup_github_pr_status_uses_runtime_cache() -> None:
    with (
        patch("atelier.prs._gh_available", return_value=True),
        patch("atelier.prs._find_latest_pr_number", return_value=7) as latest_pr,
        patch(
            "atelier.prs._run_json",
            return_value={"number": 7, "state": "OPEN"},
        ) as run_json,
    ):
        first = prs.lookup_github_pr_status("org/repo", "feature/test")
        second = prs.lookup_github_pr_status("org/repo", "feature/test")

    assert first.found is True
    assert second.found is True
    latest_pr.assert_called_once()
    run_json.assert_called_once()


def test_unresolved_review_thread_count_uses_runtime_cache() -> None:
    payload = {
        "data": {
            "repository": {
                "pullRequest": {
                    "reviewThreads": {
                        "nodes": [{"isResolved": False}],
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                    }
                }
            }
        }
    }
    with (
        patch("atelier.prs._gh_available", return_value=True),
        patch("atelier.prs._run_json", return_value=payload) as run_json,
    ):
        first = prs.unresolved_review_thread_count("org/repo", 42)
        second = prs.unresolved_review_thread_count("org/repo", 42)

    assert first == 1
    assert second == 1
    run_json.assert_called_once()


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


def test_latest_feedback_timestamp_compares_timezones_by_instant() -> None:
    payload = {
        "comments": [
            {
                "createdAt": "2026-02-20T09:30:00-05:00",
                "author": {"isBot": False},
            }
        ],
        "reviews": [
            {
                "state": "COMMENTED",
                "submittedAt": "2026-02-20T13:00:00Z",
                "author": {"isBot": False},
            }
        ],
    }
    assert prs.latest_feedback_timestamp(payload) == "2026-02-20T14:30:00Z"


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


def test_latest_feedback_with_inline_prefers_newer_inline_timestamp() -> None:
    payload = {
        "number": 204,
        "comments": [
            {
                "createdAt": "2026-02-20T02:57:05Z",
                "author": {"isBot": False},
            }
        ],
        "reviews": [],
    }
    inline_comments = [
        {
            "created_at": "2026-02-20T02:57:07Z",
            "updated_at": "2026-02-20T02:57:07Z",
            "user": {"login": "reviewer", "type": "User"},
        }
    ]
    with patch("atelier.prs._run_json", return_value=inline_comments):
        assert (
            prs.latest_feedback_timestamp_with_inline_comments(payload, repo="org/repo")
            == "2026-02-20T02:57:07Z"
        )


def test_unresolved_review_thread_count_paginates() -> None:
    payload_page_1 = {
        "data": {
            "repository": {
                "pullRequest": {
                    "reviewThreads": {
                        "nodes": [{"isResolved": False}],
                        "pageInfo": {"hasNextPage": True, "endCursor": "c1"},
                    }
                }
            }
        }
    }
    payload_page_2 = {
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
        patch("atelier.prs._run_json", side_effect=[payload_page_1, payload_page_2]),
    ):
        assert prs.unresolved_review_thread_count("org/repo", 42) == 2

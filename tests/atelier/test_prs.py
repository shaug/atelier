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

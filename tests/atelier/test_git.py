import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

import atelier.git as git


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("github.com/owner/repo", "github.com/owner/repo"),
        ("https://github.com/owner/repo.git", "github.com/owner/repo"),
        ("git@github.com:owner/repo.git", "github.com/owner/repo"),
        ("ssh://git@github.com/owner/repo.git", "github.com/owner/repo"),
    ],
)
def test_normalize_origin_url(value: str, expected: str) -> None:
    assert git.normalize_origin_url(value) == expected


def test_git_is_ancestor_handles_status_codes() -> None:
    with patch(
        "atelier.git._run_git_or_die",
        return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout=""),
    ):
        assert git.git_is_ancestor(Path("/repo"), "a", "b") is True
    with patch(
        "atelier.git._run_git_or_die",
        return_value=subprocess.CompletedProcess(args=[], returncode=1, stdout=""),
    ):
        assert git.git_is_ancestor(Path("/repo"), "a", "b") is False
    with patch(
        "atelier.git._run_git_or_die",
        return_value=subprocess.CompletedProcess(args=[], returncode=128, stdout=""),
    ):
        assert git.git_is_ancestor(Path("/repo"), "a", "b") is None


def test_git_branch_fully_applied_uses_git_cherry_output() -> None:
    with patch(
        "atelier.git._run_git_or_die",
        return_value=subprocess.CompletedProcess(
            args=[], returncode=0, stdout="- abcdef message\n- 123456 message\n"
        ),
    ):
        assert git.git_branch_fully_applied(Path("/repo"), "root", "work") is True
    with patch(
        "atelier.git._run_git_or_die",
        return_value=subprocess.CompletedProcess(
            args=[], returncode=0, stdout="- abcdef message\n+ 123456 message\n"
        ),
    ):
        assert git.git_branch_fully_applied(Path("/repo"), "root", "work") is False
    with patch(
        "atelier.git._run_git_or_die",
        return_value=subprocess.CompletedProcess(args=[], returncode=128, stdout=""),
    ):
        assert git.git_branch_fully_applied(Path("/repo"), "root", "work") is None

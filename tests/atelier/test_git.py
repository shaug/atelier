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

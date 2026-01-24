from unittest import TestCase

import atelier.git as git


class TestNormalizeOriginUrl(TestCase):
    def test_owner_name_with_host(self) -> None:
        self.assertEqual(
            git.normalize_origin_url("github.com/owner/repo"),
            "github.com/owner/repo",
        )

    def test_https_normalizes(self) -> None:
        value = "https://github.com/owner/repo.git"
        self.assertEqual(git.normalize_origin_url(value), "github.com/owner/repo")

    def test_ssh_scp_style(self) -> None:
        value = "git@github.com:owner/repo.git"
        self.assertEqual(git.normalize_origin_url(value), "github.com/owner/repo")

    def test_ssh_scheme(self) -> None:
        value = "ssh://git@github.com/owner/repo.git"
        self.assertEqual(git.normalize_origin_url(value), "github.com/owner/repo")

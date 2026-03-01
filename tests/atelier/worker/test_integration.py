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


def test_changeset_integration_signal_rejects_merged_pr_without_branch_proof() -> None:
    issue = {
        "description": (
            "changeset.root_branch: feat/root\n"
            "changeset.parent_branch: main\n"
            "changeset.work_branch: feat/work\n"
        )
    }

    with (
        patch("atelier.worker.integration.branch_ref_for_lookup", return_value=None),
        patch("atelier.worker.integration.git.git_rev_parse", return_value=None),
    ):
        ok, integrated_sha = integration.changeset_integration_signal(
            issue,
            repo_slug="org/repo",
            repo_root=Path("/repo"),
            lookup_pr_payload=lambda _repo, _branch: {"mergedAt": "2026-02-20T00:00:00Z"},
            require_target_branch_proof=True,
        )

    assert ok is False
    assert integrated_sha is None


def test_changeset_integration_signal_strict_mode_uses_origin_target_ref() -> None:
    issue = {
        "description": (
            "changeset.root_branch: feat/root\n"
            "changeset.parent_branch: main\n"
            "changeset.work_branch: feat/work\n"
        )
    }

    def fake_ref_exists(_repo_root: Path, ref: str, *, git_path: str | None = None) -> bool:
        del git_path
        return ref in {
            "refs/heads/feat/root",
            "refs/heads/feat/work",
            "refs/heads/main",
            "refs/remotes/origin/main",
        }

    def fake_is_ancestor(
        _repo_root: Path,
        ancestor: str,
        descendant: str,
        *,
        git_path: str | None = None,
    ) -> bool:
        del git_path
        return ancestor == "feat/work" and descendant == "origin/main"

    def fake_rev_parse(_repo_root: Path, ref: str, *, git_path: str | None = None) -> str | None:
        del git_path
        mapping = {
            "feat/work": "worksha",
            "feat/root": "rootsha",
        }
        return mapping.get(ref)

    with (
        patch("atelier.worker.integration.git.git_ref_exists", side_effect=fake_ref_exists),
        patch("atelier.worker.integration.git.git_default_branch", return_value="main"),
        patch("atelier.worker.integration.git.git_is_ancestor", side_effect=fake_is_ancestor),
        patch("atelier.worker.integration.git.git_branch_fully_applied", return_value=False),
        patch("atelier.worker.integration.git.git_rev_parse", side_effect=fake_rev_parse),
        patch(
            "atelier.worker.integration._refresh_origin_refs", return_value=False
        ) as refresh_refs,
    ):
        ok, integrated_sha = integration.changeset_integration_signal(
            issue,
            repo_slug=None,
            repo_root=Path("/repo"),
            lookup_pr_payload=lambda _repo, _branch: None,
            require_target_branch_proof=True,
        )

    assert ok is True
    assert integrated_sha == "worksha"
    refresh_refs.assert_not_called()


def test_changeset_integration_signal_strict_mode_retries_after_fetch_refresh() -> None:
    issue = {
        "description": (
            "changeset.root_branch: feat/root\n"
            "changeset.parent_branch: main\n"
            "changeset.work_branch: feat/work\n"
        )
    }
    refreshed = {"value": False}

    def fake_ref_exists(_repo_root: Path, ref: str, *, git_path: str | None = None) -> bool:
        del git_path
        return ref in {
            "refs/heads/feat/root",
            "refs/heads/feat/work",
            "refs/heads/main",
            "refs/remotes/origin/main",
        }

    def fake_is_ancestor(
        _repo_root: Path,
        ancestor: str,
        descendant: str,
        *,
        git_path: str | None = None,
    ) -> bool:
        del git_path
        return refreshed["value"] and ancestor == "feat/work" and descendant == "origin/main"

    def fake_rev_parse(_repo_root: Path, ref: str, *, git_path: str | None = None) -> str | None:
        del git_path
        mapping = {
            "feat/work": "worksha",
            "feat/root": "rootsha",
        }
        return mapping.get(ref)

    def fake_refresh(_repo_root: Path, *, git_path: str | None = None) -> bool:
        del git_path
        refreshed["value"] = True
        return True

    with (
        patch("atelier.worker.integration.git.git_ref_exists", side_effect=fake_ref_exists),
        patch("atelier.worker.integration.git.git_default_branch", return_value="main"),
        patch("atelier.worker.integration.git.git_is_ancestor", side_effect=fake_is_ancestor),
        patch("atelier.worker.integration.git.git_branch_fully_applied", return_value=False),
        patch("atelier.worker.integration.git.git_rev_parse", side_effect=fake_rev_parse),
        patch(
            "atelier.worker.integration._refresh_origin_refs", side_effect=fake_refresh
        ) as refresh,
    ):
        ok, integrated_sha = integration.changeset_integration_signal(
            issue,
            repo_slug=None,
            repo_root=Path("/repo"),
            lookup_pr_payload=lambda _repo, _branch: None,
            require_target_branch_proof=True,
        )

    assert ok is True
    assert integrated_sha == "worksha"
    assert refresh.call_count == 1


def test_changeset_integration_signal_accepts_patch_equivalent_branch_to_target() -> None:
    issue = {
        "description": (
            "changeset.root_branch: feat/root\n"
            "changeset.parent_branch: main\n"
            "changeset.work_branch: feat/work\n"
        )
    }

    def fake_branch_ref_for_lookup(
        _repo_root: Path, branch: str, *, git_path: str | None = None
    ) -> str | None:
        del git_path
        mapping = {
            "main": "origin/main",
            "feat/work": "feat/work",
            "feat/root": "feat/root",
        }
        return mapping.get(branch)

    def fake_branch_fully_applied(
        _repo_root: Path, target: str, source: str, *, git_path: str | None = None
    ) -> bool:
        del git_path
        return target == "origin/main" and source == "feat/work"

    with (
        patch(
            "atelier.worker.integration.branch_ref_for_lookup",
            side_effect=fake_branch_ref_for_lookup,
        ),
        patch("atelier.worker.integration.git.git_is_ancestor", return_value=False),
        patch(
            "atelier.worker.integration.git.git_branch_fully_applied",
            side_effect=fake_branch_fully_applied,
        ),
        patch("atelier.worker.integration.git.git_rev_parse", return_value="worksha"),
    ):
        ok, integrated_sha = integration.changeset_integration_signal(
            issue,
            repo_slug=None,
            repo_root=Path("/repo"),
            lookup_pr_payload=lambda _repo, _branch: None,
            require_target_branch_proof=True,
        )

    assert ok is True
    assert integrated_sha == "worksha"


def test_changeset_integration_signal_strict_mode_accepts_root_proof_without_work_branch() -> None:
    issue = {"description": ("changeset.root_branch: feat/root\nchangeset.parent_branch: main\n")}

    def fake_branch_ref_for_lookup(
        _repo_root: Path, branch: str, *, git_path: str | None = None
    ) -> str | None:
        del git_path
        mapping = {"main": "origin/main", "feat/root": "feat/root"}
        return mapping.get(branch)

    def fake_is_ancestor(
        _repo_root: Path,
        ancestor: str,
        descendant: str,
        *,
        git_path: str | None = None,
    ) -> bool:
        del git_path
        return ancestor == "feat/root" and descendant == "origin/main"

    with (
        patch(
            "atelier.worker.integration.branch_ref_for_lookup",
            side_effect=fake_branch_ref_for_lookup,
        ),
        patch("atelier.worker.integration.git.git_is_ancestor", side_effect=fake_is_ancestor),
        patch("atelier.worker.integration.git.git_branch_fully_applied", return_value=False),
        patch("atelier.worker.integration.git.git_rev_parse", return_value="rootsha"),
    ):
        ok, integrated_sha = integration.changeset_integration_signal(
            issue,
            repo_slug=None,
            repo_root=Path("/repo"),
            lookup_pr_payload=lambda _repo, _branch: None,
            require_target_branch_proof=True,
        )

    assert ok is True
    assert integrated_sha == "rootsha"


def test_changeset_integration_signal_strict_sha_requires_source_reachability() -> None:
    issue = {
        "description": (
            "changeset.integrated_sha: abcdef1234567890abcdef1234567890abcdef12\n"
            "changeset.root_branch: feat/root\n"
            "changeset.parent_branch: main\n"
            "changeset.work_branch: feat/work\n"
        )
    }

    def fake_branch_ref_for_lookup(
        _repo_root: Path, branch: str, *, git_path: str | None = None
    ) -> str | None:
        del git_path
        mapping = {
            "main": "origin/main",
            "feat/work": "feat/work",
            "feat/root": "feat/root",
        }
        return mapping.get(branch)

    def fake_is_ancestor(
        _repo_root: Path,
        ancestor: str,
        descendant: str,
        *,
        git_path: str | None = None,
    ) -> bool:
        del git_path
        if ancestor == "abcdef1234567890abcdef1234567890abcdef12" and descendant == "origin/main":
            return True
        return False

    with (
        patch(
            "atelier.worker.integration.branch_ref_for_lookup",
            side_effect=fake_branch_ref_for_lookup,
        ),
        patch(
            "atelier.worker.integration.git.git_rev_parse",
            return_value="abcdef1234567890abcdef1234567890abcdef12",
        ),
        patch("atelier.worker.integration.git.git_is_ancestor", side_effect=fake_is_ancestor),
        patch("atelier.worker.integration.git.git_branch_fully_applied", return_value=False),
    ):
        ok, integrated_sha = integration.changeset_integration_signal(
            issue,
            repo_slug=None,
            repo_root=Path("/repo"),
            lookup_pr_payload=lambda _repo, _branch: None,
            require_target_branch_proof=True,
        )

    assert ok is False
    assert integrated_sha is None


def test_changeset_integration_signal_strict_sha_allows_target_only_when_source_refs_missing() -> (
    None
):
    issue = {
        "description": (
            "changeset.integrated_sha: abcdef1234567890abcdef1234567890abcdef12\n"
            "changeset.root_branch: feat/root\n"
            "changeset.parent_branch: main\n"
            "changeset.work_branch: feat/work\n"
        )
    }

    def fake_branch_ref_for_lookup(
        _repo_root: Path, branch: str, *, git_path: str | None = None
    ) -> str | None:
        del git_path
        mapping = {"main": "origin/main"}
        return mapping.get(branch)

    def fake_is_ancestor(
        _repo_root: Path,
        ancestor: str,
        descendant: str,
        *,
        git_path: str | None = None,
    ) -> bool:
        del git_path
        return (
            ancestor == "abcdef1234567890abcdef1234567890abcdef12" and descendant == "origin/main"
        )

    with (
        patch(
            "atelier.worker.integration.branch_ref_for_lookup",
            side_effect=fake_branch_ref_for_lookup,
        ),
        patch(
            "atelier.worker.integration.git.git_rev_parse",
            return_value="abcdef1234567890abcdef1234567890abcdef12",
        ),
        patch("atelier.worker.integration.git.git_is_ancestor", side_effect=fake_is_ancestor),
        patch("atelier.worker.integration.git.git_branch_fully_applied", return_value=False),
    ):
        ok, integrated_sha = integration.changeset_integration_signal(
            issue,
            repo_slug=None,
            repo_root=Path("/repo"),
            lookup_pr_payload=lambda _repo, _branch: None,
            require_target_branch_proof=True,
        )

    assert ok is True
    assert integrated_sha == "abcdef1234567890abcdef1234567890abcdef12"


def test_changeset_integration_signal_rejects_unproven_integrated_sha() -> None:
    issue = {
        "description": (
            "changeset.integrated_sha: abcdef1234567\n"
            "changeset.root_branch: feat/root\n"
            "changeset.parent_branch: main\n"
            "changeset.work_branch: feat/work\n"
        )
    }

    with (
        patch(
            "atelier.worker.integration.git.git_rev_parse",
            return_value="abcdef1234567",
        ),
        patch("atelier.worker.integration.branch_ref_for_lookup", return_value=None),
    ):
        ok, integrated_sha = integration.changeset_integration_signal(
            issue,
            repo_slug=None,
            repo_root=Path("/repo"),
            lookup_pr_payload=lambda _repo, _branch: None,
        )

    assert ok is False
    assert integrated_sha is None


def test_changeset_integration_signal_active_pr_state_requires_parent_integration() -> None:
    issue = {
        "description": (
            "changeset.root_branch: feat/root\n"
            "changeset.parent_branch: main\n"
            "changeset.work_branch: feat/root\n"
            "pr_state: draft-pr\n"
        )
    }

    def fake_is_ancestor(
        _repo_root: Path,
        ancestor: str,
        descendant: str,
        *,
        git_path: str | None = None,
    ) -> bool:
        del git_path
        if ancestor == "feat/root" and descendant == "feat/root":
            return True
        if ancestor == "feat/root" and descendant == "main":
            return False
        return False

    with (
        patch(
            "atelier.worker.integration.branch_ref_for_lookup",
            side_effect=lambda _r, branch, **_k: branch,
        ),
        patch("atelier.worker.integration.git.git_is_ancestor", side_effect=fake_is_ancestor),
        patch("atelier.worker.integration.git.git_branch_fully_applied", return_value=False),
    ):
        ok, integrated_sha = integration.changeset_integration_signal(
            issue,
            repo_slug="org/repo",
            repo_root=Path("/repo"),
            lookup_pr_payload=lambda _repo, _branch: {"mergedAt": None},
            require_target_branch_proof=True,
        )

    assert ok is False
    assert integrated_sha is None


def test_changeset_integration_signal_active_pr_state_allows_parent_integration() -> None:
    issue = {
        "description": (
            "changeset.root_branch: feat/root\n"
            "changeset.parent_branch: main\n"
            "changeset.work_branch: feat/root\n"
            "pr_state: pr-open\n"
        )
    }

    with (
        patch(
            "atelier.worker.integration.branch_ref_for_lookup",
            side_effect=lambda _r, branch, **_k: branch,
        ),
        patch(
            "atelier.worker.integration.git.git_is_ancestor",
            side_effect=lambda _repo_root, ancestor, descendant, *, git_path=None: (
                ancestor == "feat/root" and descendant == "main"
            ),
        ),
        patch("atelier.worker.integration.git.git_branch_fully_applied", return_value=False),
        patch("atelier.worker.integration.git.git_rev_parse", return_value="rootsha"),
    ):
        ok, integrated_sha = integration.changeset_integration_signal(
            issue,
            repo_slug="org/repo",
            repo_root=Path("/repo"),
            lookup_pr_payload=lambda _repo, _branch: {"mergedAt": None},
            require_target_branch_proof=True,
        )

    assert ok is True
    assert integrated_sha == "rootsha"


def test_changeset_integration_signal_active_pr_state_uses_work_to_target_for_stacked_changesets() -> (
    None
):
    issue = {
        "description": (
            "changeset.root_branch: feat/root\n"
            "changeset.parent_branch: main\n"
            "changeset.work_branch: feat/work\n"
            "pr_state: pr-open\n"
        )
    }

    def fake_is_ancestor(
        _repo_root: Path,
        ancestor: str,
        descendant: str,
        *,
        git_path: str | None = None,
    ) -> bool:
        del git_path
        return ancestor == "feat/work" and descendant == "main"

    with (
        patch(
            "atelier.worker.integration.branch_ref_for_lookup",
            side_effect=lambda _r, branch, **_k: branch,
        ),
        patch("atelier.worker.integration.git.git_is_ancestor", side_effect=fake_is_ancestor),
        patch("atelier.worker.integration.git.git_branch_fully_applied", return_value=False),
        patch("atelier.worker.integration.git.git_rev_parse", return_value="rootsha"),
    ):
        ok, integrated_sha = integration.changeset_integration_signal(
            issue,
            repo_slug="org/repo",
            repo_root=Path("/repo"),
            lookup_pr_payload=lambda _repo, _branch: {"mergedAt": None},
            require_target_branch_proof=True,
        )

    assert ok is True
    assert integrated_sha == "rootsha"


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


def test_integrate_epic_root_to_parent_uses_file_backed_squash_commit_message() -> None:
    commands: list[list[str]] = []
    observed: dict[str, object] = {}

    def fake_run_git_status(
        args: list[str],
        *,
        repo_root: Path,
        git_path: str | None = None,
        cwd: Path | None = None,
    ) -> tuple[bool, str | None]:
        commands.append(list(args))
        if args[:2] == ["commit", "-F"]:
            message_path = Path(args[2])
            observed["message_path"] = message_path
            observed["message_exists_during_call"] = message_path.exists()
            observed["message_text"] = message_path.read_text(encoding="utf-8")
        return True, None

    with (
        patch("atelier.worker.integration.git.git_is_clean", return_value=True),
        patch(
            "atelier.worker.integration.git.git_rev_parse",
            side_effect=lambda _repo, ref, **_kwargs: f"{ref}-sha",
        ),
        patch("atelier.worker.integration.git.git_is_ancestor", return_value=False),
        patch("atelier.worker.integration.git.git_branch_fully_applied", return_value=False),
        patch("atelier.worker.integration.git.git_current_branch", return_value="feature/current"),
    ):
        ok, integrated_sha, detail = integration.integrate_epic_root_to_parent(
            epic_issue={"title": "Example"},
            epic_id="at-1",
            root_branch="feature/root",
            parent_branch="main",
            history="squash",
            squash_message_mode="deterministic",
            squash_message_agent_spec=None,
            squash_message_agent_options=None,
            squash_message_agent_home=None,
            squash_message_agent_env=None,
            integration_cwd=None,
            repo_root=Path("/repo"),
            git_path="git",
            ensure_local_branch=lambda *_args, **_kwargs: True,
            run_git_status=fake_run_git_status,
            sync_local_branch_from_remote=lambda *_args, **_kwargs: False,
            normalize_squash_message_mode=lambda _value: "deterministic",
            agent_generated_squash_subject=lambda **_kwargs: None,
            squash_subject=lambda _issue, _epic_id: "feat: `safe` $(printf noop)",
        )

    assert ok is True
    assert integrated_sha == "main-sha"
    assert detail is None
    assert any(command[:2] == ["commit", "-F"] for command in commands)
    assert not any(command[:2] == ["commit", "-m"] for command in commands)
    assert observed["message_exists_during_call"] is True
    assert observed["message_text"] == "feat: `safe` $(printf noop)"
    message_path = observed["message_path"]
    assert isinstance(message_path, Path)
    assert not message_path.exists()

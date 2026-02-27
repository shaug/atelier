"""Tests for gc.worktrees."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import atelier.gc.worktrees as gc_worktrees
import atelier.worktrees as worktrees


def test_collect_resolved_epic_artifacts_prunes_worktrees_and_branches() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        project_dir = root / "data"
        repo_root = root / "repo"
        project_dir.mkdir(parents=True, exist_ok=True)
        repo_root.mkdir(parents=True, exist_ok=True)
        epic_id = "at-epic"
        mapping_path = worktrees.mapping_path(project_dir, epic_id)
        mapping_path.parent.mkdir(parents=True, exist_ok=True)
        worktrees.write_mapping(
            mapping_path,
            worktrees.WorktreeMapping(
                epic_id=epic_id,
                worktree_path=f"worktrees/{epic_id}",
                root_branch="feat/root",
                changesets={"at-epic.1": "feat/root-at-epic.1"},
                changeset_worktrees={"at-epic.1": "worktrees/at-epic.1"},
            ),
        )
        epic_worktree = project_dir / "worktrees" / epic_id
        changeset_worktree = project_dir / "worktrees" / "at-epic.1"
        epic_worktree.mkdir(parents=True, exist_ok=True)
        changeset_worktree.mkdir(parents=True, exist_ok=True)
        (epic_worktree / ".git").write_text("gitdir: /tmp/a", encoding="utf-8")
        (changeset_worktree / ".git").write_text("gitdir: /tmp/b", encoding="utf-8")
        epic_issue = {
            "id": epic_id,
            "status": "closed",
            "labels": ["at:epic"],
            "description": "workspace.parent_branch: main\n",
        }
        refs = {
            "refs/heads/main",
            "refs/remotes/origin/main",
            "refs/heads/feat/root",
            "refs/remotes/origin/feat/root",
            "refs/heads/feat/root-at-epic.1",
            "refs/remotes/origin/feat/root-at-epic.1",
        }
        commands: list[list[str]] = []

        with (
            patch("atelier.gc.worktrees.try_show_issue", return_value=epic_issue),
            patch(
                "atelier.beads.epic_changeset_summary",
                side_effect=AssertionError("summary should not gate closed epic cleanup"),
            ),
            patch("atelier.git.git_default_branch", return_value="main"),
            patch(
                "atelier.git.git_ref_exists",
                side_effect=lambda repo, ref, git_path=None: ref in refs,
            ),
            patch("atelier.git.git_is_ancestor", return_value=True),
            patch("atelier.git.git_branch_fully_applied", return_value=False),
            patch("atelier.git.git_status_porcelain", return_value=[]),
            patch("atelier.git.git_current_branch", return_value="main"),
            patch(
                "atelier.gc.worktrees.run_git_gc_command",
                side_effect=lambda args, repo_root=None, git_path=None: (
                    commands.append(args),
                    (True, ""),
                )[1],
            ),
        ):
            actions = gc_worktrees.collect_resolved_epic_artifacts(
                project_dir=project_dir,
                beads_root=Path("/beads"),
                repo_root=repo_root,
                git_path="git",
                assume_yes=False,
            )
            assert len(actions) == 1
            actions[0].apply()

        assert ["worktree", "remove", str(epic_worktree)] in commands
        assert ["worktree", "remove", str(changeset_worktree)] in commands
        assert ["push", "origin", "--delete", "feat/root"] in commands
        assert ["push", "origin", "--delete", "feat/root-at-epic.1"] in commands
        assert ["branch", "-D", "feat/root"] in commands
        assert ["branch", "-D", "feat/root-at-epic.1"] in commands
        assert not mapping_path.exists()


def test_collect_resolved_epic_artifacts_skips_when_not_integrated() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        project_dir = root / "data"
        repo_root = root / "repo"
        project_dir.mkdir(parents=True, exist_ok=True)
        repo_root.mkdir(parents=True, exist_ok=True)
        epic_id = "at-epic"
        mapping_path = worktrees.mapping_path(project_dir, epic_id)
        mapping_path.parent.mkdir(parents=True, exist_ok=True)
        worktrees.write_mapping(
            mapping_path,
            worktrees.WorktreeMapping(
                epic_id=epic_id,
                worktree_path=f"worktrees/{epic_id}",
                root_branch="feat/root",
                changesets={},
                changeset_worktrees={},
            ),
        )
        epic_worktree = project_dir / "worktrees" / epic_id
        epic_worktree.mkdir(parents=True, exist_ok=True)
        (epic_worktree / ".git").write_text("gitdir: /tmp/a", encoding="utf-8")
        epic_issue = {
            "id": epic_id,
            "status": "closed",
            "labels": ["at:epic"],
            "description": "workspace.parent_branch: main\n",
        }
        refs = {
            "refs/heads/main",
            "refs/remotes/origin/main",
            "refs/heads/feat/root",
            "refs/remotes/origin/feat/root",
        }

        with (
            patch("atelier.gc.worktrees.try_show_issue", return_value=epic_issue),
            patch(
                "atelier.beads.epic_changeset_summary",
                side_effect=AssertionError("summary should not gate closed epic cleanup"),
            ),
            patch("atelier.git.git_default_branch", return_value="main"),
            patch(
                "atelier.git.git_ref_exists",
                side_effect=lambda repo, ref, git_path=None: ref in refs,
            ),
            patch("atelier.git.git_is_ancestor", return_value=False),
            patch("atelier.git.git_branch_fully_applied", return_value=False),
        ):
            actions = gc_worktrees.collect_resolved_epic_artifacts(
                project_dir=project_dir,
                beads_root=Path("/beads"),
                repo_root=repo_root,
                git_path="git",
                assume_yes=False,
            )

        assert actions == []


def test_collect_closed_workspace_branches_without_mapping_prunes_integrated_root() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        project_dir = root / "data"
        repo_root = root / "repo"
        project_dir.mkdir(parents=True, exist_ok=True)
        repo_root.mkdir(parents=True, exist_ok=True)

        issue = {
            "id": "at-irs",
            "status": "closed",
            "labels": ["workspace:project-guardrail"],
            "description": (
                "workspace.root_branch: project-guardrail\n"
                "workspace.parent_branch: main\n"
                "changeset.root_branch: project-guardrail\n"
                "changeset.work_branch: project-guardrail-at-irs\n"
                "pr_state: merged\n"
            ),
        }
        refs = {
            "refs/heads/main",
            "refs/remotes/origin/main",
            "refs/heads/project-guardrail",
            "refs/remotes/origin/project-guardrail",
        }
        commands: list[list[str]] = []

        with (
            patch(
                "atelier.beads.list_all_changesets",
                return_value=[issue],
            ),
            patch("atelier.git.git_default_branch", return_value="main"),
            patch(
                "atelier.git.git_ref_exists",
                side_effect=lambda repo, ref, git_path=None: ref in refs,
            ),
            patch("atelier.git.git_is_ancestor", return_value=True),
            patch("atelier.git.git_branch_fully_applied", return_value=False),
            patch("atelier.git.git_current_branch", return_value="main"),
            patch(
                "atelier.gc.worktrees.run_git_gc_command",
                side_effect=lambda args, repo_root=None, git_path=None: (
                    commands.append(args),
                    (True, ""),
                )[1],
            ),
        ):
            actions = gc_worktrees.collect_closed_workspace_branches_without_mapping(
                project_dir=project_dir,
                beads_root=Path("/beads"),
                repo_root=repo_root,
                git_path="git",
            )
            assert len(actions) == 1
            actions[0].apply()

        assert ["push", "origin", "--delete", "project-guardrail"] in commands
        assert ["branch", "-D", "project-guardrail"] in commands


def test_collect_closed_workspace_branches_without_mapping_skips_not_integrated() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        project_dir = root / "data"
        repo_root = root / "repo"
        project_dir.mkdir(parents=True, exist_ok=True)
        repo_root.mkdir(parents=True, exist_ok=True)

        issue = {
            "id": "at-irs",
            "status": "closed",
            "labels": ["workspace:project-guardrail"],
            "description": (
                "workspace.root_branch: project-guardrail\n"
                "workspace.parent_branch: main\n"
                "changeset.root_branch: project-guardrail\n"
                "pr_state: merged\n"
            ),
        }
        refs = {
            "refs/heads/main",
            "refs/remotes/origin/main",
            "refs/heads/project-guardrail",
            "refs/remotes/origin/project-guardrail",
        }

        with (
            patch(
                "atelier.beads.list_all_changesets",
                return_value=[issue],
            ),
            patch("atelier.git.git_default_branch", return_value="main"),
            patch(
                "atelier.git.git_ref_exists",
                side_effect=lambda repo, ref, git_path=None: ref in refs,
            ),
            patch("atelier.git.git_is_ancestor", return_value=False),
            patch("atelier.git.git_branch_fully_applied", return_value=False),
        ):
            actions = gc_worktrees.collect_closed_workspace_branches_without_mapping(
                project_dir=project_dir,
                beads_root=Path("/beads"),
                repo_root=repo_root,
                git_path="git",
            )

        assert actions == []

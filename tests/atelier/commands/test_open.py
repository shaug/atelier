import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import atelier.commands.open as open_cmd
import atelier.config as config


def _make_issue(root_branch: str, worktree_relpath: str) -> dict[str, object]:
    return {
        "id": "epic-1",
        "title": "Epic",
        "status": "open",
        "labels": ["at:epic", f"workspace:{root_branch}"],
        "description": (
            f"workspace.root_branch: {root_branch}\nworktree_path: {worktree_relpath}\n"
        ),
    }


def test_open_runs_command_in_worktree() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        project_root = root / "project"
        repo_root = root / "repo"
        project_root.mkdir()
        repo_root.mkdir()
        project_data_dir = root / "data"
        worktree_path = project_data_dir / "worktrees" / "epic-1"
        worktree_path.mkdir(parents=True)
        (worktree_path / ".git").write_text("gitdir: /tmp\n", encoding="utf-8")

        project_config = config.ProjectConfig()
        issue = _make_issue("feat/root", "worktrees/epic-1")
        captured: dict[str, object] = {}

        def fake_run(request: object, *, runner: object | None = None) -> object:
            del runner
            assert isinstance(request, open_cmd.exec.CommandRequest)
            captured["cmd"] = list(request.argv)
            captured["cwd"] = request.cwd
            captured["env"] = request.env
            return open_cmd.exec.CommandResult(
                argv=request.argv, returncode=7, stdout="", stderr=""
            )

        with (
            patch(
                "atelier.commands.open.resolve_current_project_with_repo_root",
                return_value=(project_root, project_config, str(repo_root), repo_root),
            ),
            patch(
                "atelier.commands.open.config.resolve_project_data_dir",
                return_value=project_data_dir,
            ),
            patch(
                "atelier.commands.open.config.resolve_beads_root",
                return_value=Path("/beads"),
            ),
            patch("atelier.commands.open.beads.run_bd_command"),
            patch(
                "atelier.commands.open.beads.find_epics_by_root_branch",
                return_value=[issue],
            ),
            patch("atelier.commands.open.exec.run_with_runner", fake_run),
        ):
            with pytest.raises(SystemExit) as raised:
                open_cmd.open_worktree(
                    SimpleNamespace(
                        workspace_name="feat/root",
                        raw=False,
                        command=["echo", "hi"],
                        shell=None,
                        workspace_root=False,
                        set_title=False,
                    )
                )

        assert raised.value.code == 7
        assert captured["cmd"] == ["echo", "hi"]
        assert captured["cwd"] == worktree_path
        env = captured["env"]
        assert env
        assert env["ATELIER_WORKSPACE"] == "feat/root"
        assert env["ATELIER_WORKSPACE_DIR"] == str(worktree_path)


def test_open_uses_shell_override() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        project_root = root / "project"
        repo_root = root / "repo"
        project_root.mkdir()
        repo_root.mkdir()
        project_data_dir = root / "data"
        worktree_path = project_data_dir / "worktrees" / "epic-1"
        worktree_path.mkdir(parents=True)
        (worktree_path / ".git").write_text("gitdir: /tmp\n", encoding="utf-8")

        project_config = config.ProjectConfig()
        issue = _make_issue("feat/root", "worktrees/epic-1")
        captured: dict[str, object] = {}

        def fake_run(request: object, *, runner: object | None = None) -> object:
            del runner
            assert isinstance(request, open_cmd.exec.CommandRequest)
            captured["cmd"] = list(request.argv)
            captured["cwd"] = request.cwd
            return open_cmd.exec.CommandResult(
                argv=request.argv, returncode=0, stdout="", stderr=""
            )

        with (
            patch(
                "atelier.commands.open.resolve_current_project_with_repo_root",
                return_value=(project_root, project_config, str(repo_root), repo_root),
            ),
            patch(
                "atelier.commands.open.config.resolve_project_data_dir",
                return_value=project_data_dir,
            ),
            patch(
                "atelier.commands.open.config.resolve_beads_root",
                return_value=Path("/beads"),
            ),
            patch("atelier.commands.open.beads.run_bd_command"),
            patch(
                "atelier.commands.open.beads.find_epics_by_root_branch",
                return_value=[issue],
            ),
            patch("atelier.commands.open.exec.run_with_runner", fake_run),
        ):
            with pytest.raises(SystemExit) as raised:
                open_cmd.open_worktree(
                    SimpleNamespace(
                        workspace_name="feat/root",
                        raw=False,
                        command=[],
                        shell="zsh",
                        workspace_root=False,
                        set_title=False,
                    )
                )

        assert raised.value.code == 0
        assert captured["cmd"] == ["zsh"]
        assert captured["cwd"] == worktree_path


def test_open_prompts_for_workspace() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        project_root = root / "project"
        repo_root = root / "repo"
        project_root.mkdir()
        repo_root.mkdir()
        project_data_dir = root / "data"
        worktree_path = project_data_dir / "worktrees" / "epic-1"
        worktree_path.mkdir(parents=True)
        (worktree_path / ".git").write_text("gitdir: /tmp\n", encoding="utf-8")

        project_config = config.ProjectConfig()
        issue = _make_issue("feat/root", "worktrees/epic-1")
        choices = ["feat/root [open] Epic (epic-1)"]

        def fake_run(request: object, *, runner: object | None = None) -> object:
            del runner
            assert isinstance(request, open_cmd.exec.CommandRequest)
            return open_cmd.exec.CommandResult(
                argv=request.argv, returncode=0, stdout="", stderr=""
            )

        with (
            patch(
                "atelier.commands.open.resolve_current_project_with_repo_root",
                return_value=(project_root, project_config, str(repo_root), repo_root),
            ),
            patch(
                "atelier.commands.open.config.resolve_project_data_dir",
                return_value=project_data_dir,
            ),
            patch(
                "atelier.commands.open.config.resolve_beads_root",
                return_value=Path("/beads"),
            ),
            patch("atelier.commands.open.beads.run_bd_command"),
            patch(
                "atelier.commands.open.beads.run_bd_json",
                return_value=[issue],
            ),
            patch("atelier.commands.open.select", return_value=choices[0]),
            patch("atelier.commands.open.exec.run_with_runner", fake_run),
        ):
            with pytest.raises(SystemExit):
                open_cmd.open_worktree(
                    SimpleNamespace(
                        workspace_name=None,
                        raw=False,
                        command=["ls"],
                        shell=None,
                        workspace_root=False,
                        set_title=False,
                    )
                )

import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import atelier.commands.shell as shell_cmd
import atelier.paths as paths
import atelier.term as term
from tests.atelier.helpers import (
    NORMALIZED_ORIGIN,
    DummyResult,
    enlistment_path_for,
    workspace_id_for,
    write_open_config,
    write_workspace_config,
)


class TestShellCommand:
    def test_shell_runs_command_in_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_open_config(project_dir, enlistment_path)

            workspace_branch = "scott/alpha"
            workspace_dir = paths.workspace_dir_for_branch(
                project_dir,
                workspace_branch,
                workspace_id_for(enlistment_path, workspace_branch),
            )
            repo_dir = workspace_dir / "repo"
            repo_dir.mkdir(parents=True)
            write_workspace_config(workspace_dir, workspace_branch, enlistment_path)

            captured: dict[str, object] = {}

            def fake_run(
                cmd: list[str],
                cwd: Path | None = None,
                env: dict[str, str] | None = None,
            ) -> DummyResult:
                captured["cmd"] = cmd
                captured["cwd"] = cwd
                captured["env"] = env
                return DummyResult(returncode=5)

            with (
                patch(
                    "atelier.commands.shell.git.resolve_repo_enlistment",
                    return_value=(None, enlistment_path, None, NORMALIZED_ORIGIN),
                ),
                patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                patch("atelier.commands.shell.git.git_is_repo", return_value=True),
                patch("atelier.commands.shell.exec.run_command_status", fake_run),
            ):
                with pytest.raises(SystemExit) as raised:
                    shell_cmd.open_workspace_shell(
                        SimpleNamespace(
                            workspace_name=workspace_branch,
                            shell=None,
                            command=["echo", "hello"],
                        )
                    )

            assert raised.value.code == 5
            assert captured["cmd"] == ["echo", "hello"]
            assert captured["cwd"] == repo_dir
            assert captured["env"]["ATELIER_WORKSPACE"] == workspace_branch
            assert captured["env"]["ATELIER_PROJECT"] == enlistment_path
            assert captured["env"]["ATELIER_WORKSPACE_DIR"] == str(workspace_dir)

    def test_shell_runs_command_in_workspace_root_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_open_config(project_dir, enlistment_path)

            workspace_branch = "scott/alpha"
            workspace_dir = paths.workspace_dir_for_branch(
                project_dir,
                workspace_branch,
                workspace_id_for(enlistment_path, workspace_branch),
            )
            repo_dir = workspace_dir / "repo"
            repo_dir.mkdir(parents=True)
            write_workspace_config(workspace_dir, workspace_branch, enlistment_path)

            captured: dict[str, object] = {}

            def fake_run(
                cmd: list[str],
                cwd: Path | None = None,
                env: dict[str, str] | None = None,
            ) -> DummyResult:
                captured["cmd"] = cmd
                captured["cwd"] = cwd
                captured["env"] = env
                return DummyResult(returncode=0)

            with (
                patch(
                    "atelier.commands.shell.git.resolve_repo_enlistment",
                    return_value=(None, enlistment_path, None, NORMALIZED_ORIGIN),
                ),
                patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                patch("atelier.commands.shell.git.git_is_repo", return_value=True),
                patch("atelier.commands.shell.exec.run_command_status", fake_run),
            ):
                with pytest.raises(SystemExit) as raised:
                    shell_cmd.open_workspace_shell(
                        SimpleNamespace(
                            workspace_name=workspace_branch,
                            shell=None,
                            command=["echo", "hello"],
                            workspace_root=True,
                        )
                    )

            assert raised.value.code == 0
            assert captured["cmd"] == ["echo", "hello"]
            assert captured["cwd"] == workspace_dir
            assert captured["env"]["ATELIER_WORKSPACE"] == workspace_branch
            assert captured["env"]["ATELIER_PROJECT"] == enlistment_path
            assert captured["env"]["ATELIER_WORKSPACE_DIR"] == str(workspace_dir)

    def test_shell_uses_override_for_interactive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_open_config(project_dir, enlistment_path)

            workspace_branch = "scott/alpha"
            workspace_dir = paths.workspace_dir_for_branch(
                project_dir,
                workspace_branch,
                workspace_id_for(enlistment_path, workspace_branch),
            )
            repo_dir = workspace_dir / "repo"
            repo_dir.mkdir(parents=True)
            write_workspace_config(workspace_dir, workspace_branch, enlistment_path)

            captured: dict[str, object] = {}

            def fake_run(
                cmd: list[str],
                cwd: Path | None = None,
                env: dict[str, str] | None = None,
            ) -> DummyResult:
                captured["cmd"] = cmd
                captured["cwd"] = cwd
                return DummyResult(returncode=0)

            with (
                patch(
                    "atelier.commands.shell.git.resolve_repo_enlistment",
                    return_value=(None, enlistment_path, None, NORMALIZED_ORIGIN),
                ),
                patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                patch("atelier.commands.shell.git.git_is_repo", return_value=True),
                patch("atelier.commands.shell.exec.run_command_status", fake_run),
            ):
                with pytest.raises(SystemExit) as raised:
                    shell_cmd.open_workspace_shell(
                        SimpleNamespace(
                            workspace_name=workspace_branch,
                            shell="zsh",
                            command=[],
                        )
                    )

            assert raised.value.code == 0
            assert captured["cmd"] == ["zsh"]
            assert captured["cwd"] == repo_dir

    def test_shell_parses_override_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_open_config(project_dir, enlistment_path)

            workspace_branch = "scott/alpha"
            workspace_dir = paths.workspace_dir_for_branch(
                project_dir,
                workspace_branch,
                workspace_id_for(enlistment_path, workspace_branch),
            )
            repo_dir = workspace_dir / "repo"
            repo_dir.mkdir(parents=True)
            write_workspace_config(workspace_dir, workspace_branch, enlistment_path)

            captured: dict[str, object] = {}

            def fake_run(
                cmd: list[str],
                cwd: Path | None = None,
                env: dict[str, str] | None = None,
            ) -> DummyResult:
                captured["cmd"] = cmd
                captured["cwd"] = cwd
                return DummyResult(returncode=0)

            with (
                patch(
                    "atelier.commands.shell.git.resolve_repo_enlistment",
                    return_value=(None, enlistment_path, None, NORMALIZED_ORIGIN),
                ),
                patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                patch("atelier.commands.shell.git.git_is_repo", return_value=True),
                patch("atelier.commands.shell.exec.run_command_status", fake_run),
            ):
                with pytest.raises(SystemExit) as raised:
                    shell_cmd.open_workspace_shell(
                        SimpleNamespace(
                            workspace_name=workspace_branch,
                            shell="bash -l",
                            command=[],
                        )
                    )

            assert raised.value.code == 0
            assert captured["cmd"] == ["bash", "-l"]
            assert captured["cwd"] == repo_dir

    def test_shell_emits_title_escape_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_open_config(project_dir, enlistment_path)

            workspace_branch = "scott/alpha"
            workspace_dir = paths.workspace_dir_for_branch(
                project_dir,
                workspace_branch,
                workspace_id_for(enlistment_path, workspace_branch),
            )
            repo_dir = workspace_dir / "repo"
            repo_dir.mkdir(parents=True)
            write_workspace_config(workspace_dir, workspace_branch, enlistment_path)

            captured: dict[str, object] = {}

            def fake_run(
                cmd: list[str],
                cwd: Path | None = None,
                env: dict[str, str] | None = None,
            ) -> DummyResult:
                return DummyResult(returncode=0)

            def fake_emit(title: str) -> bool:
                captured["title"] = title
                return True

            with (
                patch(
                    "atelier.commands.shell.git.resolve_repo_enlistment",
                    return_value=(None, enlistment_path, None, NORMALIZED_ORIGIN),
                ),
                patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                patch("atelier.commands.shell.git.git_is_repo", return_value=True),
                patch("atelier.commands.shell.exec.run_command_status", fake_run),
                patch("atelier.commands.shell.term.emit_title_escape", fake_emit),
            ):
                with pytest.raises(SystemExit):
                    shell_cmd.open_workspace_shell(
                        SimpleNamespace(
                            workspace_name=workspace_branch,
                            shell=None,
                            command=["true"],
                            set_title=True,
                        )
                    )

            assert captured["title"] == term.workspace_title(
                enlistment_path, workspace_branch
            )

    def test_exec_requires_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_open_config(project_dir, enlistment_path)

            workspace_branch = "scott/alpha"
            workspace_dir = paths.workspace_dir_for_branch(
                project_dir,
                workspace_branch,
                workspace_id_for(enlistment_path, workspace_branch),
            )
            repo_dir = workspace_dir / "repo"
            repo_dir.mkdir(parents=True)
            write_workspace_config(workspace_dir, workspace_branch, enlistment_path)

            with (
                patch(
                    "atelier.commands.shell.git.resolve_repo_enlistment",
                    return_value=(None, enlistment_path, None, NORMALIZED_ORIGIN),
                ),
                patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                patch("atelier.commands.shell.git.git_is_repo", return_value=True),
            ):
                with pytest.raises(SystemExit):
                    shell_cmd.open_workspace_shell(
                        SimpleNamespace(
                            workspace_name=workspace_branch,
                            shell=None,
                            command=[],
                        ),
                        require_command=True,
                    )

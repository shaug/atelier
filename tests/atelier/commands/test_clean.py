import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import atelier.commands.clean as clean_cmd
import atelier.paths as paths
import atelier.workspace as workspace
from tests.atelier.helpers import (
    NORMALIZED_ORIGIN,
    RAW_ORIGIN,
    enlistment_path_for,
    make_fake_git,
    workspace_id_for,
    write_project_config,
    write_workspace_config,
)


class TestCleanWorkspaces:
    def test_clean_default_deletes_finalized_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_project_config(project_dir, enlistment_path)
            complete_branch = "scott/complete"
            incomplete_branch = "scott/incomplete"
            complete_dir = paths.workspace_dir_for_branch(
                project_dir,
                complete_branch,
                workspace_id_for(enlistment_path, complete_branch),
            )
            incomplete_dir = paths.workspace_dir_for_branch(
                project_dir,
                incomplete_branch,
                workspace_id_for(enlistment_path, incomplete_branch),
            )
            (complete_dir / "repo").mkdir(parents=True)
            (incomplete_dir / "repo").mkdir(parents=True)
            write_workspace_config(complete_dir, complete_branch, enlistment_path)
            write_workspace_config(incomplete_dir, incomplete_branch, enlistment_path)

            repo_complete = complete_dir / "repo"
            repo_incomplete = incomplete_dir / "repo"
            fake_run = make_fake_git(
                branches={repo_complete: "scott/complete", repo_incomplete: "main"},
                statuses={repo_complete: " M file.txt\n", repo_incomplete: ""},
                remotes={
                    (repo_complete, "scott/complete"): "",
                    (
                        repo_incomplete,
                        "scott/incomplete",
                    ): "abc\trefs/heads/scott/incomplete\n",
                },
                tags={
                    repo_complete: {workspace.finalization_tag_name(complete_branch)}
                },
            )

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                responses = iter(["y", "y"])
                with (
                    patch("atelier.exec.subprocess.run", fake_run),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                    patch("builtins.input", lambda _: next(responses)),
                ):
                    clean_cmd.clean_workspaces(
                        SimpleNamespace(
                            all=False,
                            force=False,
                            no_branch=False,
                            workspace_names=[],
                        )
                    )
                assert not complete_dir.exists()
                assert incomplete_dir.exists()
            finally:
                os.chdir(original_cwd)

    def test_clean_default_deletes_finalized_when_tag_in_main_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_project_config(project_dir, enlistment_path)
            complete_branch = "scott/complete"
            incomplete_branch = "scott/incomplete"
            complete_dir = paths.workspace_dir_for_branch(
                project_dir,
                complete_branch,
                workspace_id_for(enlistment_path, complete_branch),
            )
            incomplete_dir = paths.workspace_dir_for_branch(
                project_dir,
                incomplete_branch,
                workspace_id_for(enlistment_path, incomplete_branch),
            )
            (complete_dir / "repo").mkdir(parents=True)
            (incomplete_dir / "repo").mkdir(parents=True)
            write_workspace_config(complete_dir, complete_branch, enlistment_path)
            write_workspace_config(incomplete_dir, incomplete_branch, enlistment_path)

            repo_complete = complete_dir / "repo"
            repo_incomplete = incomplete_dir / "repo"
            fake_run = make_fake_git(
                branches={repo_complete: "scott/complete", repo_incomplete: "main"},
                statuses={repo_complete: " M file.txt\n", repo_incomplete: ""},
                remotes={
                    (repo_complete, "scott/complete"): "",
                    (
                        repo_incomplete,
                        "scott/incomplete",
                    ): "abc\trefs/heads/scott/incomplete\n",
                },
                tags={root: {workspace.finalization_tag_name(complete_branch)}},
            )

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                responses = iter(["y"])
                with (
                    patch("atelier.exec.subprocess.run", fake_run),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                    patch("builtins.input", lambda _: next(responses)),
                ):
                    clean_cmd.clean_workspaces(
                        SimpleNamespace(
                            all=False,
                            force=False,
                            no_branch=False,
                            workspace_names=[],
                        )
                    )
                assert not complete_dir.exists()
                assert incomplete_dir.exists()
            finally:
                os.chdir(original_cwd)

    def test_clean_all_flag_deletes_all(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_project_config(project_dir, enlistment_path)
            alpha_branch = "scott/alpha"
            beta_branch = "scott/beta"
            alpha_dir = paths.workspace_dir_for_branch(
                project_dir,
                alpha_branch,
                workspace_id_for(enlistment_path, alpha_branch),
            )
            beta_dir = paths.workspace_dir_for_branch(
                project_dir,
                beta_branch,
                workspace_id_for(enlistment_path, beta_branch),
            )
            (alpha_dir / "repo").mkdir(parents=True)
            (beta_dir / "repo").mkdir(parents=True)
            write_workspace_config(alpha_dir, alpha_branch, enlistment_path)
            write_workspace_config(beta_dir, beta_branch, enlistment_path)

            repo_alpha = alpha_dir / "repo"
            repo_beta = beta_dir / "repo"
            fake_run = make_fake_git(
                branches={repo_alpha: "scott/alpha", repo_beta: "main"},
                statuses={repo_alpha: " M file.txt\n", repo_beta: ""},
                remotes={
                    (repo_alpha, "scott/alpha"): "",
                    (repo_beta, "scott/beta"): "abc\trefs/heads/scott/beta\n",
                },
            )

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                with (
                    patch("atelier.exec.subprocess.run", fake_run),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                    patch("builtins.input", lambda _: "y"),
                ):
                    clean_cmd.clean_workspaces(
                        SimpleNamespace(
                            all=True,
                            force=False,
                            no_branch=False,
                            workspace_names=[],
                        )
                    )
                assert not alpha_dir.exists()
                assert not beta_dir.exists()
            finally:
                os.chdir(original_cwd)

    def test_clean_all_force_confirms_remote_delete_for_unfinalized(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_project_config(project_dir, enlistment_path)
            branch = "scott/alpha"
            workspace_dir = paths.workspace_dir_for_branch(
                project_dir,
                branch,
                workspace_id_for(enlistment_path, branch),
            )
            (workspace_dir / "repo").mkdir(parents=True)
            write_workspace_config(workspace_dir, branch, enlistment_path)

            prompts: list[str] = []
            run_calls: list[list[str]] = []

            def fake_confirm(prompt: str, default: bool = False) -> bool:
                prompts.append(prompt)
                return False

            def fake_try_run(cmd: list[str], cwd: Path | None = None):
                run_calls.append(cmd)
                return SimpleNamespace(returncode=0)

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                with (
                    patch("atelier.commands.clean.confirm", side_effect=fake_confirm),
                    patch("atelier.exec.try_run_command", side_effect=fake_try_run),
                    patch("atelier.git.git_current_branch", return_value=None),
                    patch("atelier.git.git_is_repo", return_value=True),
                    patch("atelier.git.git_ref_exists", return_value=False),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.git.git_has_remote_branch", return_value=True),
                    patch("atelier.git.git_tag_exists", return_value=False),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    clean_cmd.clean_workspaces(
                        SimpleNamespace(
                            all=True,
                            force=True,
                            no_branch=False,
                            workspace_names=[],
                        )
                    )
                assert not workspace_dir.exists()
                assert any("remote branch" in prompt for prompt in prompts)
                assert run_calls == []
            finally:
                os.chdir(original_cwd)

    def test_clean_all_force_deletes_remote_when_confirmed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_project_config(project_dir, enlistment_path)
            branch = "scott/beta"
            workspace_dir = paths.workspace_dir_for_branch(
                project_dir,
                branch,
                workspace_id_for(enlistment_path, branch),
            )
            (workspace_dir / "repo").mkdir(parents=True)
            write_workspace_config(workspace_dir, branch, enlistment_path)

            prompts: list[str] = []
            run_calls: list[list[str]] = []

            def fake_confirm(prompt: str, default: bool = False) -> bool:
                prompts.append(prompt)
                return True

            def fake_try_run(cmd: list[str], cwd: Path | None = None):
                run_calls.append(cmd)
                return SimpleNamespace(returncode=0)

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                with (
                    patch("atelier.commands.clean.confirm", side_effect=fake_confirm),
                    patch("atelier.exec.try_run_command", side_effect=fake_try_run),
                    patch("atelier.git.git_current_branch", return_value=None),
                    patch("atelier.git.git_is_repo", return_value=True),
                    patch("atelier.git.git_ref_exists", return_value=False),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.git.git_has_remote_branch", return_value=True),
                    patch("atelier.git.git_tag_exists", return_value=False),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    clean_cmd.clean_workspaces(
                        SimpleNamespace(
                            all=True,
                            force=True,
                            no_branch=False,
                            workspace_names=[],
                        )
                    )
                assert not workspace_dir.exists()
                assert any("remote branch" in prompt for prompt in prompts)
                assert any(
                    cmd[:5]
                    == ["git", "-C", str(workspace_dir / "repo"), "push", "origin"]
                    and "--delete" in cmd
                    for cmd in run_calls
                )
            finally:
                os.chdir(original_cwd)

    def test_clean_orphans_removes_missing_config_or_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_project_config(project_dir, enlistment_path)

            workspaces_root = project_dir / "workspaces"
            missing_config_dir = workspaces_root / "missing-config"
            (missing_config_dir / "repo").mkdir(parents=True)
            missing_repo_dir = workspaces_root / "missing-repo"
            missing_repo_dir.mkdir(parents=True)
            write_workspace_config(missing_repo_dir, "scott/missing", enlistment_path)
            ok_dir = workspaces_root / "ok"
            (ok_dir / "repo").mkdir(parents=True)
            write_workspace_config(ok_dir, "scott/ok", enlistment_path)

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                responses = iter(["y", "y"])
                with (
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                    patch("builtins.input", lambda _: next(responses)),
                ):
                    clean_cmd.clean_workspaces(
                        SimpleNamespace(
                            all=False,
                            force=False,
                            orphans=True,
                            no_branch=False,
                            workspace_names=[],
                        )
                    )
                assert not missing_config_dir.exists()
                assert not missing_repo_dir.exists()
                assert ok_dir.exists()
            finally:
                os.chdir(original_cwd)

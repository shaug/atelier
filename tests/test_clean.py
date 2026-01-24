import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from typer.testing import CliRunner  # noqa: E402

import atelier.cli as cli  # noqa: E402
import atelier.commands.clean as clean_cmd  # noqa: E402
import atelier.paths as paths  # noqa: E402
import atelier.workspace as workspace  # noqa: E402
from tests.test_cli import (  # noqa: E402
    NORMALIZED_ORIGIN,
    RAW_ORIGIN,
    BaseAtelierTestCase,
    enlistment_path_for,
    make_fake_git,
    workspace_id_for,
    write_project_config,
    write_workspace_config,
)


class TestCleanWorkspaces(BaseAtelierTestCase):
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
                self.assertFalse(complete_dir.exists())
                self.assertTrue(incomplete_dir.exists())
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
                self.assertFalse(complete_dir.exists())
                self.assertTrue(incomplete_dir.exists())
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
                            all=True,
                            force=False,
                            no_branch=False,
                            workspace_names=[],
                        )
                    )
                self.assertFalse(alpha_dir.exists())
                self.assertFalse(beta_dir.exists())
            finally:
                os.chdir(original_cwd)

    def test_clean_force_skips_prompt(self) -> None:
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
            alpha_dir = paths.workspace_dir_for_branch(
                project_dir,
                alpha_branch,
                workspace_id_for(enlistment_path, alpha_branch),
            )
            (alpha_dir / "repo").mkdir(parents=True)
            write_workspace_config(alpha_dir, alpha_branch, enlistment_path)

            repo_alpha = alpha_dir / "repo"
            fake_run = make_fake_git(
                branches={repo_alpha: "scott/alpha"},
                statuses={repo_alpha: ""},
                remotes={(repo_alpha, "scott/alpha"): "abc\trefs/heads/scott/alpha\n"},
            )

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                with (
                    patch("atelier.exec.subprocess.run", fake_run),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                    patch(
                        "builtins.input",
                        side_effect=AssertionError("prompted unexpectedly"),
                    ),
                ):
                    clean_cmd.clean_workspaces(
                        SimpleNamespace(
                            all=True,
                            force=True,
                            no_branch=False,
                            workspace_names=[],
                        )
                    )
                self.assertFalse(alpha_dir.exists())
            finally:
                os.chdir(original_cwd)

    def test_clean_positional_targets_only(self) -> None:
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
                branches={repo_alpha: "scott/alpha", repo_beta: "scott/beta"},
                statuses={repo_alpha: "", repo_beta: ""},
                remotes={
                    (repo_alpha, "scott/alpha"): "abc\trefs/heads/scott/alpha\n",
                    (repo_beta, "scott/beta"): "abc\trefs/heads/scott/beta\n",
                },
            )

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                with (
                    patch("atelier.exec.subprocess.run", fake_run),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    clean_cmd.clean_workspaces(
                        SimpleNamespace(
                            all=False,
                            force=True,
                            no_branch=False,
                            workspace_names=[beta_branch, "missing"],
                        )
                    )
                self.assertTrue(alpha_dir.exists())
                self.assertFalse(beta_dir.exists())
            finally:
                os.chdir(original_cwd)

    def test_clean_handles_missing_workspace_config(self) -> None:
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
            (workspace_dir / "repo").mkdir(parents=True, exist_ok=True)

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                with (
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    clean_cmd.clean_workspaces(
                        SimpleNamespace(
                            all=False,
                            force=True,
                            no_branch=True,
                            workspace_names=[branch],
                        )
                    )
                self.assertFalse(workspace_dir.exists())
            finally:
                os.chdir(original_cwd)

    def test_clean_skips_branch_deletion_with_no_branch(self) -> None:
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
            alpha_dir = paths.workspace_dir_for_branch(
                project_dir,
                alpha_branch,
                workspace_id_for(enlistment_path, alpha_branch),
            )
            (alpha_dir / "repo").mkdir(parents=True)
            write_workspace_config(alpha_dir, alpha_branch, enlistment_path)

            repo_alpha = alpha_dir / "repo"
            fake_run = make_fake_git(
                branches={repo_alpha: "scott/alpha"},
                statuses={repo_alpha: ""},
                remotes={(repo_alpha, "scott/alpha"): "abc\trefs/heads/scott/alpha\n"},
            )

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                with (
                    patch("atelier.exec.subprocess.run", fake_run),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                    patch(
                        "atelier.commands.clean.delete_workspace_branch",
                        side_effect=AssertionError("deleted branch unexpectedly"),
                    ),
                ):
                    clean_cmd.clean_workspaces(
                        SimpleNamespace(
                            all=True,
                            force=True,
                            no_branch=True,
                            workspace_names=[],
                        )
                    )
                self.assertFalse(alpha_dir.exists())
            finally:
                os.chdir(original_cwd)

    def test_clean_deletes_branch_by_default(self) -> None:
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
            alpha_dir = paths.workspace_dir_for_branch(
                project_dir,
                alpha_branch,
                workspace_id_for(enlistment_path, alpha_branch),
            )
            (alpha_dir / "repo").mkdir(parents=True)
            write_workspace_config(alpha_dir, alpha_branch, enlistment_path)

            repo_alpha = alpha_dir / "repo"
            fake_run = make_fake_git(
                branches={repo_alpha: "scott/alpha"},
                statuses={repo_alpha: ""},
                remotes={(repo_alpha, "scott/alpha"): "abc\trefs/heads/scott/alpha\n"},
            )
            deleted: list[tuple[str, str]] = []

            def fake_delete(repo_dir: Path, branch: str, default_branch: str) -> None:
                deleted.append((repo_dir.name, branch))

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                with (
                    patch("atelier.exec.subprocess.run", fake_run),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                    patch(
                        "atelier.commands.clean.delete_workspace_branch", fake_delete
                    ),
                ):
                    clean_cmd.clean_workspaces(
                        SimpleNamespace(
                            all=True,
                            force=True,
                            no_branch=False,
                            workspace_names=[],
                        )
                    )
                self.assertEqual(deleted, [("repo", "scott/alpha")])
            finally:
                os.chdir(original_cwd)


class TestCleanFlags(BaseAtelierTestCase):
    def test_clean_short_flags(self) -> None:
        captured: dict[str, object] = {}

        def fake_clean(args: SimpleNamespace) -> None:
            captured["all"] = args.all
            captured["force"] = args.force

        runner = CliRunner()
        with patch("atelier.commands.clean.clean_workspaces", fake_clean):
            result = runner.invoke(cli.app, ["clean", "-A", "-F"])

        self.assertEqual(result.exit_code, 0)

        self.assertTrue(captured["all"])
        self.assertTrue(captured["force"])

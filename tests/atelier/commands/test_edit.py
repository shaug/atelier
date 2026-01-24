import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import atelier.commands.edit as edit_cmd
import atelier.paths as paths
from tests.atelier.helpers import (
    NORMALIZED_ORIGIN,
    RAW_ORIGIN,
    BaseAtelierTestCase,
    enlistment_path_for,
    workspace_id_for,
    write_open_config,
    write_workspace_config,
)


class TestEditCommand(BaseAtelierTestCase):
    def test_edit_project_creates_project_md(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_open_config(project_dir, enlistment_path)

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                calls: list[list[str]] = []

                def fake_run(cmd: list[str], cwd: Path | None = None) -> None:
                    calls.append(cmd)

                with (
                    patch("atelier.exec.run_command", fake_run),
                    patch(
                        "atelier.templates.project_md_template",
                        return_value="project stub\n",
                    ),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    edit_cmd.edit_files(
                        SimpleNamespace(workspace_name=None, project=True)
                    )

                project_path = project_dir / "PROJECT.md"
                self.assertTrue(project_path.exists())
                self.assertEqual(
                    project_path.read_text(encoding="utf-8"), "project stub\n"
                )
                self.assertTrue(calls)
                self.assertIn(str(project_path), calls[0])
            finally:
                os.chdir(original_cwd)

    def test_edit_workspace_creates_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_open_config(project_dir, enlistment_path)
            branch = "scott/feat-demo"
            workspace_dir = paths.workspace_dir_for_branch(
                project_dir,
                branch,
                workspace_id_for(enlistment_path, branch),
            )
            workspace_dir.mkdir(parents=True)
            write_workspace_config(workspace_dir, branch, enlistment_path)

            template_path = project_dir / "templates" / "SUCCESS.md"
            template_path.parent.mkdir(parents=True, exist_ok=True)
            template_path.write_text("workspace success\n", encoding="utf-8")

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                calls: list[list[str]] = []

                def fake_run(cmd: list[str], cwd: Path | None = None) -> None:
                    calls.append(cmd)

                with (
                    patch("atelier.exec.run_command", fake_run),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    edit_cmd.edit_files(
                        SimpleNamespace(workspace_name="feat-demo", project=False)
                    )

                success_path = workspace_dir / "SUCCESS.md"
                self.assertTrue(success_path.exists())
                self.assertEqual(
                    success_path.read_text(encoding="utf-8"), "workspace success\n"
                )
                self.assertTrue(calls)
                self.assertIn(str(success_path), calls[0])
            finally:
                os.chdir(original_cwd)

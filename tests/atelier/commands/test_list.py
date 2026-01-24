import io
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import atelier.commands.list as list_cmd
import atelier.paths as paths
from tests.atelier.helpers import (
    NORMALIZED_ORIGIN,
    RAW_ORIGIN,
    enlistment_path_for,
    workspace_id_for,
    write_project_config,
    write_workspace_config,
)


class TestListWorkspaces:
    def test_list_default_only_names(self) -> None:
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
            alpha_dir.mkdir(parents=True)
            beta_dir.mkdir(parents=True)
            write_workspace_config(alpha_dir, alpha_branch, enlistment_path)
            write_workspace_config(beta_dir, beta_branch, enlistment_path)

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                buffer = io.StringIO()
                with (
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                    patch("sys.stdout", buffer),
                ):
                    list_cmd.list_workspaces(SimpleNamespace())
                lines = [
                    line.strip() for line in buffer.getvalue().splitlines() if line
                ]
                assert lines == [alpha_branch, beta_branch]
            finally:
                os.chdir(original_cwd)

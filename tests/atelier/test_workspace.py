import tempfile
from pathlib import Path
from unittest.mock import patch

import atelier.paths as paths
import atelier.workspace as workspace
from tests.atelier.helpers import enlistment_path_for, write_workspace_config


def test_resolve_workspace_target_prefers_exact_workspace_before_prefix() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        enlistment_path = enlistment_path_for(root)
        project_dir = root / "project"
        project_dir.mkdir()

        name = "team/feature"
        branch_prefix = "scott/"
        exact_branch = name
        prefixed_branch = f"{branch_prefix}{name}"

        exact_dir = paths.workspace_dir_for_branch(
            project_dir,
            exact_branch,
            workspace.workspace_identifier(enlistment_path, exact_branch),
        )
        prefixed_dir = paths.workspace_dir_for_branch(
            project_dir,
            prefixed_branch,
            workspace.workspace_identifier(enlistment_path, prefixed_branch),
        )
        exact_dir.mkdir(parents=True)
        prefixed_dir.mkdir(parents=True)
        write_workspace_config(exact_dir, exact_branch, enlistment_path)
        write_workspace_config(prefixed_dir, prefixed_branch, enlistment_path)

        with patch("atelier.workspace._branch_exists", return_value=False):
            branch, workspace_dir, exists = workspace.resolve_workspace_target(
                project_dir,
                enlistment_path,
                name,
                branch_prefix,
                False,
            )

        assert branch == exact_branch
        assert workspace_dir == exact_dir
        assert exists is True

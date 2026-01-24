import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import atelier.commands.work as work_cmd
import atelier.paths as paths
from tests.atelier.helpers import (
    NORMALIZED_ORIGIN,
    enlistment_path_for,
    workspace_id_for,
    write_open_config,
    write_workspace_config,
)


class TestWorkCommand:
    def test_work_opens_repo_with_work_editor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_open_config(
                project_dir,
                enlistment_path,
                editor={"edit": ["true"], "work": ["code"]},
            )

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

            def fake_detached(cmd: list[str], cwd: Path | None = None) -> None:
                captured["cmd"] = cmd
                captured["cwd"] = cwd

            with (
                patch(
                    "atelier.commands.work.git.resolve_repo_enlistment",
                    return_value=(None, enlistment_path, None, NORMALIZED_ORIGIN),
                ),
                patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                patch("atelier.commands.work.git.git_is_repo", return_value=True),
                patch("atelier.commands.work.exec.run_command_detached", fake_detached),
            ):
                work_cmd.open_workspace_repo(
                    SimpleNamespace(workspace_name=workspace_branch)
                )

            assert captured["cmd"] == ["code", str(repo_dir)]
            assert captured["cwd"] == workspace_dir

import io
import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import atelier.paths as paths
from atelier.commands import describe as describe_cmd
from tests.atelier.helpers import (
    NORMALIZED_ORIGIN,
    RAW_ORIGIN,
    enlistment_path_for,
    workspace_id_for,
    write_project_config,
    write_workspace_config,
)


class TestDescribeProject:
    def test_project_json_sorted_and_filtered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_project_config(project_dir, enlistment_path)

            alpha_path = project_dir / "workspaces" / "alpha"
            beta_path = project_dir / "workspaces" / "beta"
            workspaces = [
                {
                    "name": "scott/beta",
                    "branch": "scott/beta",
                    "path": beta_path,
                    "repo_dir": beta_path / "repo",
                    "checked_out": False,
                    "clean": None,
                    "pushed": True,
                    "finalized": True,
                },
                {
                    "name": "scott/alpha",
                    "branch": "scott/alpha",
                    "path": alpha_path,
                    "repo_dir": alpha_path / "repo",
                    "checked_out": True,
                    "clean": True,
                    "pushed": False,
                    "finalized": False,
                },
            ]

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                with (
                    patch(
                        "atelier.paths.atelier_data_dir",
                        return_value=data_dir,
                    ),
                    patch(
                        "atelier.commands.describe.git.resolve_repo_enlistment",
                        return_value=(
                            root,
                            enlistment_path,
                            RAW_ORIGIN,
                            NORMALIZED_ORIGIN,
                        ),
                    ),
                    patch(
                        "atelier.commands.describe.git.git_is_repo",
                        return_value=True,
                    ),
                    patch(
                        "atelier.commands.describe.git.git_default_branch",
                        return_value="main",
                    ),
                    patch(
                        "atelier.commands.describe.workspace.collect_workspaces",
                        return_value=workspaces,
                    ),
                ):
                    buffer = io.StringIO()
                    with patch("sys.stdout", buffer):
                        describe_cmd(
                            SimpleNamespace(
                                workspace_name=None,
                                finalized=False,
                                no_finalized=False,
                                format="json",
                            )
                        )
                    payload = json.loads(buffer.getvalue())
                    assert [item["name"] for item in payload["workspaces"]] == [
                        "scott/alpha",
                        "scott/beta",
                    ]

                    buffer = io.StringIO()
                    with patch("sys.stdout", buffer):
                        describe_cmd(
                            SimpleNamespace(
                                workspace_name=None,
                                finalized=True,
                                no_finalized=False,
                                format="json",
                            )
                        )
                    payload = json.loads(buffer.getvalue())
                    assert [item["name"] for item in payload["workspaces"]] == [
                        "scott/beta"
                    ]
            finally:
                os.chdir(original_cwd)


class TestDescribeWorkspace:
    def test_workspace_json_detail(self) -> None:
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
            repo_dir = workspace_dir / "repo"
            repo_dir.mkdir(parents=True)
            write_workspace_config(workspace_dir, branch, enlistment_path)

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                buffer = io.StringIO()
                with (
                    patch(
                        "atelier.paths.atelier_data_dir",
                        return_value=data_dir,
                    ),
                    patch(
                        "atelier.commands.describe.git.resolve_repo_enlistment",
                        return_value=(
                            root,
                            enlistment_path,
                            RAW_ORIGIN,
                            NORMALIZED_ORIGIN,
                        ),
                    ),
                    patch(
                        "atelier.commands.describe.git.git_is_repo",
                        return_value=True,
                    ),
                    patch(
                        "atelier.commands.describe.git.git_current_branch",
                        return_value=branch,
                    ),
                    patch(
                        "atelier.commands.describe.git.git_is_clean",
                        return_value=False,
                    ),
                    patch(
                        "atelier.commands.describe.git.git_has_remote_branch",
                        return_value=True,
                    ),
                    patch(
                        "atelier.commands.describe.git.git_tag_exists",
                        return_value=False,
                    ),
                    patch(
                        "atelier.commands.describe.git.git_default_branch",
                        return_value="main",
                    ),
                    patch(
                        "atelier.commands.describe.git.git_commits_ahead",
                        side_effect=[3, 1],
                    ),
                    patch(
                        "atelier.commands.describe.git.git_diff_stat",
                        return_value=[
                            " file.txt | 2 ++",
                            " 1 file changed, 2 insertions(+)",
                        ],
                    ),
                    patch(
                        "atelier.commands.describe.git.git_last_commit",
                        return_value={
                            "hash": "deadbeef",
                            "short_hash": "deadbeef",
                            "timestamp": 1700000000,
                            "author": "Test User",
                            "subject": "feat: add demo",
                        },
                    ),
                    patch("sys.stdout", buffer),
                ):
                    describe_cmd(
                        SimpleNamespace(
                            workspace_name=branch,
                            finalized=False,
                            no_finalized=False,
                            format="json",
                        )
                    )
                payload = json.loads(buffer.getvalue())
                workspace_payload = payload["workspace"]
                assert workspace_payload["branch"] == branch
                assert workspace_payload["checked_out"] is True
                assert workspace_payload["clean"] is False
                assert workspace_payload["pushed"] is True
                assert workspace_payload["finalized"] is False
                assert workspace_payload["mainline"]["ahead"] == 3
                assert workspace_payload["mainline"]["behind"] == 1
                assert workspace_payload["last_commit"]["subject"] == "feat: add demo"
            finally:
                os.chdir(original_cwd)

import io
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import atelier.commands.list as list_cmd
import atelier.config as config
from tests.atelier.helpers import (
    NORMALIZED_ORIGIN,
    RAW_ORIGIN,
)


class TestListWorkspaces:
    def test_list_default_only_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            repo_root = Path(tmp) / "repo"
            project_root.mkdir(parents=True, exist_ok=True)
            repo_root.mkdir(parents=True, exist_ok=True)
            config_payload = config.ProjectConfig.model_validate(
                {
                    "project": {
                        "enlistment": str(repo_root),
                        "origin": NORMALIZED_ORIGIN,
                        "repo_url": RAW_ORIGIN,
                    },
                    "branch": {"prefix": "scott/", "pr": True, "history": "manual"},
                }
            )
            issues = [
                {
                    "id": "epic-1",
                    "labels": ["at:epic"],
                    "status": "open",
                    "description": "workspace.root_branch: scott/alpha\n",
                },
                {
                    "id": "epic-2",
                    "labels": ["at:epic"],
                    "status": "ready",
                    "description": "workspace.root_branch: scott/beta\n",
                },
            ]

            buffer = io.StringIO()
            with (
                patch(
                    "atelier.commands.list.resolve_current_project_with_repo_root",
                    return_value=(project_root, config_payload, str(repo_root), repo_root),
                ),
                patch("atelier.commands.list.beads.run_bd_command"),
                patch("atelier.commands.list.beads.run_bd_json", return_value=issues),
                patch("sys.stdout", buffer),
            ):
                list_cmd.list_workspaces(SimpleNamespace())

            lines = [line.strip() for line in buffer.getvalue().splitlines() if line]
            assert lines == ["scott/alpha", "scott/beta"]

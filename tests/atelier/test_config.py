from types import SimpleNamespace
from pathlib import Path
import tempfile
from unittest.mock import patch

import atelier.config as config
import atelier.paths as paths


def test_build_project_config_sets_data_dir() -> None:
    args = SimpleNamespace(
        branch_prefix="",
        branch_pr="true",
        branch_history="merge",
        agent="codex",
        editor_edit="cat",
        editor_work="cat",
        ticket_provider="none",
        ticket_project=None,
        ticket_namespace=None,
    )
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp) / "data"
        with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
            with patch(
                "atelier.agents.available_agent_names", return_value=("codex",)
            ):
                payload = config.build_project_config(
                    {},
                    "/repo",
                    "github.com/org/repo",
                    "https://github.com/org/repo",
                    args,
                    allow_editor_empty=True,
                )
            expected = str(
                paths.project_dir_for_enlistment("/repo", "github.com/org/repo")
            )
    assert payload.atelier.data_dir == expected

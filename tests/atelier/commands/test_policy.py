import io
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import atelier.config as config
from atelier.commands import policy as policy_cmd
from tests.atelier.helpers import NORMALIZED_ORIGIN, DummyResult


def _project_config(repo_root: Path) -> config.ProjectConfig:
    return config.ProjectConfig.model_validate(
        {"project": {"enlistment": str(repo_root), "origin": NORMALIZED_ORIGIN}}
    )


def test_show_policy_prints_combined_policy() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        repo_root = root / "repo"
        project_root = root / "project"
        beads_root = root / ".beads"
        repo_root.mkdir(parents=True, exist_ok=True)
        project_root.mkdir(parents=True, exist_ok=True)

        planner_issue = {"id": "pol-1", "description": "planner rules"}
        worker_issue = {"id": "pol-2", "description": "worker rules"}
        project_config = _project_config(repo_root)

        def fake_list(
            role: str | None, *, beads_root: Path, cwd: Path
        ) -> list[dict[str, object]]:
            if role == "planner":
                return [planner_issue]
            if role == "worker":
                return [worker_issue]
            return []

        with (
            patch(
                "atelier.commands.policy.resolve_current_project_with_repo_root",
                return_value=(project_root, project_config, str(repo_root), repo_root),
            ),
            patch(
                "atelier.commands.policy.config.resolve_project_data_dir",
                return_value=project_root,
            ),
            patch(
                "atelier.commands.policy.config.resolve_beads_root",
                return_value=beads_root,
            ),
            patch(
                "atelier.commands.policy.beads.run_bd_command",
                return_value=DummyResult(),
            ),
            patch(
                "atelier.commands.policy.beads.list_policy_beads",
                side_effect=fake_list,
            ),
        ):
            buffer = io.StringIO()
            with patch("sys.stdout", buffer):
                policy_cmd.show_policy(SimpleNamespace(role=None))

        output = buffer.getvalue()
        assert "<!-- planner -->" in output
        assert "planner rules" in output
        assert "<!-- worker -->" in output
        assert "worker rules" in output


def test_show_policy_prints_missing_message_for_role() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        repo_root = root / "repo"
        project_root = root / "project"
        beads_root = root / ".beads"
        repo_root.mkdir(parents=True, exist_ok=True)
        project_root.mkdir(parents=True, exist_ok=True)
        project_config = _project_config(repo_root)

        with (
            patch(
                "atelier.commands.policy.resolve_current_project_with_repo_root",
                return_value=(project_root, project_config, str(repo_root), repo_root),
            ),
            patch(
                "atelier.commands.policy.config.resolve_project_data_dir",
                return_value=project_root,
            ),
            patch(
                "atelier.commands.policy.config.resolve_beads_root",
                return_value=beads_root,
            ),
            patch(
                "atelier.commands.policy.beads.run_bd_command",
                return_value=DummyResult(),
            ),
            patch(
                "atelier.commands.policy.beads.list_policy_beads",
                return_value=[],
            ),
        ):
            buffer = io.StringIO()
            with patch("sys.stdout", buffer):
                policy_cmd.show_policy(SimpleNamespace(role="worker"))

        assert "No worker policy set." in buffer.getvalue()

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import atelier.commands.hook as hook_cmd
from atelier.config import ProjectConfig


def _fake_project_payload() -> ProjectConfig:
    return ProjectConfig()


def test_hook_precompact_runs_prime_and_planner_sync(tmp_path: Path) -> None:
    with (
        patch(
            "atelier.commands.hook.resolve_current_project_with_repo_root",
            return_value=(
                Path("/project"),
                _fake_project_payload(),
                "/repo",
                Path("/repo"),
            ),
        ),
        patch("atelier.commands.hook.config.resolve_project_data_dir", return_value=tmp_path),
        patch("atelier.commands.hook.config.resolve_beads_root", return_value=Path("/beads")),
        patch("atelier.commands.hook.config.resolve_git_path", return_value="git"),
        patch("atelier.commands.hook.hooks.parse_hook_event", return_value="pre-compact"),
        patch("atelier.commands.hook.beads.run_bd_command") as run_bd_command,
        patch("atelier.commands.hook.planner_sync.maybe_sync_from_hook") as maybe_sync,
    ):
        hook_cmd.run_hook(SimpleNamespace(event="pre-compact"))

    run_bd_command.assert_called_once_with(["prime"], beads_root=Path("/beads"), cwd=Path("/repo"))
    maybe_sync.assert_called_once_with(
        event="pre-compact",
        project_data_dir=tmp_path,
        repo_root=Path("/repo"),
        beads_root=Path("/beads"),
        git_path="git",
        emit=hook_cmd.say,
    )


def test_hook_commit_msg_validates_without_project_context(tmp_path: Path) -> None:
    message_file = tmp_path / "COMMIT_EDITMSG"
    message_file.write_text("feat(worker): bootstrap hooks\n", encoding="utf-8")

    with (
        patch("atelier.commands.hook.hooks.parse_hook_event", return_value="commit-msg"),
        patch("atelier.commands.hook.resolve_current_project_with_repo_root") as resolve_project,
    ):
        hook_cmd.run_hook(SimpleNamespace(event="commit-msg", message_file=message_file))

    resolve_project.assert_not_called()

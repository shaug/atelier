from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import atelier.commands.gc as gc_cmd
import atelier.config as config
from atelier.messages import render_message


def test_gc_closes_expired_channel_messages() -> None:
    project_root = Path("/project")
    repo_root = Path("/repo")
    project_config = config.ProjectConfig()
    description = render_message(
        {"channel": "ops", "retention_days": 1},
        "hello",
    )
    issue = {
        "id": "msg-1",
        "description": description,
        "created_at": "2026-01-01T00:00:00Z",
    }

    calls: list[list[str]] = []

    def fake_run_bd_json(
        args: list[str], *, beads_root: Path, cwd: Path
    ) -> list[dict[str, object]]:
        if args[:3] == ["list", "--label", "at:message"]:
            return [issue]
        return []

    def fake_run_bd_command(
        args: list[str], *, beads_root: Path, cwd: Path, allow_failure: bool = False
    ) -> object:
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    with (
        patch(
            "atelier.commands.gc.resolve_current_project_with_repo_root",
            return_value=(project_root, project_config, "/repo", repo_root),
        ),
        patch(
            "atelier.commands.gc.config.resolve_project_data_dir",
            return_value=Path("/data"),
        ),
        patch(
            "atelier.commands.gc.config.resolve_beads_root",
            return_value=Path("/beads"),
        ),
        patch("atelier.commands.gc.beads.run_bd_json", side_effect=fake_run_bd_json),
        patch(
            "atelier.commands.gc.beads.run_bd_command", side_effect=fake_run_bd_command
        ),
        patch("atelier.commands.gc.say"),
    ):
        gc_cmd.gc(SimpleNamespace(stale_hours=24.0, dry_run=False, yes=True))

    assert any(cmd[:2] == ["close", "msg-1"] for cmd in calls)

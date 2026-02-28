from types import SimpleNamespace
from unittest.mock import patch

from typer.testing import CliRunner

import atelier.cli as cli


def test_plan_passes_new_session_flag_to_command() -> None:
    captured: dict[str, object] = {}

    def fake_run_planner(args: SimpleNamespace) -> None:
        captured["epic_id"] = args.epic_id
        captured["reconcile"] = args.reconcile
        captured["yes"] = args.yes
        captured["new_session"] = args.new_session
        captured["trace"] = args.trace

    runner = CliRunner()
    with patch("atelier.commands.plan.run_planner", fake_run_planner):
        result = runner.invoke(
            cli.app,
            [
                "plan",
                "--epic-id",
                "at-epic",
                "--reconcile",
                "--yes",
                "--new-session",
                "--trace",
            ],
        )

    assert result.exit_code == 0
    assert captured == {
        "epic_id": "at-epic",
        "reconcile": True,
        "yes": True,
        "new_session": True,
        "trace": True,
    }

from types import SimpleNamespace
from unittest.mock import patch

from typer.testing import CliRunner

import atelier.cli as cli


def test_work_passes_yolo_flag_to_command() -> None:
    captured: dict[str, object] = {}

    def fake_start_worker(args: SimpleNamespace) -> None:
        captured["epic_id"] = args.epic_id
        captured["mode"] = args.mode
        captured["select"] = args.select
        captured["run_mode"] = args.run_mode
        captured["restart_on_update"] = args.restart_on_update
        captured["yes"] = args.yes
        captured["reconcile"] = args.reconcile
        captured["yolo"] = args.yolo

    runner = CliRunner()
    with patch("atelier.commands.work.start_worker", fake_start_worker):
        result = runner.invoke(
            cli.app,
            [
                "work",
                "at-epic",
                "--mode",
                "auto",
                "--select",
                "first-eligible",
                "--run-mode",
                "once",
                "--restart-on-update",
                "--yes",
                "--reconcile",
                "--yolo",
            ],
        )

    assert result.exit_code == 0
    assert captured == {
        "epic_id": "at-epic",
        "mode": "auto",
        "select": "first-eligible",
        "run_mode": "once",
        "restart_on_update": True,
        "yes": True,
        "reconcile": True,
        "yolo": True,
    }

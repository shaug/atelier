from types import SimpleNamespace
from unittest.mock import patch

from typer.testing import CliRunner

import atelier.cli as cli


class TestRepairEventHistoryOverflowCommand:
    def test_repair_event_history_overflow_passes_options(self) -> None:
        captured: dict[str, object] = {}

        def fake_repair(args: SimpleNamespace) -> None:
            captured["issue_id"] = args.issue_id
            captured["format"] = args.format

        runner = CliRunner()
        with patch(
            "atelier.cli.repair_event_history_cmd.repair_event_history_overflow", fake_repair
        ):
            result = runner.invoke(
                cli.app,
                [
                    "repair-event-history-overflow",
                    "at-overflow",
                    "--format",
                    "json",
                ],
            )

        assert result.exit_code == 0
        assert captured["issue_id"] == "at-overflow"
        assert captured["format"] == "json"

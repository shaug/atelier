from types import SimpleNamespace
from unittest.mock import patch

from typer.testing import CliRunner

import atelier.cli as cli


class TestOpenDeprecatedAlias:
    def test_open_forwards_worker_args(self) -> None:
        captured: dict[str, object] = {}

        def fake_start(args: SimpleNamespace) -> None:
            captured["epic_id"] = args.epic_id
            captured["mode"] = args.mode

        runner = CliRunner()
        with patch("atelier.commands.work.start_worker", fake_start):
            result = runner.invoke(cli.app, ["open", "at-epic123", "--mode", "auto"])

        assert result.exit_code == 0
        assert captured == {"epic_id": "at-epic123", "mode": "auto"}

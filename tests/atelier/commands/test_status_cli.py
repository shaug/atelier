from types import SimpleNamespace
from unittest.mock import patch

from typer.testing import CliRunner

import atelier.cli as cli


class TestStatusCommand:
    def test_status_passes_options(self) -> None:
        captured: dict[str, object] = {}

        def fake_status(args: SimpleNamespace) -> None:
            captured["format"] = args.format

        runner = CliRunner()
        with patch("atelier.cli.status_cmd", fake_status):
            result = runner.invoke(cli.app, ["status", "--format", "json"])

        assert result.exit_code == 0
        assert captured["format"] == "json"

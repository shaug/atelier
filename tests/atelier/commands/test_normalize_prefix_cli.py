from types import SimpleNamespace
from unittest.mock import patch

from typer.testing import CliRunner

import atelier.cli as cli


class TestNormalizePrefixCommand:
    def test_normalize_prefix_passes_options(self) -> None:
        captured: dict[str, object] = {}

        def fake_normalize_prefix(args: SimpleNamespace) -> None:
            captured["format"] = args.format
            captured["apply"] = args.apply
            captured["force"] = args.force

        runner = CliRunner()
        with patch("atelier.cli.normalize_prefix_cmd", fake_normalize_prefix):
            result = runner.invoke(
                cli.app,
                ["normalize-prefix", "--format", "json", "--apply", "--force"],
            )

        assert result.exit_code == 0
        assert captured["format"] == "json"
        assert captured["apply"] is True
        assert captured["force"] is True

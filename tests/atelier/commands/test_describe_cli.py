from types import SimpleNamespace
from unittest.mock import patch

from typer.testing import CliRunner

import atelier.cli as cli


class TestDescribeCommand:
    def test_describe_passes_options(self) -> None:
        captured: dict[str, object] = {}

        def fake_describe(args: SimpleNamespace) -> None:
            captured["workspace_name"] = args.workspace_name
            captured["finalized"] = args.finalized
            captured["no_finalized"] = args.no_finalized
            captured["format"] = args.format

        runner = CliRunner()
        with patch("atelier.cli.describe_cmd", fake_describe):
            result = runner.invoke(
                cli.app,
                [
                    "describe",
                    "feat-demo",
                    "--finalized",
                    "--no-finalized",
                    "--format",
                    "json",
                ],
            )

        assert result.exit_code == 0
        assert captured["workspace_name"] == "feat-demo"
        assert captured["finalized"] is True
        assert captured["no_finalized"] is True
        assert captured["format"] == "json"

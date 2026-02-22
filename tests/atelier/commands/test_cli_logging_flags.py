import re
from unittest.mock import patch

from typer.testing import CliRunner

import atelier.cli as cli

ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _strip_ansi(output: str) -> str:
    return ANSI_ESCAPE_RE.sub("", output)


def test_global_log_level_flag_sets_runtime_level() -> None:
    runner = CliRunner()
    with (
        patch("atelier.cli.status_cmd", lambda _args: None),
        patch("atelier.cli.atelier_log.set_level") as mock_set_level,
    ):
        result = runner.invoke(cli.app, ["--log-level", "debug", "status"])

    assert result.exit_code == 0
    mock_set_level.assert_called_once_with("debug")


def test_global_log_level_rejects_unknown_values() -> None:
    runner = CliRunner()
    result = runner.invoke(cli.app, ["--log-level", "loud", "status"], color=False)
    clean_output = _strip_ansi(result.output)

    assert result.exit_code != 0
    assert "--log-level" in clean_output
    assert "expected one of" in clean_output.lower()


def test_no_color_flag_disables_colorized_output() -> None:
    runner = CliRunner()
    with (
        patch("atelier.cli.status_cmd", lambda _args: None),
        patch("atelier.cli.atelier_log.set_no_color") as mock_set_no_color,
    ):
        result = runner.invoke(cli.app, ["--no-color", "status"])

    assert result.exit_code == 0
    mock_set_no_color.assert_called_once_with(True)

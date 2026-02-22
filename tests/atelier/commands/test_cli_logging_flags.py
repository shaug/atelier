from unittest.mock import patch

from typer.testing import CliRunner

import atelier.cli as cli


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
    result = runner.invoke(cli.app, ["--log-level", "loud", "status"])

    assert result.exit_code != 0
    assert "Invalid value for --log-level" in result.output


def test_no_color_flag_disables_colorized_output() -> None:
    runner = CliRunner()
    with (
        patch("atelier.cli.status_cmd", lambda _args: None),
        patch("atelier.cli.atelier_log.set_no_color") as mock_set_no_color,
    ):
        result = runner.invoke(cli.app, ["--no-color", "status"])

    assert result.exit_code == 0
    mock_set_no_color.assert_called_once_with(True)

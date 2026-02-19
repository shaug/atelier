from types import SimpleNamespace
from unittest.mock import patch

from typer.testing import CliRunner

import atelier.cli as cli


def test_policy_defaults_to_show() -> None:
    captured: dict[str, object] = {}

    def fake_show(args: SimpleNamespace) -> None:
        captured["role"] = args.role

    runner = CliRunner()
    with patch("atelier.commands.policy.show_policy", fake_show):
        result = runner.invoke(cli.app, ["policy"])

    assert result.exit_code == 0
    assert captured == {"role": None}


def test_policy_edit_flag_routes_to_edit_command() -> None:
    captured: dict[str, object] = {}

    def fake_edit(args: SimpleNamespace) -> None:
        captured["role"] = args.role

    runner = CliRunner()
    with patch("atelier.commands.policy.edit_policy", fake_edit):
        result = runner.invoke(cli.app, ["policy", "--role", "worker", "--edit"])

    assert result.exit_code == 0
    assert captured == {"role": "worker"}

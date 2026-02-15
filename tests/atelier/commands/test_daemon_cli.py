from types import SimpleNamespace
from unittest.mock import patch

from typer.testing import CliRunner

import atelier.cli as cli

runner = CliRunner()


def test_daemon_status_invokes_command() -> None:
    called = {}

    def fake_status(args: SimpleNamespace) -> None:
        called["ok"] = True

    with patch("atelier.cli.daemon_cmd.status_daemon", fake_status):
        result = runner.invoke(cli.app, ["daemon", "status"])

    assert result.exit_code == 0
    assert called.get("ok") is True


def test_daemon_start_invokes_command() -> None:
    called = {}

    def fake_start(args: SimpleNamespace) -> None:
        called["ok"] = True

    with patch("atelier.cli.daemon_cmd.start_daemon", fake_start):
        result = runner.invoke(cli.app, ["daemon", "start"])

    assert result.exit_code == 0
    assert called.get("ok") is True


def test_daemon_stop_invokes_command() -> None:
    called = {}

    def fake_stop(args: SimpleNamespace) -> None:
        called["ok"] = True

    with patch("atelier.cli.daemon_cmd.stop_daemon", fake_stop):
        result = runner.invoke(cli.app, ["daemon", "stop"])

    assert result.exit_code == 0
    assert called.get("ok") is True

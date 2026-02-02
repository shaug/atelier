from types import SimpleNamespace
from unittest.mock import patch

from typer.testing import CliRunner

import atelier.cli as cli


def test_open_passes_args_to_command() -> None:
    captured: dict[str, object] = {}

    def fake_open(args: SimpleNamespace) -> None:
        captured["workspace_name"] = args.workspace_name
        captured["command"] = args.command
        captured["raw"] = args.raw
        captured["shell"] = args.shell

    runner = CliRunner()
    with patch("atelier.commands.open.open_worktree", fake_open):
        result = runner.invoke(
            cli.app, ["open", "feat/root", "--raw", "--shell", "zsh", "echo", "hi"]
        )

    assert result.exit_code == 0
    assert captured["workspace_name"] == "feat/root"
    assert captured["command"] == ["echo", "hi"]
    assert captured["raw"] is True
    assert captured["shell"] == "zsh"

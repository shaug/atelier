from types import SimpleNamespace
from unittest.mock import patch

from typer.testing import CliRunner

import atelier.cli as cli


class TestOpenEditFlags:
    def test_open_edit_defaults_to_none(self) -> None:
        captured: dict[str, object] = {}

        def fake_open(args: SimpleNamespace) -> None:
            captured["edit"] = args.edit

        runner = CliRunner()
        with patch("atelier.commands.open.open_workspace", fake_open):
            result = runner.invoke(cli.app, ["open", "feat-demo"])

        assert result.exit_code == 0
        assert captured["edit"] is None

    def test_open_edit_sets_true(self) -> None:
        captured: dict[str, object] = {}

        def fake_open(args: SimpleNamespace) -> None:
            captured["edit"] = args.edit

        runner = CliRunner()
        with patch("atelier.commands.open.open_workspace", fake_open):
            result = runner.invoke(cli.app, ["open", "feat-demo", "--edit"])

        assert result.exit_code == 0
        assert captured["edit"] is True

    def test_open_no_edit_sets_false(self) -> None:
        captured: dict[str, object] = {}

        def fake_open(args: SimpleNamespace) -> None:
            captured["edit"] = args.edit

        runner = CliRunner()
        with patch("atelier.commands.open.open_workspace", fake_open):
            result = runner.invoke(cli.app, ["open", "feat-demo", "--no-edit"])

        assert result.exit_code == 0
        assert captured["edit"] is False

    def test_open_edit_last_flag_wins(self) -> None:
        captured: dict[str, object] = {}

        def fake_open(args: SimpleNamespace) -> None:
            captured["edit"] = args.edit

        runner = CliRunner()
        with patch("atelier.commands.open.open_workspace", fake_open):
            result = runner.invoke(
                cli.app, ["open", "feat-demo", "--edit", "--no-edit"]
            )

        assert result.exit_code == 0
        assert captured["edit"] is False

    def test_open_no_edit_last_flag_wins(self) -> None:
        captured: dict[str, object] = {}

        def fake_open(args: SimpleNamespace) -> None:
            captured["edit"] = args.edit

        runner = CliRunner()
        with patch("atelier.commands.open.open_workspace", fake_open):
            result = runner.invoke(
                cli.app, ["open", "feat-demo", "--no-edit", "--edit"]
            )

        assert result.exit_code == 0
        assert captured["edit"] is True

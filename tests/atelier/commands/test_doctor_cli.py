from types import SimpleNamespace
from unittest.mock import patch

import typer.main
from typer.testing import CliRunner

import atelier.cli as cli


class TestDoctorCommand:
    def test_doctor_passes_options(self) -> None:
        captured: dict[str, object] = {}

        def fake_doctor(args: SimpleNamespace) -> None:
            captured["format"] = args.format
            captured["fix"] = args.fix
            captured["force"] = args.force

        runner = CliRunner()
        with patch("atelier.cli.doctor_cmd", fake_doctor):
            result = runner.invoke(cli.app, ["doctor", "--format", "json", "--fix", "--force"])

        assert result.exit_code == 0
        assert captured["format"] == "json"
        assert captured["fix"] is True
        assert captured["force"] is True

    def test_doctor_help_describes_force_as_active_hook_override(self) -> None:
        root_command = typer.main.get_command(cli.app)
        doctor_command = root_command.commands["doctor"]
        force_option = next(
            parameter for parameter in doctor_command.params if parameter.name == "force"
        )
        assert force_option.help == "override active-hook deferrals when used with --fix"

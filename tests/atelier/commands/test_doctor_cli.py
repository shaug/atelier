from types import SimpleNamespace
from unittest.mock import patch

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

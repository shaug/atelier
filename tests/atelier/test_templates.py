import tempfile
from pathlib import Path
from unittest.mock import patch

import atelier.templates as templates


class TestInstalledTemplateComparison:
    def test_installed_template_matches_packaged_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                packaged = templates.agent_home_template()
                installed_path = data_dir / "templates" / "agent" / "AGENTS.md"
                installed_path.parent.mkdir(parents=True)
                installed_path.write_text(packaged, encoding="utf-8")

                assert templates.installed_template_modified("agent", "AGENTS.md") is False

    def test_installed_template_differs_from_packaged_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                installed_path = data_dir / "templates" / "agent" / "AGENTS.md"
                installed_path.parent.mkdir(parents=True)
                installed_path.write_text("custom agents\n", encoding="utf-8")

                assert templates.installed_template_modified("agent", "AGENTS.md") is True

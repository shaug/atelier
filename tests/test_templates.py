import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

import atelier.project as project


class TestInstalledTemplateCache(TestCase):
    def test_project_scaffold_prefers_installed_templates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            project_dir = root / "project"
            installed_agents = data_dir / "templates" / "project" / "AGENTS.md"
            installed_agents.parent.mkdir(parents=True)
            installed_agents.write_text("custom agents\n", encoding="utf-8")

            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project.ensure_project_scaffold(project_dir)

            content = (project_dir / "templates" / "AGENTS.md").read_text(
                encoding="utf-8"
            )
            self.assertEqual(content, "custom agents\n")

import tempfile
from pathlib import Path

import atelier.project as project


class TestProjectScaffold:
    def test_project_scaffold_creates_project_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "project"
            assert not project_dir.exists()

            project.ensure_project_scaffold(project_dir)

            assert project_dir.is_dir()

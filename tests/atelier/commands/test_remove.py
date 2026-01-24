import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import atelier.commands.remove as remove_cmd
import atelier.paths as paths
from tests.atelier.helpers import (
    NORMALIZED_ORIGIN,
    enlistment_path_for,
    write_project_config,
)


class TestRemoveProjects:
    def test_remove_exact_project_dir_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_project_config(project_dir, enlistment_path)

            with (
                patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                patch("builtins.input", lambda _: "y"),
            ):
                remove_cmd.remove_projects(
                    SimpleNamespace(
                        project=project_dir.name,
                        all=False,
                        installed=False,
                        orphans=False,
                    )
                )
            assert not project_dir.exists()

    def test_remove_fuzzy_match_prompts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_project_config(project_dir, enlistment_path)

            with (
                patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                patch("builtins.input", lambda _: "y"),
            ):
                needle = project_dir.name[:4]
                remove_cmd.remove_projects(
                    SimpleNamespace(
                        project=needle,
                        all=False,
                        installed=False,
                        orphans=False,
                    )
                )
            assert not project_dir.exists()

    def test_remove_orphans(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_ok = paths.project_dir_for_enlistment(
                    enlistment_path_for(root), NORMALIZED_ORIGIN
                )
                project_orphan = paths.projects_root() / "orphan-project"
            enlistment_ok = root / "repo"
            enlistment_ok.mkdir()
            write_project_config(project_ok, str(enlistment_ok))

            project_orphan.mkdir(parents=True, exist_ok=True)
            write_project_config(project_orphan, str(root / "missing-repo"))

            responses = iter(["y"])
            with (
                patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                patch("builtins.input", lambda _: next(responses)),
            ):
                remove_cmd.remove_projects(
                    SimpleNamespace(
                        project=None,
                        all=False,
                        installed=False,
                        orphans=True,
                    )
                )
            assert project_ok.exists()
            assert not project_orphan.exists()

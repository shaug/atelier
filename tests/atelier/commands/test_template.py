import io
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import atelier.commands.template as template_cmd
import atelier.paths as paths
from tests.atelier.helpers import (
    NORMALIZED_ORIGIN,
    RAW_ORIGIN,
    BaseAtelierTestCase,
    enlistment_path_for,
    write_open_config,
)


class TestTemplateCommand(BaseAtelierTestCase):
    def test_template_project_prefers_project_template(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            installed_template = data_dir / "templates" / "project" / "PROJECT.md"
            installed_template.parent.mkdir(parents=True)
            installed_template.write_text("installed project\n", encoding="utf-8")
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_open_config(project_dir, enlistment_path)
            project_path = project_dir / "PROJECT.md"
            project_path.write_text("project override\n", encoding="utf-8")

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                buffer = io.StringIO()
                with (
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                    patch("sys.stdout", buffer),
                ):
                    template_cmd.render_template(
                        SimpleNamespace(target="project", installed=False, edit=False)
                    )
                self.assertEqual(buffer.getvalue().strip(), "project override")
            finally:
                os.chdir(original_cwd)

    def test_template_project_uses_installed_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            installed_template = data_dir / "templates" / "project" / "PROJECT.md"
            installed_template.parent.mkdir(parents=True)
            installed_template.write_text("installed project\n", encoding="utf-8")
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_open_config(project_dir, enlistment_path)

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                buffer = io.StringIO()
                with (
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                    patch("sys.stdout", buffer),
                ):
                    template_cmd.render_template(
                        SimpleNamespace(target="project", installed=False, edit=False)
                    )
                self.assertEqual(buffer.getvalue().strip(), "installed project")
            finally:
                os.chdir(original_cwd)

    def test_template_workspace_prefers_project_template(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_open_config(project_dir, enlistment_path)
            project_template = project_dir / "templates" / "SUCCESS.md"
            project_template.parent.mkdir(parents=True, exist_ok=True)
            project_template.write_text("project success\n", encoding="utf-8")
            installed_template = data_dir / "templates" / "workspace" / "SUCCESS.md"
            installed_template.parent.mkdir(parents=True, exist_ok=True)
            installed_template.write_text("installed success\n", encoding="utf-8")

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                buffer = io.StringIO()
                with (
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                    patch("sys.stdout", buffer),
                ):
                    template_cmd.render_template(
                        SimpleNamespace(target="workspace", installed=False, edit=False)
                    )
                self.assertEqual(buffer.getvalue().strip(), "project success")
            finally:
                os.chdir(original_cwd)

    def test_template_edit_creates_project_template(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_open_config(project_dir, enlistment_path)
            project_path = project_dir / "PROJECT.md"

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                calls: list[list[str]] = []

                def fake_run(cmd: list[str], cwd: Path | None = None) -> None:
                    calls.append(cmd)
                    temp_path = Path(cmd[-1])
                    self.assertEqual(
                        temp_path.read_text(encoding="utf-8"), "template stub\n"
                    )
                    temp_path.write_text("edited project\n", encoding="utf-8")

                with (
                    patch("atelier.exec.run_command", fake_run),
                    patch(
                        "atelier.templates.project_md_template",
                        return_value="template stub\n",
                    ),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    template_cmd.render_template(
                        SimpleNamespace(target="project", installed=False, edit=True)
                    )

                self.assertTrue(project_path.exists())
                self.assertEqual(
                    project_path.read_text(encoding="utf-8"), "edited project\n"
                )
                self.assertTrue(calls)
                self.assertNotIn(str(project_path), calls[0])
            finally:
                os.chdir(original_cwd)

    def test_template_edit_creates_success_template(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_open_config(project_dir, enlistment_path)
            installed_template = data_dir / "templates" / "workspace" / "SUCCESS.md"
            installed_template.parent.mkdir(parents=True, exist_ok=True)
            installed_template.write_text("installed success\n", encoding="utf-8")
            target_path = project_dir / "templates" / "SUCCESS.md"

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                calls: list[list[str]] = []

                def fake_run(cmd: list[str], cwd: Path | None = None) -> None:
                    calls.append(cmd)
                    temp_path = Path(cmd[-1])
                    self.assertEqual(
                        temp_path.read_text(encoding="utf-8"), "installed success\n"
                    )
                    temp_path.write_text("edited success\n", encoding="utf-8")

                with (
                    patch("atelier.exec.run_command", fake_run),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    template_cmd.render_template(
                        SimpleNamespace(target="workspace", installed=False, edit=True)
                    )

                self.assertTrue(target_path.exists())
                self.assertEqual(
                    target_path.read_text(encoding="utf-8"), "edited success\n"
                )
                self.assertTrue(calls)
                self.assertNotIn(str(target_path), calls[0])
            finally:
                os.chdir(original_cwd)

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
    enlistment_path_for,
    write_open_config,
)


class TestTemplateCommand:
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
                assert buffer.getvalue().strip() == "project override"
            finally:
                os.chdir(original_cwd)

    def test_template_project_installed_ignores_project_template(self) -> None:
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
                        SimpleNamespace(target="project", installed=True, edit=False)
                    )
                assert buffer.getvalue().strip() == "installed project"
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
                assert buffer.getvalue().strip() == "installed project"
            finally:
                os.chdir(original_cwd)

    def test_template_agents_prefers_project_template(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_open_config(project_dir, enlistment_path)
            project_template = project_dir / "templates" / "AGENTS.md"
            project_template.parent.mkdir(parents=True, exist_ok=True)
            project_template.write_text("project agents\n", encoding="utf-8")
            installed_template = data_dir / "templates" / "AGENTS.md"
            installed_template.parent.mkdir(parents=True, exist_ok=True)
            installed_template.write_text("installed agents\n", encoding="utf-8")

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
                        SimpleNamespace(target="agents", installed=False, edit=False)
                    )
                assert buffer.getvalue().strip() == "project agents"
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

                def fake_run(
                    cmd: list[str],
                    cwd: Path | None = None,
                    env: dict[str, str] | None = None,
                ) -> None:
                    calls.append(cmd)
                    temp_path = Path(cmd[-1])
                    assert temp_path.read_text(encoding="utf-8") == "template stub\n"
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

                assert project_path.exists()
                assert project_path.read_text(encoding="utf-8") == "edited project\n"
                assert calls
                assert str(project_path) not in calls[0]
            finally:
                os.chdir(original_cwd)

    def test_template_edit_creates_agents_template(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_open_config(project_dir, enlistment_path)
            installed_template = data_dir / "templates" / "AGENTS.md"
            installed_template.parent.mkdir(parents=True, exist_ok=True)
            installed_template.write_text("installed agents\n", encoding="utf-8")
            target_path = project_dir / "templates" / "AGENTS.md"

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                calls: list[list[str]] = []

                def fake_run(
                    cmd: list[str],
                    cwd: Path | None = None,
                    env: dict[str, str] | None = None,
                ) -> None:
                    calls.append(cmd)
                    temp_path = Path(cmd[-1])
                    assert temp_path.read_text(encoding="utf-8") == "installed agents\n"
                    temp_path.write_text("edited agents\n", encoding="utf-8")

                with (
                    patch("atelier.exec.run_command", fake_run),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    template_cmd.render_template(
                        SimpleNamespace(target="agents", installed=False, edit=True)
                    )

                assert target_path.exists()
                assert target_path.read_text(encoding="utf-8") == "edited agents\n"
                assert calls
                assert str(target_path) not in calls[0]
            finally:
                os.chdir(original_cwd)

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

import atelier.commands.init as init_cmd
import atelier.config as config
import atelier.paths as paths
from tests.atelier.helpers import (
    NORMALIZED_ORIGIN,
    RAW_ORIGIN,
    enlistment_path_for,
    make_init_args,
)


class TestInitProject:
    def test_init_creates_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                args = make_init_args()
                responses = iter(["", "", "", "", "", ""])

                with (
                    patch("builtins.input", lambda _: next(responses)),
                    patch(
                        "atelier.config.shutil.which", return_value="/usr/bin/cursor"
                    ),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    init_cmd.init_project(args)
                    project_dir = paths.project_dir_for_enlistment(
                        enlistment_path, NORMALIZED_ORIGIN
                    )

                config_path = paths.project_config_path(project_dir)
                assert config_path.exists()
                config_payload = config.load_project_config(config_path)
                assert config_payload is not None
                assert config_payload.project.enlistment == enlistment_path
                assert config_payload.project.origin == NORMALIZED_ORIGIN
                assert config_payload.project.repo_url == RAW_ORIGIN
                assert config_payload.branch.pr is True
                assert config_payload.branch.history == "manual"
                assert config_payload.editor.edit == ["cursor", "-w"]
                assert config_payload.editor.work == ["cursor"]
                assert (project_dir / "templates" / "AGENTS.md").exists()
                assert not (project_dir / "AGENTS.md").exists()
                assert (project_dir / "PROJECT.md").exists()
                assert (project_dir / "workspaces").is_dir()
            finally:
                os.chdir(original_cwd)

    def test_init_prefers_cursor_over_env_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                args = make_init_args()
                responses = iter(["", "", "", "", "", ""])

                with (
                    patch("builtins.input", lambda _: next(responses)),
                    patch(
                        "atelier.config.shutil.which", return_value="/usr/bin/cursor"
                    ),
                    patch.dict(os.environ, {"EDITOR": "nano -w"}),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    init_cmd.init_project(args)
                    project_dir = paths.project_dir_for_enlistment(
                        enlistment_path, NORMALIZED_ORIGIN
                    )

                config_path = paths.project_config_path(project_dir)
                config_payload = config.load_project_config(config_path)
                assert config_payload is not None
                assert config_payload.editor.edit == ["cursor", "-w"]
                assert config_payload.editor.work == ["cursor"]
            finally:
                os.chdir(original_cwd)

    def test_init_parses_editor_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                args = make_init_args()
                responses = iter(["", "", "", "", "cursor -w", "cursor"])

                with (
                    patch("builtins.input", lambda _: next(responses)),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    init_cmd.init_project(args)
                    project_dir = paths.project_dir_for_enlistment(
                        enlistment_path, NORMALIZED_ORIGIN
                    )

                config_path = paths.project_config_path(project_dir)
                config_payload = config.load_project_config(config_path)
                assert config_payload is not None
                assert config_payload.editor.edit == ["cursor", "-w"]
                assert config_payload.editor.work == ["cursor"]
            finally:
                os.chdir(original_cwd)

    def test_init_uses_editor_env_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                args = make_init_args()
                responses = iter(["", "", "", "", "", ""])

                with (
                    patch("builtins.input", lambda _: next(responses)),
                    patch("atelier.config.shutil.which", return_value=None),
                    patch.dict(os.environ, {"EDITOR": "nano -w"}),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    init_cmd.init_project(args)
                    project_dir = paths.project_dir_for_enlistment(
                        enlistment_path, NORMALIZED_ORIGIN
                    )

                config_path = paths.project_config_path(project_dir)
                config_payload = config.load_project_config(config_path)
                assert config_payload is not None
                assert config_payload.editor.edit == ["nano", "-w"]
                assert config_payload.editor.work == ["nano"]
            finally:
                os.chdir(original_cwd)

    def test_init_with_flags_overrides_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                payload = {
                    "project": {
                        "enlistment": enlistment_path,
                        "origin": NORMALIZED_ORIGIN,
                        "repo_url": "git@github.com:old/repo.git",
                    },
                    "branch": {
                        "prefix": "old/",
                        "pr": False,
                        "history": "merge",
                    },
                    "agent": {"default": "codex", "options": {"codex": ["--old"]}},
                    "editor": {"edit": ["nano", "-w"], "work": ["nano"]},
                    "atelier": {
                        "id": "01OLD",
                        "version": "0.1.0",
                        "created_at": "2026-01-01T00:00:00Z",
                    },
                }
                with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                    project_dir = paths.project_dir_for_enlistment(
                        enlistment_path, NORMALIZED_ORIGIN
                    )
                project_dir.mkdir(parents=True, exist_ok=True)
                parsed = config.ProjectConfig.model_validate(payload)
                config.write_project_config(
                    paths.project_config_path(project_dir), parsed
                )

                args = make_init_args(
                    branch_prefix="feat/",
                    branch_pr="false",
                    branch_history="merge",
                    agent="codex",
                    editor_edit="cursor -w",
                    editor_work="cursor",
                )

                with (
                    patch(
                        "builtins.input",
                        side_effect=AssertionError("prompt should not be called"),
                    ),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    init_cmd.init_project(args)

                config_path = paths.project_config_path(project_dir)
                config_payload = config.load_project_config(config_path)
                assert config_payload is not None
                assert config_payload.project.enlistment == enlistment_path
                assert config_payload.project.origin == NORMALIZED_ORIGIN
                assert config_payload.project.repo_url == RAW_ORIGIN
                assert config_payload.branch.prefix == "feat/"
                assert config_payload.branch.pr is False
                assert config_payload.branch.history == "merge"
                assert config_payload.agent.default == "codex"
                assert config_payload.editor.edit == ["cursor", "-w"]
                assert config_payload.editor.work == ["cursor"]
                assert (project_dir / "workspaces").is_dir()
            finally:
                os.chdir(original_cwd)

    def test_init_creates_success_template(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                args = make_init_args()
                responses = iter(["", "", "", "", "", ""])

                with (
                    patch("builtins.input", lambda _: next(responses)),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    init_cmd.init_project(args)
                    project_dir = paths.project_dir_for_enlistment(
                        enlistment_path, NORMALIZED_ORIGIN
                    )

                template_path = project_dir / "templates" / "SUCCESS.md"
                assert template_path.exists()
                content = template_path.read_text(encoding="utf-8")
                assert "SUCCESS.md" in content
                assert not (project_dir / "templates" / "WORKSPACE.md").exists()
            finally:
                os.chdir(original_cwd)

    def test_legacy_project_config_rejects_legacy_editor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            project_dir.mkdir(parents=True, exist_ok=True)
            legacy_payload = {
                "project": {
                    "enlistment": enlistment_path,
                    "origin": NORMALIZED_ORIGIN,
                    "repo_url": RAW_ORIGIN,
                },
                "branch": {"prefix": "legacy/", "pr": False, "history": "merge"},
                "agent": {"default": "codex", "options": {"codex": []}},
                "editor": {"default": "vim", "options": {"vim": ["-w"]}},
                "atelier": {
                    "version": "0.1.0",
                    "created_at": "2026-01-01T00:00:00Z",
                    "upgrade": "manual",
                    "managed_files": {"AGENTS.md": "deadbeef"},
                },
            }
            legacy_path = paths.project_config_legacy_path(project_dir)
            legacy_path.write_text(json.dumps(legacy_payload), encoding="utf-8")

            with pytest.raises(SystemExit):
                config.load_project_config(paths.project_config_path(project_dir))
            assert legacy_path.exists()
            assert not legacy_path.with_suffix(".json.bak").exists()
            assert not paths.project_config_sys_path(project_dir).exists()
            assert not paths.project_config_user_path(project_dir).exists()

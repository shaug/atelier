import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import atelier.commands.config as config_cmd
import atelier.config as config
import atelier.paths as paths
from tests.atelier.helpers import (
    NORMALIZED_ORIGIN,
    RAW_ORIGIN,
    enlistment_path_for,
    write_open_config,
)


class TestConfigCommand:
    def test_config_prompt_updates_project_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_open_config(project_dir, enlistment_path)

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                responses = iter(
                    ["team/", "false", "rebase", "codex", "vim -w", "vim", ""]
                )
                with (
                    patch("builtins.input", lambda _: next(responses)),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    config_cmd.show_config(
                        SimpleNamespace(
                            workspace_name=None,
                            installed=False,
                            prompt=True,
                            reset=False,
                        )
                    )
                config_path = paths.project_config_path(project_dir)
                updated = config.load_project_config(config_path)
                assert updated is not None
                assert updated.branch.prefix == "team/"
                assert updated.branch.pr is False
                assert updated.branch.history == "rebase"
                assert updated.editor.edit == ["vim", "-w"]
                assert updated.editor.work == ["vim"]
            finally:
                os.chdir(original_cwd)

    def test_config_prompt_skips_agent_when_only_one_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_open_config(project_dir, enlistment_path)

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                responses = iter(["team/", "false", "rebase", "vim -w", "vim", ""])
                call_count = {"count": 0}

                def fake_input(_: str) -> str:
                    call_count["count"] += 1
                    return next(responses)

                with (
                    patch("builtins.input", fake_input),
                    patch(
                        "atelier.agents.available_agent_names",
                        return_value=("codex",),
                    ),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    config_cmd.show_config(
                        SimpleNamespace(
                            workspace_name=None,
                            installed=False,
                            prompt=True,
                            reset=False,
                        )
                    )
                config_path = paths.project_config_path(project_dir)
                updated = config.load_project_config(config_path)
                assert updated is not None
                assert updated.agent.default == "codex"
                assert call_count["count"] == 6
            finally:
                os.chdir(original_cwd)

    def test_config_prompt_retries_invalid_choices(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_open_config(project_dir, enlistment_path)

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                responses = iter(
                    [
                        "team/",
                        "maybe",
                        "false",
                        "sideways",
                        "merge",
                        "codex",
                        "vim -w",
                        "vim",
                        "",
                    ]
                )
                call_count = {"count": 0}

                def fake_input(_: str) -> str:
                    call_count["count"] += 1
                    return next(responses)

                with (
                    patch("builtins.input", fake_input),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    config_cmd.show_config(
                        SimpleNamespace(
                            workspace_name=None,
                            installed=False,
                            prompt=True,
                            reset=False,
                        )
                    )
                config_path = paths.project_config_path(project_dir)
                updated = config.load_project_config(config_path)
                assert updated is not None
                assert call_count["count"] == 9
                assert updated.branch.pr is False
                assert updated.branch.history == "merge"
            finally:
                os.chdir(original_cwd)

    def test_config_reset_uses_installed_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_open_config(project_dir, enlistment_path)

            defaults = {
                "branch": {"prefix": "installed/", "pr": False, "history": "squash"},
                "agent": {"default": "codex", "options": {"codex": []}},
                "editor": {"edit": ["nano", "-w"], "work": ["nano"]},
            }
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                data_dir.mkdir(parents=True, exist_ok=True)
                config.write_json(paths.installed_config_path(), defaults)

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                with (
                    patch("builtins.input", return_value="y"),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    config_cmd.show_config(
                        SimpleNamespace(
                            workspace_name=None,
                            installed=False,
                            prompt=False,
                            reset=True,
                        )
                    )
                config_path = paths.project_config_path(project_dir)
                updated = config.load_project_config(config_path)
                assert updated is not None
                assert updated.branch.prefix == "installed/"
                assert updated.branch.pr is False
                assert updated.branch.history == "squash"
                assert updated.editor.edit == ["nano", "-w"]
                assert updated.editor.work == ["nano"]
            finally:
                os.chdir(original_cwd)

    def test_config_prompt_updates_installed_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_open_config(project_dir, enlistment_path)

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                responses = iter(
                    ["prefs/", "true", "merge", "codex", "code -w", "code", ""]
                )
                with (
                    patch("builtins.input", lambda _: next(responses)),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    config_cmd.show_config(
                        SimpleNamespace(
                            workspace_name=None,
                            installed=True,
                            prompt=True,
                            reset=False,
                        )
                    )
                with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                    installed_path = paths.installed_config_path()
                stored = json.loads(installed_path.read_text(encoding="utf-8"))
                assert stored["branch"]["prefix"] == "prefs/"
                assert stored["branch"]["pr"] is True
                assert stored["branch"]["history"] == "merge"
                assert stored["editor"]["edit"] == ["code", "-w"]
                assert stored["editor"]["work"] == ["code"]
            finally:
                os.chdir(original_cwd)

    def test_config_edit_updates_user_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_open_config(project_dir, enlistment_path)

            original_cwd = Path.cwd()
            os.chdir(root)
            try:

                def fake_run(cmd: list[str], cwd: Path | None = None) -> None:
                    temp_path = Path(cmd[-1])
                    payload = {
                        "branch": {
                            "prefix": "edited/",
                            "pr": False,
                            "history": "merge",
                        },
                        "agent": {"default": "codex", "options": {"codex": []}},
                        "editor": {"edit": ["nano", "-w"], "work": ["nano"]},
                        "atelier": {"upgrade": "manual"},
                    }
                    temp_path.write_text(json.dumps(payload), encoding="utf-8")

                with (
                    patch("atelier.commands.config.exec.run_command", fake_run),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    config_cmd.show_config(
                        SimpleNamespace(
                            workspace_name=None,
                            installed=False,
                            prompt=False,
                            reset=False,
                            edit=True,
                        )
                    )
                user_config = config.load_project_user_config(
                    paths.project_config_user_path(project_dir)
                )
                assert user_config is not None
                assert user_config.branch.prefix == "edited/"
                assert user_config.branch.pr is False
                assert user_config.branch.history == "merge"
                assert user_config.editor.edit == ["nano", "-w"]
                assert user_config.editor.work == ["nano"]
                assert user_config.atelier.upgrade == "manual"
            finally:
                os.chdir(original_cwd)

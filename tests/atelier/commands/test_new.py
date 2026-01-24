import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import atelier.commands.new as new_cmd
import atelier.config as config
import atelier.paths as paths


def test_new_creates_project_and_opens_workspace() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        data_dir = root / "data"
        target_dir = root / "greenfield"
        commands: list[tuple[list[str], Path | None]] = []
        opened: list[object] = []
        responses = iter(["", "", "", "", "", "", ""])

        def fake_run(cmd: list[str], cwd: Path | None = None) -> None:
            commands.append((cmd, cwd))

        def fake_open(args: object) -> None:
            opened.append(args)

        original_cwd = Path.cwd()
        os.chdir(root)
        try:
            with (
                patch("builtins.input", lambda _: next(responses)),
                patch("atelier.config.shutil.which", return_value="/usr/bin/cursor"),
                patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                patch("atelier.exec.run_command", fake_run),
                patch("atelier.git.git_repo_root", return_value=target_dir),
                patch("atelier.git.git_origin_url", return_value=None),
                patch("atelier.commands.open.open_workspace", fake_open),
            ):
                new_cmd.new_project(
                    SimpleNamespace(
                        path=str(target_dir),
                        branch_prefix=None,
                        branch_pr=None,
                        branch_history=None,
                        agent=None,
                        editor_edit=None,
                        editor_work=None,
                    )
                )
        finally:
            os.chdir(original_cwd)

        enlistment_path = str(target_dir.resolve())
        with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
            project_dir = paths.project_dir_for_enlistment(enlistment_path, None)
            config_path = paths.project_config_path(project_dir)
        assert config_path.exists()
        config_payload = config.load_project_config(config_path)
        assert config_payload is not None
        assert config_payload.project.allow_mainline_workspace is True

        assert commands[0][0][:3] == ["git", "init", "-b"]
        assert commands[0][1] == target_dir
        assert any(
            cmd[:4] == ["git", "-C", str(target_dir), "commit"]
            and "--allow-empty" in cmd
            for cmd, _ in commands
        )
        assert opened
        open_args = opened[0]
        assert getattr(open_args, "workspace_name") == "main"
        assert getattr(open_args, "raw") is True

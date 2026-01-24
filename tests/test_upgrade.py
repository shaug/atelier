import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from typer.testing import CliRunner  # noqa: E402

import atelier.cli as cli  # noqa: E402
import atelier.commands.upgrade as upgrade_cmd  # noqa: E402
import atelier.config as config  # noqa: E402
import atelier.git as git  # noqa: E402
import atelier.paths as paths  # noqa: E402
import atelier.workspace as workspace  # noqa: E402

RAW_ORIGIN = "git@github.com:org/repo.git"
NORMALIZED_ORIGIN = git.normalize_origin_url(RAW_ORIGIN)


def enlistment_path_for(path: Path) -> str:
    return str(path.resolve())


def workspace_id_for(enlistment_path: str, branch: str) -> str:
    return workspace.workspace_identifier(enlistment_path, branch)


class BaseAtelierTestCase(TestCase):
    def setUp(self) -> None:
        super().setUp()
        patcher = patch(
            "atelier.agents.available_agent_names",
            return_value=("codex", "claude"),
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        io_patcher = patch("atelier.io._use_questionary", return_value=False)
        io_patcher.start()
        self.addCleanup(io_patcher.stop)
        input_patcher = patch(
            "builtins.input",
            side_effect=AssertionError("prompted unexpectedly"),
        )
        input_patcher.start()
        self.addCleanup(input_patcher.stop)


def write_project_config(project_dir: Path, enlistment_path: str) -> dict:
    project_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "project": {
            "enlistment": enlistment_path,
            "origin": NORMALIZED_ORIGIN,
            "repo_url": RAW_ORIGIN,
        },
        "branch": {
            "prefix": "scott/",
            "pr": True,
            "history": "manual",
        },
    }
    parsed = config.ProjectConfig.model_validate(payload)
    config.write_project_config(paths.project_config_path(project_dir), parsed)
    return parsed.model_dump()


class TestUpgradeFlags(BaseAtelierTestCase):
    def test_upgrade_flags(self) -> None:
        captured: dict[str, object] = {}

        def fake_upgrade(args: SimpleNamespace) -> None:
            captured["installed"] = args.installed
            captured["dry_run"] = args.dry_run
            captured["yes"] = args.yes
            captured["workspaces"] = args.workspace_names

        runner = CliRunner()
        with patch("atelier.commands.upgrade.upgrade", fake_upgrade):
            result = runner.invoke(
                cli.app,
                ["upgrade", "alpha", "beta", "--installed", "--dry-run", "--yes"],
            )

        self.assertEqual(result.exit_code, 0)
        self.assertTrue(captured["installed"])
        self.assertTrue(captured["dry_run"])
        self.assertTrue(captured["yes"])
        self.assertEqual(captured["workspaces"], ["alpha", "beta"])


class TestUpgradeLegacyEditorMigration(BaseAtelierTestCase):
    def test_upgrade_migrates_legacy_project_user_editor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            enlistment_path = enlistment_path_for(root / "repo")
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )

                project_dir.mkdir(parents=True, exist_ok=True)
                system_payload = {
                    "project": {
                        "enlistment": enlistment_path,
                        "origin": NORMALIZED_ORIGIN,
                        "repo_url": RAW_ORIGIN,
                    },
                    "atelier": {
                        "version": "0.1.0",
                        "created_at": "2026-01-01T00:00:00Z",
                    },
                }
                system_config = config.ProjectSystemConfig.model_validate(
                    system_payload
                )
                config.write_project_system_config(
                    paths.project_config_sys_path(project_dir), system_config
                )

                user_payload = {
                    "agent": {"default": "codex", "options": {"codex": []}},
                    "editor": {
                        "default": "cursor",
                        "options": {"cursor": ["--wait", "--new-window"]},
                    },
                }
                user_path = paths.project_config_user_path(project_dir)
                user_path.write_text(json.dumps(user_payload), encoding="utf-8")

                args = SimpleNamespace(
                    workspace_names=[],
                    installed=False,
                    all_projects=True,
                    no_projects=False,
                    no_workspaces=True,
                    dry_run=False,
                    yes=True,
                )
                upgrade_cmd.upgrade(args)

                updated = json.loads(user_path.read_text(encoding="utf-8"))
                self.assertEqual(
                    updated["editor"]["edit"],
                    ["cursor", "--wait", "--new-window"],
                )
                self.assertEqual(
                    updated["editor"]["work"],
                    ["cursor", "--new-window"],
                )
                self.assertNotIn("default", updated["editor"])
                self.assertNotIn("options", updated["editor"])
                self.assertTrue(user_path.with_suffix(".json.bak").exists())

    def test_upgrade_migrates_legacy_project_config_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            enlistment_path = enlistment_path_for(root / "repo")
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
                    "editor": {
                        "default": "cursor",
                        "options": {"cursor": ["--wait", "--new-window"]},
                    },
                    "atelier": {
                        "version": "0.1.0",
                        "created_at": "2026-01-01T00:00:00Z",
                        "upgrade": "manual",
                    },
                }
                legacy_path = paths.project_config_legacy_path(project_dir)
                legacy_path.write_text(json.dumps(legacy_payload), encoding="utf-8")

                args = SimpleNamespace(
                    workspace_names=[],
                    installed=False,
                    all_projects=True,
                    no_projects=False,
                    no_workspaces=True,
                    dry_run=False,
                    yes=True,
                )
                upgrade_cmd.upgrade(args)

                sys_path = paths.project_config_sys_path(project_dir)
                user_path = paths.project_config_user_path(project_dir)
                self.assertTrue(sys_path.exists())
                self.assertTrue(user_path.exists())
                self.assertFalse(legacy_path.exists())
                self.assertTrue(legacy_path.with_suffix(".json.bak").exists())

                updated = json.loads(user_path.read_text(encoding="utf-8"))
                self.assertEqual(
                    updated["editor"]["edit"],
                    ["cursor", "--wait", "--new-window"],
                )
                self.assertEqual(
                    updated["editor"]["work"],
                    ["cursor", "--new-window"],
                )
                self.assertNotIn("default", updated["editor"])
                self.assertNotIn("options", updated["editor"])


class TestUpgradeWorkspaceConfigRepair(BaseAtelierTestCase):
    def test_upgrade_repairs_missing_workspace_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_project_config(project_dir, enlistment_path)
            branch = "scott/alpha"
            workspace_dir = paths.workspace_dir_for_branch(
                project_dir,
                branch,
                workspace_id_for(enlistment_path, branch),
            )
            workspace_dir.mkdir(parents=True, exist_ok=True)

            args = SimpleNamespace(
                workspace_names=[branch],
                installed=False,
                all_projects=False,
                no_projects=True,
                no_workspaces=False,
                dry_run=False,
                yes=True,
            )

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                with (
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    upgrade_cmd.upgrade(args)
            finally:
                os.chdir(original_cwd)

            sys_path = paths.workspace_config_sys_path(workspace_dir)
            user_path = paths.workspace_config_user_path(workspace_dir)
            self.assertTrue(sys_path.exists())
            self.assertTrue(user_path.exists())
            loaded = config.load_workspace_config(
                paths.workspace_config_path(workspace_dir)
            )
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.workspace.branch, branch)

    def test_upgrade_repairs_orphaned_workspace_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_project_config(project_dir, enlistment_path)
            branch = "scott/alpha"
            workspace_dir = paths.workspace_dir_for_branch(
                project_dir,
                branch,
                workspace_id_for(enlistment_path, branch),
            )
            workspace_dir.mkdir(parents=True, exist_ok=True)

            args = SimpleNamespace(
                workspace_names=[],
                installed=False,
                all_projects=False,
                no_projects=True,
                no_workspaces=False,
                dry_run=False,
                yes=False,
            )

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                with (
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                    patch("atelier.commands.upgrade.select", return_value="repair"),
                    patch("atelier.commands.upgrade.confirm", return_value=True),
                ):
                    upgrade_cmd.upgrade(args)
            finally:
                os.chdir(original_cwd)

            sys_path = paths.workspace_config_sys_path(workspace_dir)
            user_path = paths.workspace_config_user_path(workspace_dir)
            self.assertTrue(sys_path.exists())
            self.assertTrue(user_path.exists())
            loaded = config.load_workspace_config(
                paths.workspace_config_path(workspace_dir)
            )
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.workspace.branch, branch)

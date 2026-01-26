import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from typer.testing import CliRunner

import atelier.cli as cli
import atelier.commands.upgrade as upgrade_cmd
import atelier.config as config
import atelier.paths as paths
import atelier.templates as templates
from tests.atelier.helpers import (
    NORMALIZED_ORIGIN,
    RAW_ORIGIN,
    enlistment_path_for,
    workspace_id_for,
    write_project_config,
)


class TestUpgradeFlags:
    def test_upgrade_flags(self) -> None:
        captured: dict[str, object] = {}

        def fake_upgrade(args: SimpleNamespace) -> None:
            captured["installed"] = args.installed
            captured["dry_run"] = args.dry_run
            captured["keep_modified"] = args.keep_modified
            captured["yes"] = args.yes
            captured["workspaces"] = args.workspace_names

        runner = CliRunner()
        with patch("atelier.commands.upgrade.upgrade", fake_upgrade):
            result = runner.invoke(
                cli.app,
                [
                    "upgrade",
                    "alpha",
                    "beta",
                    "--installed",
                    "--dry-run",
                    "--keep-modified",
                    "--yes",
                ],
            )

        assert result.exit_code == 0
        assert captured["installed"] is True
        assert captured["dry_run"] is True
        assert captured["keep_modified"] is True
        assert captured["yes"] is True
        assert captured["workspaces"] == ["alpha", "beta"]


class TestUpgradeLegacyEditorMigration:
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
                assert updated["editor"]["edit"] == [
                    "cursor",
                    "--wait",
                    "--new-window",
                ]
                assert updated["editor"]["work"] == ["cursor", "--new-window"]
                assert "default" not in updated["editor"]
                assert "options" not in updated["editor"]
                assert user_path.with_suffix(".json.bak").exists()

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
                assert sys_path.exists()
                assert user_path.exists()
                assert not legacy_path.exists()
                assert legacy_path.with_suffix(".json.bak").exists()

                updated = json.loads(user_path.read_text(encoding="utf-8"))
                assert updated["editor"]["edit"] == [
                    "cursor",
                    "--wait",
                    "--new-window",
                ]
                assert updated["editor"]["work"] == ["cursor", "--new-window"]
                assert "default" not in updated["editor"]
                assert "options" not in updated["editor"]

    def test_upgrade_migrates_legacy_project_tickets(self) -> None:
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
                    "agent": {"default": "codex", "options": {"codex": []}},
                    "tickets": {
                        "provider": "github",
                        "default_project": "org/repo",
                        "default_namespace": "org",
                    },
                    "atelier": {
                        "version": "0.1.0",
                        "created_at": "2026-01-01T00:00:00Z",
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

                updated = json.loads(user_path.read_text(encoding="utf-8"))
                assert updated["tickets"]["provider"] == "github"
                assert updated["tickets"]["default_project"] == "org/repo"
                assert updated["tickets"]["default_namespace"] == "org"

                system_payload = json.loads(sys_path.read_text(encoding="utf-8"))
                assert "tickets" not in system_payload


class TestUpgradeWorkspaceConfigRepair:
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
            assert sys_path.exists()
            assert user_path.exists()
            loaded = config.load_workspace_config(
                paths.workspace_config_path(workspace_dir)
            )
            assert loaded is not None
            assert loaded.workspace.branch == branch
            assert loaded.workspace.uid is not None


class TestUpgradeTemplateComparison:
    def test_upgrade_uses_installed_cache_when_modified(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            enlistment_path = enlistment_path_for(root / "repo")
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
                write_project_config(project_dir, enlistment_path)

                templates_dir = project_dir / "templates"
                templates_dir.mkdir(parents=True, exist_ok=True)

                custom_text = "custom agents\n"
                (templates_dir / "AGENTS.md").write_text(custom_text, encoding="utf-8")

                installed_path = data_dir / "templates" / "AGENTS.md"
                installed_path.parent.mkdir(parents=True, exist_ok=True)
                installed_path.write_text(custom_text, encoding="utf-8")

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

                updated = config.load_project_config(
                    paths.project_config_path(project_dir)
                )
                assert updated is not None
                assert updated.atelier.managed_files["templates/AGENTS.md"] == (
                    config.hash_text(custom_text)
                )

    def test_upgrade_prompts_to_overwrite_modified_template(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            enlistment_path = enlistment_path_for(root / "repo")
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
                write_project_config(project_dir, enlistment_path)

                templates_dir = project_dir / "templates"
                templates_dir.mkdir(parents=True, exist_ok=True)

                canonical = templates.agents_template(prefer_installed_if_modified=True)
                template_path = templates_dir / "AGENTS.md"
                template_path.write_text("custom agents\n", encoding="utf-8")
                (templates_dir / "SUCCESS.md").write_text(
                    "custom success\n", encoding="utf-8"
                )

                config.update_project_managed_files(
                    project_dir,
                    {"templates/AGENTS.md": config.hash_text(canonical)},
                )

                args = SimpleNamespace(
                    workspace_names=[],
                    installed=False,
                    all_projects=True,
                    no_projects=False,
                    no_workspaces=True,
                    dry_run=False,
                    keep_modified=False,
                    yes=False,
                )
                confirm_mock = patch(
                    "atelier.commands.upgrade.confirm", return_value=True
                )
                with confirm_mock as confirm:
                    upgrade_cmd.upgrade(args)

                assert any(
                    "appears modified" in str(call.args[0])
                    for call in confirm.call_args_list
                )
                assert template_path.read_text(encoding="utf-8") == canonical

    def test_upgrade_keep_modified_skips_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            enlistment_path = enlistment_path_for(root / "repo")
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
                write_project_config(project_dir, enlistment_path)

                templates_dir = project_dir / "templates"
                templates_dir.mkdir(parents=True, exist_ok=True)

                canonical = templates.agents_template(prefer_installed_if_modified=True)
                template_path = templates_dir / "AGENTS.md"
                template_path.write_text("custom agents\n", encoding="utf-8")
                (templates_dir / "SUCCESS.md").write_text(
                    "custom success\n", encoding="utf-8"
                )

                config.update_project_managed_files(
                    project_dir,
                    {"templates/AGENTS.md": config.hash_text(canonical)},
                )

                args = SimpleNamespace(
                    workspace_names=[],
                    installed=False,
                    all_projects=True,
                    no_projects=False,
                    no_workspaces=True,
                    dry_run=False,
                    keep_modified=True,
                    yes=False,
                )
                with patch("atelier.commands.upgrade.confirm") as confirm:
                    upgrade_cmd.upgrade(args)

                confirm.assert_not_called()
                assert template_path.read_text(encoding="utf-8") == "custom agents\n"

    def test_upgrade_prompts_to_remove_modified_legacy_project_agents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            enlistment_path = enlistment_path_for(root / "repo")
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
                write_project_config(project_dir, enlistment_path)

                templates_dir = project_dir / "templates"
                templates_dir.mkdir(parents=True, exist_ok=True)
                canonical = templates.agents_template(prefer_installed_if_modified=True)
                (templates_dir / "AGENTS.md").write_text(canonical, encoding="utf-8")
                (templates_dir / "SUCCESS.md").write_text(
                    templates.success_md_template(prefer_installed_if_modified=True),
                    encoding="utf-8",
                )
                config.update_project_managed_files(
                    project_dir,
                    {"templates/AGENTS.md": config.hash_text(canonical)},
                )

                legacy_path = project_dir / "AGENTS.md"
                legacy_path.write_text("legacy agents\n", encoding="utf-8")

                args = SimpleNamespace(
                    workspace_names=[],
                    installed=False,
                    all_projects=True,
                    no_projects=False,
                    no_workspaces=True,
                    dry_run=False,
                    keep_modified=False,
                    yes=False,
                )
                confirm_mock = patch(
                    "atelier.commands.upgrade.confirm",
                    side_effect=[True, True],
                )
                with confirm_mock as confirm:
                    upgrade_cmd.upgrade(args)

                assert not legacy_path.exists()
                assert any(
                    "legacy project AGENTS.md" in str(call.args[0])
                    for call in confirm.call_args_list
                )

    def test_upgrade_keep_modified_skips_legacy_agents_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            enlistment_path = enlistment_path_for(root / "repo")
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
                write_project_config(project_dir, enlistment_path)

                templates_dir = project_dir / "templates"
                templates_dir.mkdir(parents=True, exist_ok=True)
                canonical = templates.agents_template(prefer_installed_if_modified=True)
                (templates_dir / "AGENTS.md").write_text(canonical, encoding="utf-8")
                (templates_dir / "SUCCESS.md").write_text(
                    templates.success_md_template(prefer_installed_if_modified=True),
                    encoding="utf-8",
                )
                config.update_project_managed_files(
                    project_dir,
                    {"templates/AGENTS.md": config.hash_text(canonical)},
                )

                legacy_path = project_dir / "AGENTS.md"
                legacy_path.write_text("legacy agents\n", encoding="utf-8")

                args = SimpleNamespace(
                    workspace_names=[],
                    installed=False,
                    all_projects=True,
                    no_projects=False,
                    no_workspaces=True,
                    dry_run=False,
                    keep_modified=True,
                    yes=False,
                )
                with patch("atelier.commands.upgrade.confirm") as confirm:
                    upgrade_cmd.upgrade(args)

                confirm.assert_not_called()
                assert legacy_path.exists()

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
            assert sys_path.exists()
            assert user_path.exists()
            loaded = config.load_workspace_config(
                paths.workspace_config_path(workspace_dir)
            )
            assert loaded is not None
            assert loaded.workspace.branch == branch
            assert loaded.workspace.uid is not None

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

import pytest

import atelier.commands.init as init_cmd
import atelier.config as config
import atelier.external_registry as external_registry
import atelier.paths as paths
import atelier.project as project
from tests.atelier.helpers import (
    NORMALIZED_ORIGIN,
    RAW_ORIGIN,
    enlistment_path_for,
    make_init_args,
)


class TestInitProject:
    @pytest.mark.skipif(shutil.which("bd") is None, reason="bd not installed")
    def test_init_does_not_modify_repo_files_when_using_real_bd(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir(parents=True, exist_ok=True)
            data_dir = root / "data"

            subprocess.run(["git", "-C", str(repo), "init"], check=True)
            subprocess.run(
                ["git", "-C", str(repo), "config", "user.email", "test@example.com"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(repo), "config", "user.name", "Test User"],
                check=True,
            )
            (repo / "README.md").write_text("base\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
            subprocess.run(
                ["git", "-C", str(repo), "commit", "-m", "chore: init repo"],
                check=True,
            )
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo),
                    "remote",
                    "add",
                    "origin",
                    "https://github.com/example/repo.git",
                ],
                check=True,
            )

            args = make_init_args(
                branch_prefix="",
                branch_pr="true",
                branch_history="manual",
                branch_pr_strategy="parallel",
                agent="codex",
                editor_edit="true",
                editor_work="true",
            )

            original_cwd = Path.cwd()
            os.chdir(repo)
            try:
                with (
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.commands.init.confirm", return_value=False),
                    patch(
                        "atelier.config.agents.available_agent_names",
                        return_value=("codex",),
                    ),
                ):
                    init_cmd.init_project(args)
            finally:
                os.chdir(original_cwd)

            status = subprocess.run(
                ["git", "-C", str(repo), "status", "--porcelain"],
                check=True,
                capture_output=True,
                text=True,
            )
            assert status.stdout.strip() == ""
            assert not (repo / ".gitattributes").exists()
            assert not (repo / "AGENTS.md").exists()

    def test_init_creates_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                args = make_init_args()
                responses = iter(["", "", "", "", "", "", "", "", ""])

                with (
                    patch("builtins.input", lambda _: next(responses)),
                    patch("atelier.config.shutil.which", return_value="/usr/bin/cursor"),
                    patch(
                        "atelier.commands.init.beads.run_bd_command",
                        return_value=CompletedProcess(
                            args=["bd"], returncode=0, stdout="", stderr=""
                        ),
                    ),
                    patch(
                        "atelier.commands.init.beads.ensure_atelier_types",
                        return_value=False,
                    ),
                    patch(
                        "atelier.commands.init.beads.ensure_atelier_store",
                        return_value=False,
                    ),
                    patch(
                        "atelier.commands.init.beads.ensure_atelier_issue_prefix",
                        return_value=False,
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
                assert config_payload.project.provider == "github"
                assert config_payload.branch.pr is True
                assert config_payload.branch.history == "manual"
                assert config_payload.editor.edit == ["cursor", "-w"]
                assert config_payload.editor.work == ["cursor"]
                assert not (project_dir / "AGENTS.md").exists()
                assert not (project_dir / "PROJECT.md").exists()
            finally:
                os.chdir(original_cwd)

    def test_init_uses_project_scoped_beads_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(enlistment_path, NORMALIZED_ORIGIN)
            captured: list[tuple[str, Path, Path]] = []
            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                args = make_init_args()
                responses = iter(["", "", "", "", "", "", "", "", ""])

                def _capture(name: str, *, beads_root: Path, cwd: Path) -> None:
                    captured.append((name, beads_root, cwd))

                def fake_bd(
                    _args: list[str], *, beads_root: Path, cwd: Path
                ) -> CompletedProcess[str]:
                    _capture("run_bd_command", beads_root=beads_root, cwd=cwd)
                    return CompletedProcess(args=["bd"], returncode=0, stdout="", stderr="")

                def fake_ensure_store(*, beads_root: Path, cwd: Path) -> bool:
                    _capture("ensure_atelier_store", beads_root=beads_root, cwd=cwd)
                    return False

                def fake_ensure_prefix(*, beads_root: Path, cwd: Path) -> bool:
                    _capture("ensure_atelier_issue_prefix", beads_root=beads_root, cwd=cwd)
                    return False

                def fake_ensure_types(*, beads_root: Path, cwd: Path) -> bool:
                    _capture("ensure_atelier_types", beads_root=beads_root, cwd=cwd)
                    return False

                with (
                    patch("builtins.input", lambda _: next(responses)),
                    patch("atelier.commands.init.confirm", return_value=False),
                    patch(
                        "atelier.commands.init.beads.run_bd_command",
                        side_effect=fake_bd,
                    ),
                    patch(
                        "atelier.commands.init.beads.ensure_atelier_types",
                        side_effect=fake_ensure_types,
                    ),
                    patch(
                        "atelier.commands.init.beads.ensure_atelier_store",
                        side_effect=fake_ensure_store,
                    ),
                    patch(
                        "atelier.commands.init.beads.ensure_atelier_issue_prefix",
                        side_effect=fake_ensure_prefix,
                    ),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    init_cmd.init_project(args)
            finally:
                os.chdir(original_cwd)

            assert captured
            for _name, beads_root, cwd in captured:
                assert beads_root == project_dir / ".beads"
                assert Path(str(cwd)).resolve() == project_dir.resolve()

    def test_init_persists_provider_selected_during_init(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                args = make_init_args()
                responses = iter(["", "", "", "", "", "", "", "", ""])

                with (
                    patch("builtins.input", lambda _: next(responses)),
                    patch(
                        "atelier.commands.init.beads.run_bd_command",
                        return_value=CompletedProcess(
                            args=["bd"], returncode=0, stdout="", stderr=""
                        ),
                    ),
                    patch(
                        "atelier.commands.init.beads.ensure_atelier_types",
                        return_value=False,
                    ),
                    patch(
                        "atelier.commands.init.beads.ensure_atelier_store",
                        return_value=False,
                    ),
                    patch(
                        "atelier.commands.init.beads.ensure_atelier_issue_prefix",
                        return_value=False,
                    ),
                    patch(
                        "atelier.commands.init.external_registry.resolve_planner_provider",
                        return_value=external_registry.PlannerProviderResolution(
                            selected_provider="linear",
                            available_providers=("github", "linear"),
                            github_repo="acme/widgets",
                        ),
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
                config_payload = config.load_project_config(config_path)
                assert config_payload is not None
                assert config_payload.project.provider == "linear"
            finally:
                os.chdir(original_cwd)

    def test_init_prompts_provider_selection_for_existing_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                args = make_init_args(
                    branch_prefix="",
                    branch_pr="true",
                    branch_history="manual",
                    branch_pr_strategy="parallel",
                    agent="codex",
                    editor_edit="cursor -w",
                    editor_work="cursor",
                )
                with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                    project_dir = paths.project_dir_for_enlistment(
                        enlistment_path, NORMALIZED_ORIGIN
                    )
                project.ensure_project_dirs(project_dir)
                seed = config.ProjectConfig.model_validate(
                    {
                        "project": {
                            "enlistment": enlistment_path,
                            "origin": NORMALIZED_ORIGIN,
                            "repo_url": RAW_ORIGIN,
                            "provider": "github",
                        },
                        "branch": {
                            "prefix": "",
                            "pr": True,
                            "history": "manual",
                            "pr_strategy": "parallel",
                        },
                        "agent": {"default": "codex", "options": {"codex": []}},
                        "editor": {"edit": ["cursor", "-w"], "work": ["cursor"]},
                    }
                )
                config.write_project_config(paths.project_config_path(project_dir), seed)

                with (
                    patch(
                        "atelier.commands.init.beads.run_bd_command",
                        return_value=CompletedProcess(
                            args=["bd"], returncode=0, stdout="", stderr=""
                        ),
                    ),
                    patch(
                        "atelier.commands.init.beads.ensure_atelier_types",
                        return_value=False,
                    ),
                    patch(
                        "atelier.commands.init.beads.ensure_atelier_store",
                        return_value=False,
                    ),
                    patch(
                        "atelier.commands.init.beads.ensure_atelier_issue_prefix",
                        return_value=False,
                    ),
                    patch(
                        "atelier.commands.init.external_registry.resolve_planner_provider",
                        return_value=external_registry.PlannerProviderResolution(
                            selected_provider="github",
                            available_providers=("github", "linear"),
                            github_repo="acme/widgets",
                        ),
                    ),
                    patch("atelier.commands.init.select", return_value="none") as choose,
                    patch("atelier.commands.init.confirm", return_value=False),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("sys.stdin.isatty", return_value=True),
                    patch("sys.stdout.isatty", return_value=True),
                ):
                    init_cmd.init_project(args)

                choose.assert_called_once()
                config_payload = config.load_project_config(paths.project_config_path(project_dir))
                assert config_payload is not None
                assert config_payload.project.provider is None
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
                responses = iter(["", "", "", "", "", "", "", "", ""])

                with (
                    patch("builtins.input", lambda _: next(responses)),
                    patch("atelier.config.shutil.which", return_value="/usr/bin/cursor"),
                    patch.dict(os.environ, {"EDITOR": "nano -w"}),
                    patch(
                        "atelier.commands.init.beads.run_bd_command",
                        return_value=CompletedProcess(
                            args=["bd"], returncode=0, stdout="", stderr=""
                        ),
                    ),
                    patch(
                        "atelier.commands.init.beads.ensure_atelier_types",
                        return_value=False,
                    ),
                    patch(
                        "atelier.commands.init.beads.ensure_atelier_store",
                        return_value=False,
                    ),
                    patch(
                        "atelier.commands.init.beads.ensure_atelier_issue_prefix",
                        return_value=False,
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
                responses = iter(["", "", "", "", "", "cursor -w", "cursor", "", ""])

                with (
                    patch("builtins.input", lambda _: next(responses)),
                    patch(
                        "atelier.commands.init.beads.run_bd_command",
                        return_value=CompletedProcess(
                            args=["bd"], returncode=0, stdout="", stderr=""
                        ),
                    ),
                    patch(
                        "atelier.commands.init.beads.ensure_atelier_types",
                        return_value=False,
                    ),
                    patch(
                        "atelier.commands.init.beads.ensure_atelier_store",
                        return_value=False,
                    ),
                    patch(
                        "atelier.commands.init.beads.ensure_atelier_issue_prefix",
                        return_value=False,
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
                config_payload = config.load_project_config(config_path)
                assert config_payload is not None
                assert config_payload.editor.edit == ["cursor", "-w"]
                assert config_payload.editor.work == ["cursor"]
            finally:
                os.chdir(original_cwd)

    def test_init_resolves_provider_non_interactive_then_prompts_with_none(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                args = make_init_args(
                    branch_prefix="scott/",
                    branch_pr="true",
                    branch_history="rebase",
                    branch_pr_strategy="on-ready",
                    agent="codex",
                    editor_edit="cursor -w --new-window",
                    editor_work="cursor --new-window",
                )
                captured_interactive: list[bool] = []

                def fake_resolve_provider(
                    *_: object,
                    interactive: bool = True,
                    **__: object,
                ) -> external_registry.PlannerProviderResolution:
                    captured_interactive.append(interactive)
                    return external_registry.PlannerProviderResolution(
                        selected_provider="github",
                        available_providers=("github", "linear"),
                        github_repo="acme/widgets",
                    )

                with (
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                    patch("atelier.commands.init.confirm", return_value=False),
                    patch("atelier.commands.init.select", return_value="none") as choose,
                    patch(
                        "atelier.commands.init.external_registry.resolve_planner_provider",
                        side_effect=fake_resolve_provider,
                    ),
                    patch(
                        "atelier.commands.init.beads.run_bd_command",
                        return_value=CompletedProcess(
                            args=["bd"], returncode=0, stdout="", stderr=""
                        ),
                    ),
                    patch(
                        "atelier.commands.init.beads.ensure_atelier_types",
                        return_value=False,
                    ),
                    patch(
                        "atelier.commands.init.beads.ensure_atelier_store",
                        return_value=False,
                    ),
                    patch(
                        "atelier.commands.init.beads.ensure_atelier_issue_prefix",
                        return_value=False,
                    ),
                    patch("sys.stdin.isatty", return_value=True),
                    patch("sys.stdout.isatty", return_value=True),
                ):
                    init_cmd.init_project(args)

                assert captured_interactive == [False]
                choose.assert_called_once()
                prompt_choices = choose.call_args.args[1]
                assert prompt_choices[0] == "none"
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
                responses = iter(["", "", "", "", "", "", "", "", ""])

                with (
                    patch("builtins.input", lambda _: next(responses)),
                    patch("atelier.config.shutil.which", return_value=None),
                    patch.dict(os.environ, {"EDITOR": "nano -w"}),
                    patch(
                        "atelier.commands.init.beads.run_bd_command",
                        return_value=CompletedProcess(
                            args=["bd"], returncode=0, stdout="", stderr=""
                        ),
                    ),
                    patch(
                        "atelier.commands.init.beads.ensure_atelier_types",
                        return_value=False,
                    ),
                    patch(
                        "atelier.commands.init.beads.ensure_atelier_store",
                        return_value=False,
                    ),
                    patch(
                        "atelier.commands.init.beads.ensure_atelier_issue_prefix",
                        return_value=False,
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
                config.write_project_config(paths.project_config_path(project_dir), parsed)

                args = make_init_args(
                    branch_prefix="feat/",
                    branch_pr="false",
                    branch_history="merge",
                    branch_pr_strategy="sequential",
                    agent="codex",
                    editor_edit="cursor -w",
                    editor_work="cursor",
                )

                with (
                    patch(
                        "builtins.input",
                        side_effect=AssertionError("prompt should not be called"),
                    ),
                    patch("atelier.commands.init.confirm", return_value=False),
                    patch(
                        "atelier.commands.init.beads.run_bd_command",
                        return_value=CompletedProcess(
                            args=["bd"], returncode=0, stdout="", stderr=""
                        ),
                    ),
                    patch(
                        "atelier.commands.init.beads.ensure_atelier_types",
                        return_value=False,
                    ),
                    patch(
                        "atelier.commands.init.beads.ensure_atelier_store",
                        return_value=False,
                    ),
                    patch(
                        "atelier.commands.init.beads.ensure_atelier_issue_prefix",
                        return_value=False,
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
            finally:
                os.chdir(original_cwd)

    def test_init_reprompts_with_existing_defaults(self) -> None:
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
                        "repo_url": RAW_ORIGIN,
                    },
                    "branch": {
                        "prefix": "existing/",
                        "pr": False,
                        "history": "merge",
                    },
                    "agent": {"default": "codex", "options": {"codex": []}},
                    "editor": {"edit": ["nano", "-w"], "work": ["nano"]},
                    "atelier": {
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
                config.write_project_config(paths.project_config_path(project_dir), parsed)

                args = make_init_args()
                responses = iter(["", "", "", "", "", "", "", "", ""])

                with (
                    patch("builtins.input", lambda _: next(responses)),
                    patch("atelier.commands.init.confirm", return_value=False),
                    patch(
                        "atelier.commands.init.beads.run_bd_command",
                        return_value=CompletedProcess(
                            args=["bd"], returncode=0, stdout="", stderr=""
                        ),
                    ),
                    patch(
                        "atelier.commands.init.beads.ensure_atelier_types",
                        return_value=False,
                    ),
                    patch(
                        "atelier.commands.init.beads.ensure_atelier_store",
                        return_value=False,
                    ),
                    patch(
                        "atelier.commands.init.beads.ensure_atelier_issue_prefix",
                        return_value=False,
                    ),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    init_cmd.init_project(args)

                config_path = paths.project_config_path(project_dir)
                config_payload = config.load_project_config(config_path)
                assert config_payload is not None
                assert config_payload.branch.prefix == "existing/"
                assert config_payload.branch.pr is False
                assert config_payload.branch.history == "merge"
                assert config_payload.agent.default == "codex"
                assert config_payload.editor.edit == ["nano", "-w"]
                assert config_payload.editor.work == ["nano"]
            finally:
                os.chdir(original_cwd)

    def test_legacy_project_config_rejects_legacy_editor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(enlistment_path, NORMALIZED_ORIGIN)
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

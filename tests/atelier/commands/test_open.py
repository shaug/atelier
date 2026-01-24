import json
import os
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import atelier
import atelier.codex as codex
import atelier.commands.open as open_cmd
import atelier.config as config
import atelier.git as git
import atelier.paths as paths
import atelier.templates as templates
import atelier.workspace as workspace
from tests.atelier.helpers import (
    NORMALIZED_ORIGIN,
    RAW_ORIGIN,
    DummyResult,
    enlistment_path_for,
    init_local_repo,
    init_local_repo_without_feature,
    make_open_config,
    workspace_id_for,
    write_open_config,
    write_workspace_config,
)


def record_codex_command(commands: list[list[str]]):
    def fake_codex(
        cmd: list[str],
        cwd: Path | None = None,
        allow_missing: bool = False,
        env: dict[str, str] | None = None,
    ) -> codex.CodexRunResult:
        commands.append(cmd)
        return codex.CodexRunResult(returncode=0, session_id=None, resume_command=None)

    return fake_codex


fake_codex = record_codex_command([])


class TestOpenWorkspace:
    def test_open_creates_workspace_and_launches(self) -> None:
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
                commands: list[list[str]] = []
                fake_codex = record_codex_command(commands)

                def fake_run(
                    cmd: list[str],
                    cwd: Path | None = None,
                    env: dict[str, str] | None = None,
                ) -> None:
                    commands.append(cmd)

                with (
                    patch("atelier.exec.run_command", fake_run),
                    patch("atelier.codex.run_codex_command", fake_codex),
                    patch("atelier.sessions.find_codex_session", return_value=None),
                    patch("atelier.git.git_current_branch", return_value="main"),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.git.git_is_clean", return_value=True),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    open_cmd.open_workspace(SimpleNamespace(workspace_name="feat-demo"))

                workspace_branch = "scott/feat-demo"
                workspace_dir = paths.workspace_dir_for_branch(
                    project_dir,
                    workspace_branch,
                    workspace_id_for(enlistment_path, workspace_branch),
                )
                assert (workspace_dir / "AGENTS.md").exists()
                assert (workspace_dir / "PROJECT.md").exists()
                assert (workspace_dir / "PERSIST.md").exists()
                assert (workspace_dir / "SUCCESS.md").exists()
                assert paths.workspace_config_path(workspace_dir).exists()

                workspace_config = config.load_workspace_config(
                    paths.workspace_config_path(workspace_dir)
                )
                assert workspace_config is not None
                assert workspace_config.workspace.branch == workspace_branch
                assert workspace_config.workspace.uid

                agents_content = (workspace_dir / "AGENTS.md").read_text(
                    encoding="utf-8"
                )
                assert "Atelier Agent Contract" in agents_content
                assert "SUCCESS.md" in agents_content
                project_content = (project_dir / "PROJECT.md").read_text(
                    encoding="utf-8"
                )
                workspace_project_content = (workspace_dir / "PROJECT.md").read_text(
                    encoding="utf-8"
                )
                assert workspace_project_content == project_content
                assert "PERSIST.md" in agents_content

                persist_content = (workspace_dir / "PERSIST.md").read_text(
                    encoding="utf-8"
                )
                assert "## Integration Strategy" in persist_content
                assert "Pull requests expected: yes" in persist_content
                assert "History policy: manual" in persist_content
                assert workspace_config.atelier.managed_files.get(
                    "PERSIST.md"
                ) == config.hash_text(persist_content)

                assert any(cmd[:2] == ["git", "clone"] for cmd in commands)
                repo_path = (workspace_dir / "repo").resolve()
                assert any(
                    cmd[0] == "git"
                    and any(
                        Path(part).resolve() == repo_path
                        for part in cmd
                        if isinstance(part, str) and part.startswith("/")
                    )
                    for cmd in commands
                )
                assert any(cmd[0] == "codex" and "--cd" in cmd for cmd in commands)
            finally:
                os.chdir(original_cwd)

    def test_open_records_tickets_for_new_workspace(self) -> None:
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
                commands: list[list[str]] = []
                fake_codex = record_codex_command(commands)
                with (
                    patch("atelier.exec.run_command", lambda *args, **kwargs: None),
                    patch("atelier.codex.run_codex_command", fake_codex),
                    patch("atelier.sessions.find_codex_session", return_value=None),
                    patch("atelier.git.git_current_branch", return_value="main"),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.git.git_is_clean", return_value=True),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    open_cmd.open_workspace(
                        SimpleNamespace(
                            workspace_name="feat-demo",
                            ticket=["GH-1, GH-2", "gh-1"],
                        )
                    )

                workspace_branch = "scott/feat-demo"
                workspace_dir = paths.workspace_dir_for_branch(
                    project_dir,
                    workspace_branch,
                    workspace_id_for(enlistment_path, workspace_branch),
                )
                user_config = config.load_workspace_user_config(
                    paths.workspace_config_user_path(workspace_dir)
                )
                assert user_config is not None
                assert user_config.tickets.refs == ["GH-1", "GH-2"]
                success_content = (workspace_dir / "SUCCESS.md").read_text(
                    encoding="utf-8"
                )
                assert "## Tickets" in success_content
                assert "- GH-1" in success_content
                assert "- GH-2" in success_content
            finally:
                os.chdir(original_cwd)

    def test_open_uses_ticket_name_for_workspace_when_missing(self) -> None:
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
                commands: list[list[str]] = []
                fake_codex = record_codex_command(commands)
                with (
                    patch("atelier.exec.run_command", lambda *args, **kwargs: None),
                    patch("atelier.codex.run_codex_command", fake_codex),
                    patch("atelier.sessions.find_codex_session", return_value=None),
                    patch("atelier.git.git_current_branch", return_value="main"),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.git.git_is_clean", return_value=True),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    open_cmd.open_workspace(
                        SimpleNamespace(workspace_name=None, ticket=["Fix login!!!"])
                    )

                workspace_branch = "scott/$ticket-fix-login"
                workspace_dir = paths.workspace_dir_for_branch(
                    project_dir,
                    workspace_branch,
                    workspace_id_for(enlistment_path, workspace_branch),
                )
                workspace_config = config.load_workspace_config(
                    paths.workspace_config_path(workspace_dir)
                )
                assert workspace_config is not None
                assert workspace_config.workspace.branch == workspace_branch
            finally:
                os.chdir(original_cwd)

    def test_open_ticket_uses_ticket_success_template_when_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_open_config(
                project_dir,
                enlistment_path,
                tickets={"provider": "github", "default_project": "org/repo"},
            )

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                commands: list[list[str]] = []
                fake_codex = record_codex_command(commands)
                with (
                    patch("atelier.exec.run_command", lambda *args, **kwargs: None),
                    patch("atelier.codex.run_codex_command", fake_codex),
                    patch("atelier.sessions.find_codex_session", return_value=None),
                    patch(
                        "atelier.templates.ticket_success_md_template",
                        return_value=(
                            "Implement ${ticket-provider} ticket ${ticket-id} "
                            "for project ${project-name} to completion.\n"
                        ),
                    ),
                    patch("atelier.git.git_current_branch", return_value="main"),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.git.git_is_clean", return_value=True),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    open_cmd.open_workspace(
                        SimpleNamespace(
                            workspace_name="feat-demo",
                            ticket=["GH-123"],
                        )
                    )

                workspace_branch = "scott/feat-demo"
                workspace_dir = paths.workspace_dir_for_branch(
                    project_dir,
                    workspace_branch,
                    workspace_id_for(enlistment_path, workspace_branch),
                )
                success_content = (workspace_dir / "SUCCESS.md").read_text(
                    encoding="utf-8"
                )
                assert (
                    "Implement github ticket GH-123 for project org/repo to completion."
                ) in success_content
            finally:
                os.chdir(original_cwd)

    def test_open_ai_success_uses_ai_draft(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_open_config(
                project_dir,
                enlistment_path,
                tickets={"provider": "github", "default_project": "org/repo"},
                ai={"provider": "openai", "model": "gpt-4o-mini"},
            )

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                commands: list[list[str]] = []
                fake_codex = record_codex_command(commands)
                with (
                    patch("atelier.exec.run_command", lambda *args, **kwargs: None),
                    patch("atelier.codex.run_codex_command", fake_codex),
                    patch("atelier.sessions.find_codex_session", return_value=None),
                    patch(
                        "atelier.ai.draft_success_md",
                        return_value="# Success Contract\n\nAI Draft\n",
                    ),
                    patch("atelier.git.git_current_branch", return_value="main"),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.git.git_is_clean", return_value=True),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    open_cmd.open_workspace(
                        SimpleNamespace(
                            workspace_name="feat-demo",
                            ticket=["GH-123"],
                            ai_success=True,
                        )
                    )

                workspace_branch = "scott/feat-demo"
                workspace_dir = paths.workspace_dir_for_branch(
                    project_dir,
                    workspace_branch,
                    workspace_id_for(enlistment_path, workspace_branch),
                )
                success_content = (workspace_dir / "SUCCESS.md").read_text(
                    encoding="utf-8"
                )
                assert "AI Draft" in success_content
            finally:
                os.chdir(original_cwd)

    def test_open_ai_branch_uses_ai_suggestion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_open_config(
                project_dir,
                enlistment_path,
                ai={"provider": "openai", "model": "gpt-4o-mini"},
            )

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                commands: list[list[str]] = []
                fake_codex = record_codex_command(commands)
                with (
                    patch("atelier.exec.run_command", lambda *args, **kwargs: None),
                    patch("atelier.codex.run_codex_command", fake_codex),
                    patch("atelier.sessions.find_codex_session", return_value=None),
                    patch(
                        "atelier.ai.suggest_branch_names",
                        return_value=["Fix login flow"],
                    ),
                    patch("atelier.git.git_current_branch", return_value="main"),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.git.git_is_clean", return_value=True),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    open_cmd.open_workspace(
                        SimpleNamespace(
                            workspace_name=None,
                            ticket=["GH-123"],
                            ai_branch=True,
                        )
                    )

                workspace_branch = "scott/$ticket-fix-login-flow"
                workspace_dir = paths.workspace_dir_for_branch(
                    project_dir,
                    workspace_branch,
                    workspace_id_for(enlistment_path, workspace_branch),
                )
                workspace_config = config.load_workspace_config(
                    paths.workspace_config_path(workspace_dir)
                )
                assert workspace_config is not None
                assert workspace_config.workspace.branch == workspace_branch
            finally:
                os.chdir(original_cwd)

    def test_open_yolo_passes_through_to_codex(self) -> None:
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
                commands: list[list[str]] = []
                fake_codex = record_codex_command(commands)

                def fake_run(
                    cmd: list[str],
                    cwd: Path | None = None,
                    env: dict[str, str] | None = None,
                ) -> None:
                    commands.append(cmd)

                with (
                    patch("atelier.exec.run_command", fake_run),
                    patch("atelier.codex.run_codex_command", fake_codex),
                    patch("atelier.sessions.find_codex_session", return_value=None),
                    patch("atelier.git.git_current_branch", return_value="main"),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.git.git_is_clean", return_value=True),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    open_cmd.open_workspace(
                        SimpleNamespace(workspace_name="feat-demo", yolo=True)
                    )

                codex_commands = [cmd for cmd in commands if cmd and cmd[0] == "codex"]
                assert codex_commands
                assert any("--yolo" in cmd for cmd in codex_commands)
            finally:
                os.chdir(original_cwd)

    def test_open_prefers_stored_codex_session_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_open_config(project_dir, enlistment_path)

            workspace_branch = "scott/feat-demo"
            workspace_dir = paths.workspace_dir_for_branch(
                project_dir,
                workspace_branch,
                workspace_id_for(enlistment_path, workspace_branch),
            )
            workspace_dir.mkdir(parents=True, exist_ok=True)
            write_workspace_config(
                workspace_dir,
                workspace_branch,
                enlistment_path,
                session={"agent": "codex", "id": "sess-123"},
            )
            (workspace_dir / "AGENTS.md").write_text("stub\n", encoding="utf-8")

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                commands: list[list[str]] = []
                fake_codex = record_codex_command(commands)

                def fake_run(
                    cmd: list[str],
                    cwd: Path | None = None,
                    env: dict[str, str] | None = None,
                ) -> None:
                    commands.append(cmd)

                with (
                    patch("atelier.exec.run_command", fake_run),
                    patch("atelier.codex.run_codex_command", fake_codex),
                    patch("atelier.sessions.find_codex_session") as find_session,
                    patch("atelier.git.git_current_branch", return_value="main"),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.git.git_is_clean", return_value=True),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    open_cmd.open_workspace(SimpleNamespace(workspace_name="feat-demo"))

                assert not find_session.called
                assert any(
                    cmd[:2] == ["codex", "--cd"]
                    and "resume" in cmd
                    and "sess-123" in cmd
                    for cmd in commands
                )
            finally:
                os.chdir(original_cwd)

    def test_open_resumes_claude_with_continue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_open_config(
                project_dir,
                enlistment_path,
                agent={
                    "default": "claude",
                    "options": {"claude": ["--model", "sonnet"]},
                },
            )

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                commands: list[list[str]] = []
                fake_codex = record_codex_command(commands)
                status_calls: list[list[str]] = []

                def fake_run(
                    cmd: list[str],
                    cwd: Path | None = None,
                    env: dict[str, str] | None = None,
                ) -> None:
                    commands.append(cmd)

                def fake_status(
                    cmd: list[str],
                    cwd: Path | None = None,
                    env: dict[str, str] | None = None,
                ) -> DummyResult:
                    status_calls.append(cmd)
                    return DummyResult(returncode=0)

                with (
                    patch("atelier.exec.run_command", fake_run),
                    patch("atelier.codex.run_codex_command", fake_codex),
                    patch("atelier.exec.run_command_status", fake_status),
                    patch("atelier.git.git_current_branch", return_value="main"),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.git.git_is_clean", return_value=True),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    open_cmd.open_workspace(SimpleNamespace(workspace_name="feat-demo"))

                assert status_calls == [["claude", "--model", "sonnet", "--continue"]]
                assert not any(cmd and cmd[0] == "claude" for cmd in commands)
            finally:
                os.chdir(original_cwd)

    def test_open_rejects_default_branch_without_new_flag(self) -> None:
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
                with (
                    patch("atelier.exec.run_command", lambda *_args, **_kw: None),
                    patch("atelier.codex.run_codex_command", fake_codex),
                    patch("atelier.sessions.find_codex_session", return_value=None),
                    patch("atelier.git.git_current_branch", return_value="main"),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.git.git_is_clean", return_value=True),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    with pytest.raises(SystemExit):
                        open_cmd.open_workspace(
                            SimpleNamespace(
                                workspace_name="main",
                                raw=True,
                                branch_pr=None,
                                branch_history=None,
                                yolo=False,
                            )
                        )
            finally:
                os.chdir(original_cwd)

    def test_open_allows_default_branch_with_new_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_open_config(
                project_dir,
                enlistment_path,
                project={"allow_mainline_workspace": True},
            )

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                commands: list[list[str]] = []

                def fake_run(
                    cmd: list[str],
                    cwd: Path | None = None,
                    env: dict[str, str] | None = None,
                ) -> None:
                    commands.append(cmd)

                with (
                    patch("atelier.exec.run_command", fake_run),
                    patch("atelier.codex.run_codex_command", fake_codex),
                    patch("atelier.sessions.find_codex_session", return_value=None),
                    patch("atelier.git.git_current_branch", return_value="main"),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.git.git_is_clean", return_value=True),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    open_cmd.open_workspace(
                        SimpleNamespace(
                            workspace_name="main",
                            raw=True,
                            branch_pr=None,
                            branch_history=None,
                            yolo=False,
                        )
                    )

                assert any(cmd[:2] == ["git", "clone"] for cmd in commands)
            finally:
                os.chdir(original_cwd)

    def test_open_resumes_gemini_with_resume_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_open_config(
                project_dir,
                enlistment_path,
                agent={
                    "default": "gemini",
                    "options": {"gemini": ["--model", "flash"]},
                },
            )

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                commands: list[list[str]] = []
                fake_codex = record_codex_command(commands)
                status_calls: list[list[str]] = []

                def fake_run(
                    cmd: list[str],
                    cwd: Path | None = None,
                    env: dict[str, str] | None = None,
                ) -> None:
                    commands.append(cmd)

                def fake_status(
                    cmd: list[str],
                    cwd: Path | None = None,
                    env: dict[str, str] | None = None,
                ) -> DummyResult:
                    status_calls.append(cmd)
                    return DummyResult(returncode=0)

                with (
                    patch(
                        "atelier.agents.available_agent_names",
                        return_value=("codex", "claude", "gemini"),
                    ),
                    patch("atelier.exec.run_command", fake_run),
                    patch("atelier.codex.run_codex_command", fake_codex),
                    patch("atelier.exec.run_command_status", fake_status),
                    patch("atelier.git.git_current_branch", return_value="main"),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.git.git_is_clean", return_value=True),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    open_cmd.open_workspace(SimpleNamespace(workspace_name="feat-demo"))

                assert status_calls == [["gemini", "--model", "flash", "--resume"]]
                assert not any(cmd and cmd[0] == "gemini" for cmd in commands)
            finally:
                os.chdir(original_cwd)

    def test_open_starts_gemini_without_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_open_config(
                project_dir,
                enlistment_path,
                agent={
                    "default": "gemini",
                    "options": {"gemini": ["--model", "flash"]},
                },
            )

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                commands: list[list[str]] = []
                fake_codex = record_codex_command(commands)

                def fake_run(
                    cmd: list[str],
                    cwd: Path | None = None,
                    env: dict[str, str] | None = None,
                ) -> None:
                    commands.append(cmd)

                def fake_status(
                    cmd: list[str],
                    cwd: Path | None = None,
                    env: dict[str, str] | None = None,
                ) -> DummyResult:
                    return DummyResult(returncode=1)

                with (
                    patch(
                        "atelier.agents.available_agent_names",
                        return_value=("codex", "claude", "gemini"),
                    ),
                    patch("atelier.exec.run_command", fake_run),
                    patch("atelier.codex.run_codex_command", fake_codex),
                    patch("atelier.exec.run_command_status", fake_status),
                    patch("atelier.git.git_current_branch", return_value="main"),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.git.git_is_clean", return_value=True),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    open_cmd.open_workspace(SimpleNamespace(workspace_name="feat-demo"))

                expected = ["gemini", "--model", "flash"]
                gemini_commands = [
                    cmd for cmd in commands if cmd and cmd[0] == "gemini"
                ]
                assert gemini_commands == [expected]
            finally:
                os.chdir(original_cwd)

    def test_open_resumes_aider_with_chat_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_open_config(
                project_dir,
                enlistment_path,
                agent={
                    "default": "aider",
                    "options": {"aider": ["--model", "gpt-4"]},
                },
            )

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                commands: list[list[str]] = []
                fake_codex = record_codex_command(commands)
                status_calls: list[list[str]] = []

                def fake_run(
                    cmd: list[str],
                    cwd: Path | None = None,
                    env: dict[str, str] | None = None,
                ) -> None:
                    commands.append(cmd)

                def fake_status(
                    cmd: list[str],
                    cwd: Path | None = None,
                    env: dict[str, str] | None = None,
                ) -> DummyResult:
                    status_calls.append(cmd)
                    return DummyResult(returncode=0)

                with (
                    patch(
                        "atelier.agents.available_agent_names",
                        return_value=("codex", "claude", "aider"),
                    ),
                    patch(
                        "atelier.agents.aider_chat_history_path",
                        return_value=Path("/tmp/aider.chat.history.md"),
                    ),
                    patch("atelier.exec.run_command", fake_run),
                    patch("atelier.codex.run_codex_command", fake_codex),
                    patch("atelier.exec.run_command_status", fake_status),
                    patch("atelier.git.git_current_branch", return_value="main"),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.git.git_is_clean", return_value=True),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    open_cmd.open_workspace(SimpleNamespace(workspace_name="feat-demo"))

                assert status_calls == [
                    ["aider", "--model", "gpt-4", "--restore-chat-history"]
                ]
                assert not any(cmd and cmd[0] == "aider" for cmd in commands)
            finally:
                os.chdir(original_cwd)

    def test_open_starts_aider_without_prompt_when_no_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_open_config(
                project_dir,
                enlistment_path,
                agent={
                    "default": "aider",
                    "options": {"aider": ["--model", "gpt-4"]},
                },
            )

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                commands: list[list[str]] = []
                fake_codex = record_codex_command(commands)
                status_calls: list[list[str]] = []

                def fake_run(
                    cmd: list[str],
                    cwd: Path | None = None,
                    env: dict[str, str] | None = None,
                ) -> None:
                    commands.append(cmd)

                def fake_status(
                    cmd: list[str],
                    cwd: Path | None = None,
                    env: dict[str, str] | None = None,
                ) -> DummyResult:
                    status_calls.append(cmd)
                    return DummyResult(returncode=1)

                with (
                    patch(
                        "atelier.agents.available_agent_names",
                        return_value=("codex", "claude", "aider"),
                    ),
                    patch("atelier.agents.aider_chat_history_path", return_value=None),
                    patch("atelier.exec.run_command", fake_run),
                    patch("atelier.codex.run_codex_command", fake_codex),
                    patch("atelier.exec.run_command_status", fake_status),
                    patch("atelier.git.git_current_branch", return_value="main"),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.git.git_is_clean", return_value=True),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    open_cmd.open_workspace(SimpleNamespace(workspace_name="feat-demo"))

                assert status_calls == []
                aider_commands = [cmd for cmd in commands if cmd and cmd[0] == "aider"]
                assert aider_commands == [["aider", "--model", "gpt-4"]]
            finally:
                os.chdir(original_cwd)

    def test_open_auto_upgrades_project_templates_with_always_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )

            project_dir.mkdir(parents=True, exist_ok=True)
            templates_dir = project_dir / "templates"
            templates_dir.mkdir(parents=True, exist_ok=True)

            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                canonical = templates.agents_template(prefer_installed=True)
            old_text = f"{canonical}\nlegacy\n"
            (templates_dir / "AGENTS.md").write_text(old_text, encoding="utf-8")

            payload = make_open_config(enlistment_path)
            payload["atelier"]["version"] = "9999.0.0"
            payload["atelier"]["upgrade"] = "always"
            payload["atelier"]["managed_files"] = {
                "templates/AGENTS.md": config.hash_text(old_text),
            }
            parsed = config.ProjectConfig.model_validate(payload)
            config.write_project_config(paths.project_config_path(project_dir), parsed)

            original_cwd = Path.cwd()
            os.chdir(root)
            try:

                def fake_run(
                    cmd: list[str],
                    cwd: Path | None = None,
                    env: dict[str, str] | None = None,
                ) -> None:
                    return None

                with (
                    patch("atelier.exec.run_command", fake_run),
                    patch("atelier.codex.run_codex_command", fake_codex),
                    patch("atelier.sessions.find_codex_session", return_value=None),
                    patch("atelier.git.git_current_branch", return_value="main"),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.git.git_is_clean", return_value=True),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    open_cmd.open_workspace(SimpleNamespace(workspace_name="feat-demo"))
            finally:
                os.chdir(original_cwd)

            updated = (templates_dir / "AGENTS.md").read_text(encoding="utf-8")
            assert updated == canonical

    def test_open_ask_policy_updates_when_confirmed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )

            project_dir.mkdir(parents=True, exist_ok=True)
            templates_dir = project_dir / "templates"
            templates_dir.mkdir(parents=True, exist_ok=True)

            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                canonical = templates.agents_template(prefer_installed=True)
            old_text = f"{canonical}\nlegacy\n"
            (templates_dir / "AGENTS.md").write_text(old_text, encoding="utf-8")

            payload = make_open_config(enlistment_path)
            payload["atelier"]["version"] = "9999.0.0"
            payload["atelier"]["upgrade"] = "ask"
            payload["atelier"]["managed_files"] = {
                "templates/AGENTS.md": config.hash_text(old_text),
            }
            parsed = config.ProjectConfig.model_validate(payload)
            config.write_project_config(paths.project_config_path(project_dir), parsed)

            original_cwd = Path.cwd()
            os.chdir(root)
            try:

                def fake_run(
                    cmd: list[str],
                    cwd: Path | None = None,
                    env: dict[str, str] | None = None,
                ) -> None:
                    return None

                with (
                    patch("atelier.exec.run_command", fake_run),
                    patch("atelier.codex.run_codex_command", fake_codex),
                    patch("atelier.sessions.find_codex_session", return_value=None),
                    patch("atelier.git.git_current_branch", return_value="main"),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.git.git_is_clean", return_value=True),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                    patch("builtins.input", return_value="y"),
                ):
                    open_cmd.open_workspace(SimpleNamespace(workspace_name="feat-demo"))
            finally:
                os.chdir(original_cwd)

            updated = (templates_dir / "AGENTS.md").read_text(encoding="utf-8")
            assert updated == canonical

    def test_open_with_prefixed_branch_does_not_double_prefix(self) -> None:
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
                commands: list[list[str]] = []
                fake_codex = record_codex_command(commands)

                def fake_run(
                    cmd: list[str],
                    cwd: Path | None = None,
                    env: dict[str, str] | None = None,
                ) -> None:
                    commands.append(cmd)

                with (
                    patch("atelier.exec.run_command", fake_run),
                    patch("atelier.codex.run_codex_command", fake_codex),
                    patch("atelier.sessions.find_codex_session", return_value=None),
                    patch("atelier.git.git_current_branch", return_value="main"),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.git.git_is_clean", return_value=True),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    open_cmd.open_workspace(
                        SimpleNamespace(workspace_name="scott/feat-demo")
                    )

                workspace_branch = "scott/feat-demo"
                workspace_dir = paths.workspace_dir_for_branch(
                    project_dir,
                    workspace_branch,
                    workspace_id_for(enlistment_path, workspace_branch),
                )
                workspace_config = config.load_workspace_config(
                    paths.workspace_config_path(workspace_dir)
                )
                assert workspace_config is not None
                assert workspace_config.workspace.branch == workspace_branch
                assert not (
                    paths.workspace_dir_for_branch(
                        project_dir,
                        "scott/scott/feat-demo",
                        workspace_id_for(enlistment_path, "scott/scott/feat-demo"),
                    ).exists()
                )
                assert any(cmd[:2] == ["git", "clone"] for cmd in commands)
            finally:
                os.chdir(original_cwd)

    def test_open_prefers_exact_branch_match_over_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo_root = init_local_repo_without_feature(root)
            subprocess.run(
                ["git", "-C", str(repo_root), "checkout", "-b", "feature/demo"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(repo_root), "checkout", "main"], check=True
            )
            enlistment_path = enlistment_path_for(repo_root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_open_config(project_dir, enlistment_path)

            original_cwd = Path.cwd()
            os.chdir(repo_root)
            try:
                commands: list[list[str]] = []
                fake_codex = record_codex_command(commands)

                def fake_run(
                    cmd: list[str],
                    cwd: Path | None = None,
                    env: dict[str, str] | None = None,
                ) -> None:
                    commands.append(cmd)

                with (
                    patch("atelier.exec.run_command", fake_run),
                    patch("atelier.codex.run_codex_command", fake_codex),
                    patch("atelier.sessions.find_codex_session", return_value=None),
                    patch("atelier.git.git_current_branch", return_value="main"),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.git.git_is_clean", return_value=True),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    open_cmd.open_workspace(
                        SimpleNamespace(workspace_name="feature/demo")
                    )

                workspace_branch = "feature/demo"
                workspace_dir = paths.workspace_dir_for_branch(
                    project_dir,
                    workspace_branch,
                    workspace_id_for(enlistment_path, workspace_branch),
                )
                workspace_config = config.load_workspace_config(
                    paths.workspace_config_path(workspace_dir)
                )
                assert workspace_config is not None
                assert workspace_config.workspace.branch == workspace_branch
                assert not (
                    paths.workspace_dir_for_branch(
                        project_dir,
                        "scott/feature/demo",
                        workspace_id_for(enlistment_path, "scott/feature/demo"),
                    ).exists()
                )
                assert any(cmd[:2] == ["git", "clone"] for cmd in commands)
            finally:
                os.chdir(original_cwd)

    def test_open_without_name_uses_current_branch_when_clean_and_pushed(self) -> None:
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
                commands: list[list[str]] = []
                fake_codex = record_codex_command(commands)

                def fake_run(
                    cmd: list[str],
                    cwd: Path | None = None,
                    env: dict[str, str] | None = None,
                ) -> None:
                    commands.append(cmd)

                def fake_current_branch(
                    repo_dir: Path, *, git_path: str | None = None
                ) -> str | None:
                    if repo_dir == root:
                        return "feature/demo"
                    return "main"

                with (
                    patch("atelier.exec.run_command", fake_run),
                    patch("atelier.codex.run_codex_command", fake_codex),
                    patch("atelier.sessions.find_codex_session", return_value=None),
                    patch("atelier.git.git_current_branch", fake_current_branch),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.git.git_is_clean", return_value=True),
                    patch("atelier.git.git_branch_fully_pushed", return_value=True),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    open_cmd.open_workspace(SimpleNamespace(workspace_name=None))

                workspace_branch = "feature/demo"
                workspace_dir = paths.workspace_dir_for_branch(
                    project_dir,
                    workspace_branch,
                    workspace_id_for(enlistment_path, workspace_branch),
                )
                workspace_config = config.load_workspace_config(
                    paths.workspace_config_path(workspace_dir)
                )
                assert workspace_config is not None
                assert workspace_config.workspace.branch == workspace_branch
                assert any(cmd[0] == "codex" for cmd in commands)
            finally:
                os.chdir(original_cwd)

    def test_open_edits_agents_after_clone_when_repo_missing(self) -> None:
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
                commands: list[list[str]] = []
                fake_codex = record_codex_command(commands)

                def fake_run(
                    cmd: list[str],
                    cwd: Path | None = None,
                    env: dict[str, str] | None = None,
                ) -> None:
                    commands.append(cmd)

                with (
                    patch("atelier.exec.run_command", fake_run),
                    patch("atelier.codex.run_codex_command", fake_codex),
                    patch("atelier.sessions.find_codex_session", return_value=None),
                    patch("atelier.git.git_is_repo", return_value=True),
                    patch("atelier.git.git_current_branch", return_value="main"),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.git.git_is_clean", return_value=True),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    open_cmd.open_workspace(SimpleNamespace(workspace_name="feat-demo"))

                editor_index = next(
                    index for index, cmd in enumerate(commands) if cmd[:1] == ["true"]
                )
                clone_index = next(
                    index
                    for index, cmd in enumerate(commands)
                    if cmd[:2] == ["git", "clone"]
                )
                assert clone_index < editor_index
            finally:
                os.chdir(original_cwd)

    def test_open_editor_uses_workspace_relative_workspace_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data dir"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_open_config(project_dir, enlistment_path)

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                commands: list[list[str]] = []
                fake_codex = record_codex_command(commands)
                cwds: list[Path | None] = []

                def fake_run(
                    cmd: list[str],
                    cwd: Path | None = None,
                    env: dict[str, str] | None = None,
                ) -> None:
                    commands.append(cmd)
                    cwds.append(cwd)

                with (
                    patch("atelier.exec.run_command", fake_run),
                    patch("atelier.codex.run_codex_command", fake_codex),
                    patch("atelier.sessions.find_codex_session", return_value=None),
                    patch("atelier.git.git_is_repo", return_value=True),
                    patch("atelier.git.git_current_branch", return_value="main"),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.git.git_is_clean", return_value=True),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    open_cmd.open_workspace(SimpleNamespace(workspace_name="feat-demo"))

                editor_index = next(
                    index for index, cmd in enumerate(commands) if cmd[:1] == ["true"]
                )
                assert commands[editor_index][-1] == "SUCCESS.md"
                workspace_dir = paths.workspace_dir_for_branch(
                    project_dir,
                    "scott/feat-demo",
                    workspace_id_for(enlistment_path, "scott/feat-demo"),
                )
                assert cwds[editor_index] == workspace_dir
            finally:
                os.chdir(original_cwd)

    def test_open_edits_success_when_repo_exists_for_new_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_open_config(project_dir, enlistment_path)

            workspace_branch = "scott/feat-demo"
            workspace_dir = paths.workspace_dir_for_branch(
                project_dir,
                workspace_branch,
                workspace_id_for(enlistment_path, workspace_branch),
            )
            repo_dir = workspace_dir / "repo"
            repo_dir.mkdir(parents=True)
            subprocess.run(["git", "-C", str(repo_dir), "init"], check=True)
            subprocess.run(
                ["git", "-C", str(repo_dir), "remote", "add", "origin", RAW_ORIGIN],
                check=True,
            )

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                commands: list[list[str]] = []
                fake_codex = record_codex_command(commands)

                def fake_run(
                    cmd: list[str],
                    cwd: Path | None = None,
                    env: dict[str, str] | None = None,
                ) -> None:
                    commands.append(cmd)

                with (
                    patch("atelier.exec.run_command", fake_run),
                    patch("atelier.codex.run_codex_command", fake_codex),
                    patch("atelier.sessions.find_codex_session", return_value=None),
                    patch("atelier.git.git_current_branch", return_value="main"),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.git.git_is_clean", return_value=True),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    open_cmd.open_workspace(SimpleNamespace(workspace_name="feat-demo"))

                assert any(cmd[:1] == ["true"] for cmd in commands)
            finally:
                os.chdir(original_cwd)

    def test_open_skips_editor_when_no_edit_for_new_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_open_config(project_dir, enlistment_path)

            workspace_branch = "scott/feat-demo"
            workspace_dir = paths.workspace_dir_for_branch(
                project_dir,
                workspace_branch,
                workspace_id_for(enlistment_path, workspace_branch),
            )
            repo_dir = workspace_dir / "repo"
            repo_dir.mkdir(parents=True)
            subprocess.run(["git", "-C", str(repo_dir), "init"], check=True)
            subprocess.run(
                ["git", "-C", str(repo_dir), "remote", "add", "origin", RAW_ORIGIN],
                check=True,
            )

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                commands: list[list[str]] = []
                fake_codex = record_codex_command(commands)

                def fake_run(
                    cmd: list[str],
                    cwd: Path | None = None,
                    env: dict[str, str] | None = None,
                ) -> None:
                    commands.append(cmd)

                with (
                    patch("atelier.exec.run_command", fake_run),
                    patch("atelier.codex.run_codex_command", fake_codex),
                    patch("atelier.sessions.find_codex_session", return_value=None),
                    patch("atelier.git.git_current_branch", return_value="main"),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.git.git_is_clean", return_value=True),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    open_cmd.open_workspace(
                        SimpleNamespace(workspace_name="feat-demo", edit=False)
                    )

                assert not any(cmd[:1] == ["true"] for cmd in commands)
            finally:
                os.chdir(original_cwd)

    def test_open_skips_editor_when_repo_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            config_payload = write_open_config(project_dir, enlistment_path)

            workspace_branch = "scott/feat-demo"
            workspace_dir = paths.workspace_dir_for_branch(
                project_dir,
                workspace_branch,
                workspace_id_for(enlistment_path, workspace_branch),
            )
            repo_dir = workspace_dir / "repo"
            repo_dir.mkdir(parents=True)
            subprocess.run(["git", "-C", str(repo_dir), "init"], check=True)
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo_dir),
                    "remote",
                    "add",
                    "origin",
                    config_payload["project"]["repo_url"],
                ],
                check=True,
            )
            (workspace_dir / "AGENTS.md").write_text("stub\n", encoding="utf-8")
            write_workspace_config(workspace_dir, workspace_branch, enlistment_path)

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                commands: list[list[str]] = []
                fake_codex = record_codex_command(commands)

                def fake_run(
                    cmd: list[str],
                    cwd: Path | None = None,
                    env: dict[str, str] | None = None,
                ) -> None:
                    commands.append(cmd)

                with (
                    patch("atelier.exec.run_command", fake_run),
                    patch("atelier.codex.run_codex_command", fake_codex),
                    patch("atelier.sessions.find_codex_session", return_value=None),
                    patch("atelier.git.git_current_branch", return_value="main"),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.git.git_is_clean", return_value=True),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    open_cmd.open_workspace(SimpleNamespace(workspace_name="feat-demo"))

                assert not any(cmd[:1] == ["true"] for cmd in commands)
            finally:
                os.chdir(original_cwd)

    def test_open_opens_editor_with_edit_for_existing_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            config_payload = write_open_config(project_dir, enlistment_path)

            workspace_branch = "scott/feat-demo"
            workspace_dir = paths.workspace_dir_for_branch(
                project_dir,
                workspace_branch,
                workspace_id_for(enlistment_path, workspace_branch),
            )
            repo_dir = workspace_dir / "repo"
            repo_dir.mkdir(parents=True)
            subprocess.run(["git", "-C", str(repo_dir), "init"], check=True)
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo_dir),
                    "remote",
                    "add",
                    "origin",
                    config_payload["project"]["repo_url"],
                ],
                check=True,
            )
            (workspace_dir / "AGENTS.md").write_text("stub\n", encoding="utf-8")
            (workspace_dir / "SUCCESS.md").write_text("policy\n", encoding="utf-8")
            write_workspace_config(workspace_dir, workspace_branch, enlistment_path)

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                commands: list[list[str]] = []
                fake_codex = record_codex_command(commands)

                def fake_run(
                    cmd: list[str],
                    cwd: Path | None = None,
                    env: dict[str, str] | None = None,
                ) -> None:
                    commands.append(cmd)

                with (
                    patch("atelier.exec.run_command", fake_run),
                    patch("atelier.codex.run_codex_command", fake_codex),
                    patch("atelier.sessions.find_codex_session", return_value=None),
                    patch("atelier.git.git_current_branch", return_value="main"),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.git.git_is_clean", return_value=True),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    open_cmd.open_workspace(
                        SimpleNamespace(workspace_name="feat-demo", edit=True)
                    )

                editor_cmd = next(cmd for cmd in commands if cmd[:1] == ["true"])
                assert editor_cmd[-1] == "SUCCESS.md"
            finally:
                os.chdir(original_cwd)

    def test_open_edit_uses_legacy_workspace_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            config_payload = write_open_config(project_dir, enlistment_path)

            workspace_branch = "scott/feat-demo"
            workspace_dir = paths.workspace_dir_for_branch(
                project_dir,
                workspace_branch,
                workspace_id_for(enlistment_path, workspace_branch),
            )
            repo_dir = workspace_dir / "repo"
            repo_dir.mkdir(parents=True)
            subprocess.run(["git", "-C", str(repo_dir), "init"], check=True)
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo_dir),
                    "remote",
                    "add",
                    "origin",
                    config_payload["project"]["repo_url"],
                ],
                check=True,
            )
            (workspace_dir / "AGENTS.md").write_text("stub\n", encoding="utf-8")
            (workspace_dir / "WORKSPACE.md").write_text("legacy\n", encoding="utf-8")
            write_workspace_config(workspace_dir, workspace_branch, enlistment_path)

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                commands: list[list[str]] = []
                fake_codex = record_codex_command(commands)

                def fake_run(
                    cmd: list[str],
                    cwd: Path | None = None,
                    env: dict[str, str] | None = None,
                ) -> None:
                    commands.append(cmd)

                with (
                    patch("atelier.exec.run_command", fake_run),
                    patch("atelier.codex.run_codex_command", fake_codex),
                    patch("atelier.sessions.find_codex_session", return_value=None),
                    patch("atelier.git.git_current_branch", return_value="main"),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.git.git_is_clean", return_value=True),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    open_cmd.open_workspace(
                        SimpleNamespace(workspace_name="feat-demo", edit=True)
                    )

                editor_cmd = next(cmd for cmd in commands if cmd[:1] == ["true"])
                assert editor_cmd[-1] == "WORKSPACE.md"
                assert not (workspace_dir / "SUCCESS.md").exists()
            finally:
                os.chdir(original_cwd)

    def test_open_skips_editor_when_success_md_missing_for_existing_workspace(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_origin(NORMALIZED_ORIGIN)
            write_open_config(project_dir, enlistment_path)

            workspace_branch = "scott/feat-demo"
            workspace_dir = paths.workspace_dir_for_branch(
                project_dir,
                workspace_branch,
                workspace_id_for(enlistment_path, workspace_branch),
            )
            workspace_dir.mkdir(parents=True)
            write_workspace_config(workspace_dir, workspace_branch, enlistment_path)
            (workspace_dir / "AGENTS.md").write_text("stub\n", encoding="utf-8")

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                commands: list[list[str]] = []
                fake_codex = record_codex_command(commands)

                def fake_run(
                    cmd: list[str],
                    cwd: Path | None = None,
                    env: dict[str, str] | None = None,
                ) -> None:
                    commands.append(cmd)

                with (
                    patch("atelier.exec.run_command", fake_run),
                    patch("atelier.codex.run_codex_command", fake_codex),
                    patch("atelier.sessions.find_codex_session", return_value=None),
                    patch("atelier.git.git_current_branch", return_value="main"),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.git.git_is_clean", return_value=True),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    open_cmd.open_workspace(SimpleNamespace(workspace_name="feat-demo"))

                assert not (workspace_dir / "SUCCESS.md").exists()
                assert not (project_dir / "templates").exists()
                assert not any(cmd[:1] == ["true"] for cmd in commands)
            finally:
                os.chdir(original_cwd)

    def test_open_skips_default_checkout_with_dirty_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            config_payload = write_open_config(project_dir, enlistment_path)

            workspace_branch = "scott/feat-demo"
            workspace_dir = paths.workspace_dir_for_branch(
                project_dir,
                workspace_branch,
                workspace_id_for(enlistment_path, workspace_branch),
            )
            repo_dir = workspace_dir / "repo"
            repo_dir.mkdir(parents=True)
            subprocess.run(["git", "-C", str(repo_dir), "init"], check=True)
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo_dir),
                    "config",
                    "user.email",
                    "test@example.com",
                ],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(repo_dir), "config", "user.name", "Test User"],
                check=True,
            )
            (repo_dir / "README.md").write_text("base\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo_dir), "add", "README.md"], check=True)
            subprocess.run(
                ["git", "-C", str(repo_dir), "commit", "-m", "chore: init"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(repo_dir), "branch", "-M", "main"], check=True
            )
            subprocess.run(
                ["git", "-C", str(repo_dir), "checkout", "-b", "scott/feat-demo"],
                check=True,
            )
            (repo_dir / "dirty.txt").write_text("dirty\n", encoding="utf-8")
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo_dir),
                    "remote",
                    "add",
                    "origin",
                    config_payload["project"]["repo_url"],
                ],
                check=True,
            )
            (workspace_dir / "AGENTS.md").write_text("stub\n", encoding="utf-8")
            write_workspace_config(workspace_dir, workspace_branch, enlistment_path)

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                commands: list[list[str]] = []
                fake_codex = record_codex_command(commands)

                def fake_run(
                    cmd: list[str],
                    cwd: Path | None = None,
                    env: dict[str, str] | None = None,
                ) -> None:
                    commands.append(cmd)

                with (
                    patch("atelier.exec.run_command", fake_run),
                    patch("atelier.codex.run_codex_command", fake_codex),
                    patch("atelier.sessions.find_codex_session", return_value=None),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    open_cmd.open_workspace(SimpleNamespace(workspace_name="feat-demo"))

                assert not any(
                    cmd == ["git", "-C", str(repo_dir), "checkout", "main"]
                    for cmd in commands
                )
            finally:
                os.chdir(original_cwd)

    def test_open_does_not_modify_existing_workspace_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_open_config(project_dir, enlistment_path)

            workspace_branch = "scott/feat-demo"
            workspace_dir = paths.workspace_dir_for_branch(
                project_dir,
                workspace_branch,
                workspace_id_for(enlistment_path, workspace_branch),
            )
            workspace_dir.mkdir(parents=True)
            payload = {
                "workspace": {
                    "branch": workspace_branch,
                    "branch_pr": False,
                    "branch_history": "squash",
                    "id": workspace_id_for(enlistment_path, workspace_branch),
                },
                "atelier": {
                    "version": atelier.__version__,
                    "created_at": "2026-01-01T00:00:00Z",
                    "upgrade": "ask",
                },
            }
            parsed = config.WorkspaceConfig.model_validate(payload)
            config.write_workspace_config(
                paths.workspace_config_path(workspace_dir), parsed
            )
            agents_path = workspace_dir / "AGENTS.md"
            workspace_path = workspace_dir / "SUCCESS.md"
            agents_path.write_text("agents stub\n", encoding="utf-8")
            workspace_path.write_text("workspace stub\n", encoding="utf-8")
            os.utime(agents_path, (1_000_000_000, 1_000_000_000))
            os.utime(workspace_path, (1_000_000_000, 1_000_000_000))
            repo_dir = workspace_dir / "repo"
            repo_dir.mkdir()

            original_cwd = Path.cwd()
            os.chdir(root)
            try:

                def fake_run(
                    cmd: list[str],
                    cwd: Path | None = None,
                    env: dict[str, str] | None = None,
                ) -> None:
                    return None

                with (
                    patch("atelier.exec.run_command", fake_run),
                    patch("atelier.codex.run_codex_command", fake_codex),
                    patch("atelier.sessions.find_codex_session", return_value=None),
                    patch(
                        "atelier.commands.open.subprocess.run",
                        return_value=DummyResult(stdout=RAW_ORIGIN),
                    ),
                    patch(
                        "atelier.commands.open.workspace.resolve_workspace_target",
                        return_value=(workspace_branch, workspace_dir, True),
                    ),
                    patch("atelier.git.git_is_repo", return_value=True),
                    patch("atelier.git.git_current_branch", return_value="main"),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.git.git_is_clean", return_value=True),
                    patch("atelier.git.git_tag_exists", return_value=False),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    open_cmd.open_workspace(SimpleNamespace(workspace_name="feat-demo"))

                assert agents_path.read_text(encoding="utf-8") == "agents stub\n"
                assert workspace_path.read_text(encoding="utf-8") == "workspace stub\n"
                assert int(agents_path.stat().st_mtime) == 1_000_000_000
                assert int(workspace_path.stat().st_mtime) == 1_000_000_000
                persist_content = (workspace_dir / "PERSIST.md").read_text(
                    encoding="utf-8"
                )
                assert "Pull requests expected: no" in persist_content
                assert "History policy: squash" in persist_content
                assert not (workspace_dir / "BACKGROUND.md").exists()
            finally:
                os.chdir(original_cwd)

    def test_open_backfills_missing_managed_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_open_config(project_dir, enlistment_path)

            workspace_branch = "scott/feat-demo"
            workspace_dir = paths.workspace_dir_for_branch(
                project_dir,
                workspace_branch,
                workspace_id_for(enlistment_path, workspace_branch),
            )
            workspace_dir.mkdir(parents=True)
            write_workspace_config(workspace_dir, workspace_branch, enlistment_path)
            success_path = workspace_dir / "SUCCESS.md"
            success_path.write_text("workspace stub\n", encoding="utf-8")
            repo_dir = workspace_dir / "repo"
            repo_dir.mkdir()

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                commands: list[list[str]] = []
                fake_codex = record_codex_command(commands)

                def fake_run(
                    cmd: list[str],
                    cwd: Path | None = None,
                    env: dict[str, str] | None = None,
                ) -> None:
                    return None

                with (
                    patch("atelier.exec.run_command", fake_run),
                    patch("atelier.codex.run_codex_command", fake_codex),
                    patch("atelier.sessions.find_codex_session", return_value=None),
                    patch(
                        "atelier.commands.open.subprocess.run",
                        return_value=DummyResult(stdout=RAW_ORIGIN),
                    ),
                    patch(
                        "atelier.commands.open.workspace.resolve_workspace_target",
                        return_value=(workspace_branch, workspace_dir, True),
                    ),
                    patch("atelier.git.git_is_repo", return_value=True),
                    patch("atelier.git.git_current_branch", return_value="main"),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.git.git_is_clean", return_value=True),
                    patch("atelier.git.git_tag_exists", return_value=False),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    open_cmd.open_workspace(SimpleNamespace(workspace_name="feat-demo"))

                assert (workspace_dir / "AGENTS.md").exists()
                assert (workspace_dir / "PERSIST.md").exists()
                assert success_path.read_text(encoding="utf-8") == "workspace stub\n"
                agents_content = (workspace_dir / "AGENTS.md").read_text(
                    encoding="utf-8"
                )
                assert "Atelier Agent Contract" in agents_content
                persist_content = (workspace_dir / "PERSIST.md").read_text(
                    encoding="utf-8"
                )
                assert "Pull requests expected: yes" in persist_content
                assert "History policy: manual" in persist_content
            finally:
                os.chdir(original_cwd)

    def test_open_continues_when_finalization_tag_present_and_declined(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_open_config(project_dir, enlistment_path)

            workspace_branch = "scott/feat-demo"
            workspace_dir = paths.workspace_dir_for_branch(
                project_dir,
                workspace_branch,
                workspace_id_for(enlistment_path, workspace_branch),
            )
            (workspace_dir / "repo").mkdir(parents=True)
            write_workspace_config(workspace_dir, workspace_branch, enlistment_path)

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                commands: list[list[str]] = []
                fake_codex = record_codex_command(commands)

                def fake_run(
                    cmd: list[str],
                    cwd: Path | None = None,
                    env: dict[str, str] | None = None,
                ) -> None:
                    commands.append(cmd)

                with (
                    patch("atelier.exec.run_command", fake_run),
                    patch("atelier.codex.run_codex_command", fake_codex),
                    patch("atelier.sessions.find_codex_session", return_value=None),
                    patch(
                        "atelier.commands.open.subprocess.run",
                        return_value=DummyResult(stdout=RAW_ORIGIN),
                    ),
                    patch("atelier.git.git_is_repo", return_value=True),
                    patch("atelier.git.git_current_branch", return_value="main"),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.git.git_is_clean", return_value=True),
                    patch("atelier.git.git_tag_exists", return_value=True),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                    patch("builtins.input", return_value="n"),
                ):
                    open_cmd.open_workspace(SimpleNamespace(workspace_name="feat-demo"))
            finally:
                os.chdir(original_cwd)

            assert any(cmd[0] == "codex" for cmd in commands)

    def test_open_removes_finalization_tag_when_confirmed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_open_config(project_dir, enlistment_path)

            workspace_branch = "scott/feat-demo"
            workspace_dir = paths.workspace_dir_for_branch(
                project_dir,
                workspace_branch,
                workspace_id_for(enlistment_path, workspace_branch),
            )
            repo_dir = workspace_dir / "repo"
            repo_dir.mkdir(parents=True)
            write_workspace_config(workspace_dir, workspace_branch, enlistment_path)

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                commands: list[list[str]] = []
                fake_codex = record_codex_command(commands)
                confirm_calls: list[tuple[str, str]] = []

                def fake_run(
                    cmd: list[str],
                    cwd: Path | None = None,
                    env: dict[str, str] | None = None,
                ) -> None:
                    commands.append(cmd)

                def fake_try(cmd: list[str], cwd: Path | None = None) -> DummyResult:
                    return DummyResult(returncode=0, stdout="")

                def fake_confirm(workspace_branch: str, tag: str) -> bool:
                    confirm_calls.append((workspace_branch, tag))
                    return True

                with (
                    patch("atelier.exec.run_command", fake_run),
                    patch("atelier.codex.run_codex_command", fake_codex),
                    patch("atelier.sessions.find_codex_session", return_value=None),
                    patch(
                        "atelier.commands.open.subprocess.run",
                        return_value=DummyResult(stdout=RAW_ORIGIN),
                    ),
                    patch(
                        "atelier.commands.open.workspace.resolve_workspace_target",
                        return_value=(workspace_branch, workspace_dir, True),
                    ),
                    patch("atelier.git.git_is_repo", return_value=True),
                    patch("atelier.git.git_current_branch", return_value="main"),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.git.git_is_clean", return_value=True),
                    patch.object(open_cmd.git, "git_tag_exists", return_value=True),
                    patch.object(
                        open_cmd,
                        "confirm_remove_finalization_tag",
                        fake_confirm,
                    ),
                    patch.object(open_cmd.exec, "try_run_command", fake_try),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                    patch("builtins.input", return_value="y"),
                ):
                    open_cmd.open_workspace(SimpleNamespace(workspace_name="feat-demo"))
            finally:
                os.chdir(original_cwd)

            finalization_tag = workspace.finalization_tag_name(workspace_branch)
            assert confirm_calls == [(workspace_branch, finalization_tag)]

    def test_open_errors_when_repo_is_not_git_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_open_config(project_dir, enlistment_path)

            workspace_branch = "scott/feat-demo"
            workspace_dir = paths.workspace_dir_for_branch(
                project_dir,
                workspace_branch,
                workspace_id_for(enlistment_path, workspace_branch),
            )
            (workspace_dir / "repo").mkdir(parents=True)

            original_cwd = Path.cwd()
            os.chdir(root)
            try:

                def fake_run(
                    cmd: list[str],
                    cwd: Path | None = None,
                    env: dict[str, str] | None = None,
                ) -> None:
                    return None

                with (
                    patch("atelier.exec.run_command", fake_run),
                    patch("atelier.codex.run_codex_command", fake_codex),
                    patch("atelier.sessions.find_codex_session", return_value=None),
                    patch(
                        "atelier.commands.open.subprocess.run",
                        return_value=DummyResult(returncode=1, stdout=""),
                    ),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    with pytest.raises(SystemExit):
                        open_cmd.open_workspace(
                            SimpleNamespace(workspace_name="feat-demo")
                        )
            finally:
                os.chdir(original_cwd)

    def test_open_errors_when_origin_remote_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_open_config(project_dir, enlistment_path)

            workspace_branch = "scott/feat-demo"
            workspace_dir = paths.workspace_dir_for_branch(
                project_dir,
                workspace_branch,
                workspace_id_for(enlistment_path, workspace_branch),
            )
            repo_dir = workspace_dir / "repo"
            repo_dir.mkdir(parents=True)
            subprocess.run(["git", "-C", str(repo_dir), "init"], check=True)

            original_cwd = Path.cwd()
            os.chdir(root)
            try:

                def fake_run(
                    cmd: list[str],
                    cwd: Path | None = None,
                    env: dict[str, str] | None = None,
                ) -> None:
                    return None

                with (
                    patch("atelier.exec.run_command", fake_run),
                    patch("atelier.codex.run_codex_command", fake_codex),
                    patch("atelier.sessions.find_codex_session", return_value=None),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    with pytest.raises(SystemExit):
                        open_cmd.open_workspace(
                            SimpleNamespace(workspace_name="feat-demo")
                        )
            finally:
                os.chdir(original_cwd)

    def test_open_accepts_raw_branch_name(self) -> None:
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

                def fake_run(
                    cmd: list[str],
                    cwd: Path | None = None,
                    env: dict[str, str] | None = None,
                ) -> None:
                    return None

                with (
                    patch("atelier.exec.run_command", fake_run),
                    patch("atelier.codex.run_codex_command", fake_codex),
                    patch("atelier.sessions.find_codex_session", return_value=None),
                    patch(
                        "atelier.commands.open.subprocess.run",
                        return_value=DummyResult(returncode=1, stdout=""),
                    ),
                    patch("atelier.git.git_current_branch", return_value="main"),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.git.git_is_clean", return_value=True),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    workspace_branch = "feature/demo-branch"
                    open_cmd.open_workspace(
                        SimpleNamespace(workspace_name=workspace_branch, raw=True)
                    )

                workspace_dir = paths.workspace_dir_for_branch(
                    project_dir,
                    workspace_branch,
                    workspace_id_for(enlistment_path, workspace_branch),
                )
                assert (workspace_dir / "AGENTS.md").exists()
                workspace_config = config.load_workspace_config(
                    paths.workspace_config_path(workspace_dir)
                )
                assert workspace_config is not None
                assert workspace_config.workspace.branch == workspace_branch
            finally:
                os.chdir(original_cwd)

    def test_open_prefers_success_template(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            payload = {
                "project": {
                    "enlistment": enlistment_path,
                    "origin": NORMALIZED_ORIGIN,
                    "repo_url": RAW_ORIGIN,
                },
                "branch": {"prefix": "scott/"},
                "agent": {"default": "codex", "options": {"codex": []}},
                "editor": {"edit": ["true"], "work": ["true"]},
                "atelier": {
                    "version": atelier.__version__,
                    "created_at": "2026-01-01T00:00:00Z",
                    "upgrade": "ask",
                },
            }
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            project_dir.mkdir(parents=True, exist_ok=True)
            parsed = config.ProjectConfig.model_validate(payload)
            config.write_project_config(paths.project_config_path(project_dir), parsed)
            templates_dir = project_dir / "templates"
            templates_dir.mkdir()
            success_content = "<!-- success template -->\n"
            legacy_content = "<!-- workspace template -->\n"
            (templates_dir / "SUCCESS.md").write_text(success_content, encoding="utf-8")
            (templates_dir / "WORKSPACE.md").write_text(
                legacy_content, encoding="utf-8"
            )

            original_cwd = Path.cwd()
            os.chdir(root)
            try:

                def fake_run(
                    cmd: list[str],
                    cwd: Path | None = None,
                    env: dict[str, str] | None = None,
                ) -> None:
                    return None

                with (
                    patch("atelier.exec.run_command", fake_run),
                    patch("atelier.codex.run_codex_command", fake_codex),
                    patch("atelier.sessions.find_codex_session", return_value=None),
                    patch(
                        "atelier.commands.open.subprocess.run",
                        return_value=DummyResult(returncode=1, stdout=""),
                    ),
                    patch("atelier.git.git_current_branch", return_value="main"),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.git.git_is_clean", return_value=True),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    open_cmd.open_workspace(SimpleNamespace(workspace_name="feat-demo"))

                workspace_branch = "scott/feat-demo"
                workspace_dir = paths.workspace_dir_for_branch(
                    project_dir,
                    workspace_branch,
                    workspace_id_for(enlistment_path, workspace_branch),
                )
                success_template = workspace_dir / "SUCCESS.md"
                assert success_template.exists()
                assert success_template.read_text(encoding="utf-8") == success_content
                assert not (workspace_dir / "WORKSPACE.md").exists()
            finally:
                os.chdir(original_cwd)

    def test_open_normalizes_workspace_name_and_preserves_branch_slashes(self) -> None:
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

                def fake_run(
                    cmd: list[str],
                    cwd: Path | None = None,
                    env: dict[str, str] | None = None,
                ) -> None:
                    return None

                with (
                    patch("atelier.exec.run_command", fake_run),
                    patch("atelier.codex.run_codex_command", fake_codex),
                    patch("atelier.sessions.find_codex_session", return_value=None),
                    patch(
                        "atelier.commands.open.subprocess.run",
                        return_value=DummyResult(returncode=1, stdout=""),
                    ),
                    patch("atelier.git.git_current_branch", return_value="main"),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.git.git_is_clean", return_value=True),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    open_cmd.open_workspace(SimpleNamespace(workspace_name="feat/demo"))

                workspace_branch = "scott/feat/demo"
                workspace_dir = paths.workspace_dir_for_branch(
                    project_dir,
                    workspace_branch,
                    workspace_id_for(enlistment_path, workspace_branch),
                )
                workspace_config = config.load_workspace_config(
                    paths.workspace_config_path(workspace_dir)
                )
                assert workspace_config is not None
                assert workspace_config.workspace.branch == workspace_branch
            finally:
                os.chdir(original_cwd)

    def test_open_renders_direct_integration_strategy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_open_config(
                project_dir,
                enlistment_path,
                branch={
                    "prefix": "scott/",
                    "pr": False,
                    "history": "squash",
                },
            )

            original_cwd = Path.cwd()
            os.chdir(root)
            try:

                def fake_run(
                    cmd: list[str],
                    cwd: Path | None = None,
                    env: dict[str, str] | None = None,
                ) -> None:
                    return None

                with (
                    patch("atelier.exec.run_command", fake_run),
                    patch("atelier.codex.run_codex_command", fake_codex),
                    patch("atelier.sessions.find_codex_session", return_value=None),
                    patch(
                        "atelier.commands.open.subprocess.run",
                        return_value=DummyResult(returncode=1, stdout=""),
                    ),
                    patch("atelier.git.git_current_branch", return_value="main"),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.git.git_is_clean", return_value=True),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    open_cmd.open_workspace(SimpleNamespace(workspace_name="feat-demo"))

                workspace_branch = "scott/feat-demo"
                workspace_dir = paths.workspace_dir_for_branch(
                    project_dir,
                    workspace_branch,
                    workspace_id_for(enlistment_path, workspace_branch),
                )
                persist_content = (workspace_dir / "PERSIST.md").read_text(
                    encoding="utf-8"
                )
                assert "Pull requests expected: no" in persist_content
                assert "History policy: squash" in persist_content
                assert "collapsed into a single commit" in persist_content
            finally:
                os.chdir(original_cwd)

    def test_open_overrides_branch_settings_for_new_workspace(self) -> None:
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
                commands: list[list[str]] = []
                fake_codex = record_codex_command(commands)

                def fake_run(
                    cmd: list[str],
                    cwd: Path | None = None,
                    env: dict[str, str] | None = None,
                ) -> None:
                    commands.append(cmd)

                with (
                    patch("atelier.exec.run_command", fake_run),
                    patch("atelier.codex.run_codex_command", fake_codex),
                    patch("atelier.sessions.find_codex_session", return_value=None),
                    patch(
                        "atelier.commands.open.subprocess.run",
                        return_value=DummyResult(returncode=1, stdout=""),
                    ),
                    patch("atelier.git.git_current_branch", return_value="main"),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.git.git_is_clean", return_value=True),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    open_cmd.open_workspace(
                        SimpleNamespace(
                            workspace_name="feat-demo",
                            branch_pr="false",
                            branch_history="merge",
                        )
                    )

                workspace_branch = "scott/feat-demo"
                workspace_dir = paths.workspace_dir_for_branch(
                    project_dir,
                    workspace_branch,
                    workspace_id_for(enlistment_path, workspace_branch),
                )
                workspace_config = config.load_workspace_config(
                    paths.workspace_config_path(workspace_dir)
                )
                assert workspace_config is not None
                assert workspace_config.workspace.branch_pr is False
                assert workspace_config.workspace.branch_history == "merge"

                persist_content = (workspace_dir / "PERSIST.md").read_text(
                    encoding="utf-8"
                )
                assert "Pull requests expected: no" in persist_content
                assert "History policy: merge" in persist_content
            finally:
                os.chdir(original_cwd)

    def test_open_uses_remote_branch_and_writes_background_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            origin_repo = init_local_repo(root)
            origin_raw = str(origin_repo)
            origin_norm = git.normalize_origin_url(origin_raw)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, origin_norm
                )
            write_open_config(
                project_dir,
                enlistment_path,
                project={"origin": origin_norm, "repo_url": origin_raw},
            )
            workspace_branch = "scott/feat-demo"
            workspace_dir = paths.workspace_dir_for_branch(
                project_dir,
                workspace_branch,
                workspace_id_for(enlistment_path, workspace_branch),
            )

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                commands: list[list[str]] = []
                fake_codex = record_codex_command(commands)

                def fake_run(
                    cmd: list[str],
                    cwd: Path | None = None,
                    env: dict[str, str] | None = None,
                ) -> None:
                    commands.append(cmd)
                    if cmd[0] == "codex":
                        return
                    if cmd[0] == "true":
                        background_content = (
                            workspace_dir / "BACKGROUND.md"
                        ).read_text(encoding="utf-8")
                        assert "Commit Subjects since merge-base" in background_content
                    subprocess.run(cmd, cwd=cwd, check=True)

                with (
                    patch("atelier.exec.run_command", fake_run),
                    patch("atelier.codex.run_codex_command", fake_codex),
                    patch("atelier.sessions.find_codex_session", return_value=None),
                    patch("atelier.git.git_is_repo", return_value=True),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=origin_raw),
                ):
                    open_cmd.open_workspace(SimpleNamespace(workspace_name="feat-demo"))

                assert (workspace_dir / "BACKGROUND.md").exists()
                background_content = (workspace_dir / "BACKGROUND.md").read_text(
                    encoding="utf-8"
                )
                assert "Commit Subjects since merge-base" in background_content
                assert "feat: demo change" in background_content

                head = subprocess.run(
                    [
                        "git",
                        "-C",
                        str(workspace_dir / "repo"),
                        "rev-parse",
                        "--abbrev-ref",
                        "HEAD",
                    ],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                assert head.stdout.strip() == "scott/feat-demo"
                assert any(cmd[0] == "codex" for cmd in commands)
            finally:
                os.chdir(original_cwd)

    def test_open_skips_background_for_new_branch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            origin_repo = init_local_repo_without_feature(root)
            origin_raw = str(origin_repo)
            origin_norm = git.normalize_origin_url(origin_raw)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, origin_norm
                )
            write_open_config(
                project_dir,
                enlistment_path,
                project={"origin": origin_norm, "repo_url": origin_raw},
            )

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                commands: list[list[str]] = []
                fake_codex = record_codex_command(commands)

                def fake_run(
                    cmd: list[str],
                    cwd: Path | None = None,
                    env: dict[str, str] | None = None,
                ) -> None:
                    commands.append(cmd)
                    if cmd[0] == "codex":
                        return
                    subprocess.run(cmd, cwd=cwd, check=True)

                with (
                    patch("atelier.exec.run_command", fake_run),
                    patch("atelier.codex.run_codex_command", fake_codex),
                    patch("atelier.sessions.find_codex_session", return_value=None),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=origin_raw),
                ):
                    open_cmd.open_workspace(SimpleNamespace(workspace_name="feat-demo"))

                workspace_branch = "scott/feat-demo"
                workspace_dir = paths.workspace_dir_for_branch(
                    project_dir,
                    workspace_branch,
                    workspace_id_for(enlistment_path, workspace_branch),
                )
                assert not (workspace_dir / "BACKGROUND.md").exists()
            finally:
                os.chdir(original_cwd)

    def test_open_uses_raw_branch_without_prefix(self) -> None:
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
                commands: list[list[str]] = []
                fake_codex = record_codex_command(commands)

                def fake_run(
                    cmd: list[str],
                    cwd: Path | None = None,
                    env: dict[str, str] | None = None,
                ) -> None:
                    commands.append(cmd)

                with (
                    patch("atelier.exec.run_command", fake_run),
                    patch("atelier.codex.run_codex_command", fake_codex),
                    patch("atelier.sessions.find_codex_session", return_value=None),
                    patch(
                        "atelier.commands.open.subprocess.run",
                        return_value=DummyResult(returncode=1, stdout=""),
                    ),
                    patch("atelier.git.git_current_branch", return_value="main"),
                    patch("atelier.git.git_default_branch", return_value="main"),
                    patch("atelier.git.git_is_clean", return_value=True),
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    workspace_branch = "feature/demo-branch"
                    open_cmd.open_workspace(
                        SimpleNamespace(
                            workspace_name=workspace_branch,
                            raw=True,
                        )
                    )

                workspace_dir = paths.workspace_dir_for_branch(
                    project_dir,
                    workspace_branch,
                    workspace_id_for(enlistment_path, workspace_branch),
                )
                workspace_config = config.load_workspace_config(
                    paths.workspace_config_path(workspace_dir)
                )
                assert workspace_config is not None
                assert workspace_config.workspace.branch == workspace_branch
                assert any(
                    len(cmd) >= 6
                    and cmd[0] == "git"
                    and cmd[1] == "-C"
                    and cmd[3:6] == ["checkout", "-b", workspace_branch]
                    for cmd in commands
                )
            finally:
                os.chdir(original_cwd)

    def test_open_errors_on_branch_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_open_config(project_dir, enlistment_path)
            workspace_branch = "scott/feat-demo"
            workspace_dir = paths.workspace_dir_for_branch(
                project_dir,
                workspace_branch,
                workspace_id_for(enlistment_path, workspace_branch),
            )
            workspace_dir.mkdir(parents=True)
            write_workspace_config(workspace_dir, "scott/mismatch", enlistment_path)

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                with (
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    with pytest.raises(SystemExit):
                        open_cmd.open_workspace(
                            SimpleNamespace(workspace_name="feat-demo")
                        )
            finally:
                os.chdir(original_cwd)

    def test_open_errors_on_branch_settings_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            write_open_config(project_dir, enlistment_path)
            workspace_branch = "scott/feat-demo"
            workspace_dir = paths.workspace_dir_for_branch(
                project_dir,
                workspace_branch,
                workspace_id_for(enlistment_path, workspace_branch),
            )
            workspace_dir.mkdir(parents=True)
            write_workspace_config(workspace_dir, workspace_branch, enlistment_path)

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                with (
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    with pytest.raises(SystemExit):
                        open_cmd.open_workspace(
                            SimpleNamespace(
                                workspace_name="feat-demo",
                                branch_pr="false",
                                branch_history="manual",
                            )
                        )
            finally:
                os.chdir(original_cwd)

    def test_open_rejects_invalid_branch_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enlistment_path = enlistment_path_for(root)
            data_dir = root / "data"
            with patch("atelier.paths.atelier_data_dir", return_value=data_dir):
                project_dir = paths.project_dir_for_enlistment(
                    enlistment_path, NORMALIZED_ORIGIN
                )
            payload = make_open_config(
                enlistment_path,
                branch={"prefix": "scott/", "history": "sideways"},
            )
            legacy_path = paths.project_config_legacy_path(project_dir)
            project_dir.mkdir(parents=True, exist_ok=True)
            legacy_path.write_text(json.dumps(payload), encoding="utf-8")

            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                with (
                    patch("atelier.paths.atelier_data_dir", return_value=data_dir),
                    patch("atelier.git.git_repo_root", return_value=root),
                    patch("atelier.git.git_origin_url", return_value=RAW_ORIGIN),
                ):
                    with pytest.raises(SystemExit):
                        open_cmd.open_workspace(
                            SimpleNamespace(workspace_name="feat-demo")
                        )
            finally:
                os.chdir(original_cwd)

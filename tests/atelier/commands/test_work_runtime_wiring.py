from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from atelier import config
from atelier.agent_home import AgentHome
from atelier.commands import work as work_cmd


def _project_config() -> config.ProjectConfig:
    return config.ProjectConfig(
        project=config.ProjectSection(enlistment="/repo", origin="org/repo"),
        branch=config.BranchConfig(),
        agent=config.AgentConfig(default="codex", options={"codex": []}),
    )


def test_start_worker_delegates_loop_to_runtime() -> None:
    with (
        patch(
            "atelier.commands.work.agent_home.generate_session_key",
            return_value="sess-1",
        ),
        patch(
            "atelier.commands.work.worker_runtime.run_worker_sessions"
        ) as run_sessions,
    ):
        work_cmd.start_worker(
            SimpleNamespace(epic_id=None, mode="auto", run_mode="once", dry_run=True)
        )

    kwargs = run_sessions.call_args.kwargs
    assert kwargs["mode"] == "auto"
    assert kwargs["run_mode"] == "once"
    assert kwargs["dry_run"] is True
    assert kwargs["session_key"] == "sess-1"
    assert kwargs["run_worker_once"] is work_cmd._run_worker_once


def test_start_worker_cleans_up_agent_home_after_runtime_failure(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    repo_root = tmp_path / "repo"
    project_root.mkdir()
    repo_root.mkdir()
    project_cfg = _project_config()
    agent = AgentHome(
        name="worker",
        agent_id="atelier/worker/codex/p1",
        role="worker",
        path=tmp_path / "agents" / "worker" / "codex" / "p1",
        session_key="p1",
    )

    with (
        patch(
            "atelier.commands.work.resolve_current_project_with_repo_root",
            return_value=(project_root, project_cfg, str(repo_root), repo_root),
        ),
        patch(
            "atelier.commands.work.config.resolve_project_data_dir",
            return_value=tmp_path,
        ),
        patch(
            "atelier.commands.work.agent_home.preview_agent_home", return_value=agent
        ),
        patch(
            "atelier.commands.work.worker_runtime.run_worker_sessions",
            side_effect=RuntimeError("boom"),
        ),
        patch("atelier.commands.work.agent_home.cleanup_agent_home") as cleanup_home,
    ):
        with pytest.raises(RuntimeError, match="boom"):
            work_cmd.start_worker(
                SimpleNamespace(
                    epic_id=None, mode="auto", run_mode="default", dry_run=False
                )
            )

    cleanup_home.assert_called_once_with(agent, project_dir=tmp_path)

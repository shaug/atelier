from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from atelier import config
from atelier.agent_home import AgentHome
from atelier.commands import work as work_cmd
from atelier.worker.models import WorkerRunSummary


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


def test_run_worker_once_uses_runtime_builder_and_runner() -> None:
    deps = object()
    expected = WorkerRunSummary(started=False, reason="queue_blocked")

    with (
        patch(
            "atelier.commands.work.worker_runtime.build_worker_runtime_dependencies",
            return_value=deps,
        ) as build_deps,
        patch(
            "atelier.commands.work.worker_session_runner.run_worker_once",
            return_value=expected,
        ) as run_once,
    ):
        result = work_cmd._run_worker_once(
            SimpleNamespace(), mode="auto", dry_run=True, session_key="sess-1"
        )

    assert result is expected
    build_deps.assert_called_once()
    kwargs = run_once.call_args.kwargs
    assert kwargs["deps"] is deps
    assert kwargs["run_context"].mode == "auto"
    assert kwargs["run_context"].dry_run is True
    assert kwargs["run_context"].session_key == "sess-1"

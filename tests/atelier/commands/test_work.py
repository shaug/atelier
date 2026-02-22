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


def test_start_worker_dry_run_skips_project_resolution() -> None:
    with (
        patch("atelier.commands.work.resolve_current_project_with_repo_root") as resolve_project,
        patch("atelier.commands.work.agent_home.preview_agent_home") as preview_agent_home,
        patch("atelier.commands.work.agent_home.cleanup_agent_home") as cleanup_agent_home,
        patch("atelier.commands.work.worker_runtime.run_worker_sessions"),
    ):
        work_cmd.start_worker(
            SimpleNamespace(epic_id=None, mode="auto", run_mode="once", dry_run=True)
        )

    resolve_project.assert_not_called()
    preview_agent_home.assert_not_called()
    cleanup_agent_home.assert_not_called()


def test_start_worker_non_dry_run_previews_and_cleans_agent_home(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    repo_root = tmp_path / "repo"
    project_root.mkdir()
    repo_root.mkdir()
    project_cfg = _project_config()
    session_agent = AgentHome(
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
            "atelier.commands.work.agent_home.preview_agent_home",
            return_value=session_agent,
        ) as preview_agent_home,
        patch("atelier.commands.work.worker_runtime.run_worker_sessions") as run_sessions,
        patch("atelier.commands.work.agent_home.cleanup_agent_home") as cleanup_agent_home,
    ):
        work_cmd.start_worker(
            SimpleNamespace(epic_id=None, mode="auto", run_mode="once", dry_run=False)
        )

    preview_agent_home.assert_called_once()
    run_sessions.assert_called_once()
    cleanup_agent_home.assert_called_once_with(session_agent, project_dir=tmp_path)


def test_start_worker_applies_env_translated_yes_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ATELIER_MODE", "AUTO")
    monkeypatch.setenv("ATELIER_RUN_MODE", "WATCH")
    monkeypatch.setenv("ATELIER_WORK_YES", "1")
    args = SimpleNamespace(epic_id=None, mode=None, run_mode=None, dry_run=True, yes=False)
    with patch("atelier.commands.work.worker_runtime.run_worker_sessions") as run_sessions:
        work_cmd.start_worker(args)

    kwargs = run_sessions.call_args.kwargs
    assert kwargs["mode"] == "prompt"
    assert kwargs["run_mode"] == "default"
    assert kwargs["args"].yes is True


def test_start_worker_cli_values_override_env_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ATELIER_MODE", "prompt")
    monkeypatch.setenv("ATELIER_RUN_MODE", "once")
    monkeypatch.setenv("ATELIER_WORK_YES", "0")
    args = SimpleNamespace(epic_id=None, mode="auto", run_mode="watch", dry_run=True, yes=True)
    with patch("atelier.commands.work.worker_runtime.run_worker_sessions") as run_sessions:
        work_cmd.start_worker(args)

    kwargs = run_sessions.call_args.kwargs
    assert kwargs["mode"] == "auto"
    assert kwargs["run_mode"] == "watch"
    assert kwargs["args"].yes is True


def test_start_worker_invalid_mode_exits() -> None:
    with pytest.raises(SystemExit):
        work_cmd.start_worker(
            SimpleNamespace(epic_id=None, mode="invalid", run_mode="once", dry_run=True)
        )


def test_start_worker_invalid_work_yes_env_exits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ATELIER_WORK_YES", "maybe")
    with pytest.raises(SystemExit):
        work_cmd.start_worker(
            SimpleNamespace(epic_id=None, mode="auto", run_mode="once", dry_run=True, yes=False)
        )


def test_start_worker_invalid_watch_interval_exits() -> None:
    with pytest.raises(SystemExit):
        work_cmd.start_worker(
            SimpleNamespace(
                epic_id=None,
                mode="auto",
                run_mode="watch",
                watch_interval=0,
                dry_run=True,
            )
        )


def test_command_reexports_worker_reconcile_functions() -> None:
    assert callable(work_cmd.list_reconcile_epic_candidates)
    assert callable(work_cmd.reconcile_blocked_merged_changesets)


def test_start_worker_ignores_legacy_mode_env_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ATELIER_MODE", "invalid")
    monkeypatch.setenv("ATELIER_RUN_MODE", "invalid")
    captured: dict[str, object] = {}

    def fake_run_worker_sessions(**kwargs: object) -> None:
        captured.update(kwargs)

    with patch(
        "atelier.commands.work.worker_runtime.run_worker_sessions",
        side_effect=fake_run_worker_sessions,
    ):
        work_cmd.start_worker(SimpleNamespace(epic_id=None, mode=None, run_mode=None, dry_run=True))

    assert captured["mode"] == "prompt"
    assert captured["run_mode"] == "default"


def test_start_worker_ignores_legacy_watch_interval_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ATELIER_WATCH_INTERVAL", "7")
    captured: dict[str, object] = {}

    def fake_run_worker_sessions(**kwargs: object) -> None:
        captured.update(kwargs)

    with patch(
        "atelier.commands.work.worker_runtime.run_worker_sessions",
        side_effect=fake_run_worker_sessions,
    ):
        work_cmd.start_worker(
            SimpleNamespace(
                epic_id=None,
                mode="auto",
                run_mode="watch",
                watch_interval=None,
                dry_run=True,
            )
        )

    interval_fn = captured["watch_interval_seconds"]
    assert callable(interval_fn)
    assert interval_fn() == 60

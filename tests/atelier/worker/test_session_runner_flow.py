from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from atelier import config
from atelier.agent_home import AgentHome
from atelier.worker.context import WorkerRunContext
from atelier.worker.models import StartupContractResult
from atelier.worker.session import runner


def _noop(*_args: object, **_kwargs: object) -> None:
    return None


def _build_runner_deps(
    *,
    startup_result: StartupContractResult,
    preview_agent: AgentHome,
) -> runner.RunnerDependencies:
    project_config = config.ProjectConfig(
        project=config.ProjectSection(origin="org/repo")
    )
    resolve_project = Mock(
        return_value=(Path("/project"), project_config, "/repo", Path("/repo"))
    )
    resolve_project_data_dir = Mock(return_value=Path("/project/.atelier"))
    resolve_beads_root = Mock(return_value=Path("/project/.atelier/.beads"))

    return runner.RunnerDependencies(
        _capture_review_feedback_snapshot=_noop,
        _changeset_parent_branch=lambda _issue, **_kwargs: "feat/root",
        _changeset_pr_url=lambda _issue: None,
        _changeset_work_branch=lambda _issue: None,
        _dry_run_log=_noop,
        _ensure_exec_subcommand_flag=lambda args, _flag: args,
        _extract_changeset_root_branch=lambda _issue: "feat/root",
        _extract_workspace_parent_branch=lambda _issue: "main",
        _finalize_changeset=lambda **_kwargs: None,
        _find_invalid_changeset_labels=lambda **_kwargs: [],
        _lookup_pr_payload=lambda _repo_slug, _branch: None,
        _mark_changeset_blocked=_noop,
        _mark_changeset_in_progress=_noop,
        _next_changeset=lambda **_kwargs: None,
        _persist_review_feedback_cursor=_noop,
        _release_epic_assignment=_noop,
        _report_timings=_noop,
        _resolve_epic_id_for_changeset=lambda _issue, **_kwargs: None,
        _review_feedback_progressed=lambda _before, _after: False,
        _run_startup_contract=Mock(return_value=startup_result),
        _send_invalid_changeset_labels_notification=lambda **_kwargs: "sent",
        _send_no_ready_changesets=_noop,
        _send_planner_notification=_noop,
        _step=lambda _label, *, timings, trace: lambda **_kwargs: None,
        _strip_flag_with_value=lambda args, _flag: args,
        _trace_enabled=lambda: False,
        _with_codex_exec=lambda cmd, _prompt: cmd,
        _worker_opening_prompt=lambda **_kwargs: "open",
        agent_home=SimpleNamespace(
            preview_agent_home=Mock(return_value=preview_agent),
            resolve_agent_home=Mock(return_value=preview_agent),
        ),
        agents=SimpleNamespace(scoped_agent_env=lambda _agent_id: nullcontext()),
        beads=SimpleNamespace(
            run_bd_command=Mock(),
            ensure_agent_bead=Mock(return_value={"id": "at-agent"}),
            find_agent_bead=Mock(return_value={"id": "at-agent"}),
        ),
        branching=SimpleNamespace(branch_exists=lambda **_kwargs: True),
        config=SimpleNamespace(
            resolve_project_data_dir=resolve_project_data_dir,
            resolve_beads_root=resolve_beads_root,
            resolve_git_path=Mock(return_value="git"),
        ),
        confirm=lambda _prompt: True,
        die=Mock(side_effect=RuntimeError("die called")),
        git=SimpleNamespace(git_default_branch=lambda *_args, **_kwargs: "main"),
        prs=SimpleNamespace(
            clear_runtime_cache=Mock(),
            github_repo_slug=lambda _origin: "org/repo",
        ),
        reconcile_blocked_merged_changesets=Mock(),
        resolve_current_project_with_repo_root=resolve_project,
        root_branch=SimpleNamespace(suggest_root_branch=lambda **_kwargs: "feat/root"),
        say=Mock(),
        worker_session_agent=SimpleNamespace(start_agent_session=Mock()),
        worker_session_worktree=SimpleNamespace(prepare_worktrees=Mock()),
    )


def test_run_worker_once_returns_startup_exit_summary() -> None:
    agent = AgentHome(
        name="worker",
        agent_id="atelier/worker/codex/p1",
        role="worker",
        path=Path("/tmp/worker"),
        session_key="p1",
    )
    deps = _build_runner_deps(
        startup_result=StartupContractResult(
            epic_id=None,
            changeset_id=None,
            should_exit=True,
            reason="no_eligible_epics",
        ),
        preview_agent=agent,
    )

    summary = runner.run_worker_once(
        SimpleNamespace(epic_id=None, queue=False, yes=False, reconcile=False),
        run_context=WorkerRunContext(mode="auto", dry_run=False, session_key="p1"),
        deps=deps,
    )

    assert summary.started is False
    assert summary.reason == "no_eligible_epics"
    deps.beads.run_bd_command.assert_called_once()
    deps._run_startup_contract.assert_called_once()


def test_run_worker_once_dry_run_without_epic_stops_cleanly() -> None:
    agent = AgentHome(
        name="worker",
        agent_id="atelier/worker/codex/p2",
        role="worker",
        path=Path("/tmp/worker"),
        session_key="p2",
    )
    deps = _build_runner_deps(
        startup_result=StartupContractResult(
            epic_id=None,
            changeset_id=None,
            should_exit=False,
            reason="continue",
        ),
        preview_agent=agent,
    )

    summary = runner.run_worker_once(
        SimpleNamespace(epic_id=None, queue=False, yes=False, reconcile=False),
        run_context=WorkerRunContext(mode="auto", dry_run=True, session_key="p2"),
        deps=deps,
    )

    assert summary.started is False
    assert summary.reason == "no_epic_selected"
    deps.agent_home.preview_agent_home.assert_called_once()
    deps.agent_home.resolve_agent_home.assert_not_called()

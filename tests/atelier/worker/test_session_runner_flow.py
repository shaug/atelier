from __future__ import annotations

import datetime as dt
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from atelier import config
from atelier.agent_home import AgentHome
from atelier.worker.context import WorkerRunContext
from atelier.worker.models import FinalizeResult, StartupContractResult
from atelier.worker.ports import (
    WorkerInfrastructurePorts,
    WorkerRuntimeDependencies,
)
from atelier.worker.session import runner


def _noop(*_args: object, **_kwargs: object) -> None:
    return None


class _TestControl:
    def __init__(self) -> None:
        self._die = Mock(side_effect=RuntimeError("die called"))
        self._say = Mock()

    def dry_run_log(self, message: str) -> None:
        _noop(message)

    def report_timings(self, timings: list[tuple[str, float]], *, trace: bool) -> None:
        _noop(timings, trace)

    def step(self, _label: str, *, timings, trace):  # type: ignore[no-untyped-def]
        _noop(timings, trace)
        return lambda **_kwargs: None

    def trace_enabled(self) -> bool:
        return False

    def confirm(self, _prompt: str, *, default: bool = False) -> bool:
        return default

    def die(self, message: str) -> None:
        self._die(message)

    def say(self, message: str) -> None:
        self._say(message)


def _build_runner_deps(
    *,
    startup_result: StartupContractResult,
    preview_agent: AgentHome,
) -> WorkerRuntimeDependencies:
    project_config = config.ProjectConfig(project=config.ProjectSection(origin="org/repo"))
    resolve_project = Mock(return_value=(Path("/project"), project_config, "/repo", Path("/repo")))
    resolve_project_data_dir = Mock(return_value=Path("/project/.atelier"))
    resolve_beads_root = Mock(return_value=Path("/project/.atelier/.beads"))

    run_startup_contract = Mock(return_value=startup_result)
    beads_port = SimpleNamespace(
        run_bd_command=Mock(),
        run_bd_json=Mock(return_value=[]),
        ensure_agent_bead=Mock(return_value={"id": "at-agent"}),
        find_agent_bead=Mock(return_value={"id": "at-agent"}),
        claim_epic=Mock(return_value={"id": "at-epic", "title": "Epic"}),
        clear_agent_hook=Mock(),
        extract_workspace_root_branch=Mock(return_value="feat/root"),
        update_workspace_root_branch=Mock(),
        update_workspace_parent_branch=Mock(),
        set_agent_hook=Mock(),
    )

    return WorkerRuntimeDependencies(
        infra=WorkerInfrastructurePorts(
            resolve_current_project_with_repo_root=resolve_project,
            agent_home=SimpleNamespace(
                preview_agent_home=Mock(return_value=preview_agent),
                resolve_agent_home=Mock(return_value=preview_agent),
            ),
            agents=SimpleNamespace(scoped_agent_env=lambda _agent_id: nullcontext()),
            beads=beads_port,
            branching=SimpleNamespace(
                suggest_root_branch=Mock(return_value="feat/root"),
                branch_exists=lambda **_kwargs: True,
            ),
            config=SimpleNamespace(
                resolve_project_data_dir=resolve_project_data_dir,
                resolve_beads_root=resolve_beads_root,
                resolve_git_path=Mock(return_value="git"),
            ),
            git=SimpleNamespace(git_default_branch=lambda *_args, **_kwargs: "main"),
            prs=SimpleNamespace(
                clear_runtime_cache=Mock(),
                github_repo_slug=lambda _origin: "org/repo",
            ),
            root_branch=SimpleNamespace(prompt_root_branch=Mock(return_value="feat/root")),
            worker_session_agent=SimpleNamespace(
                prepare_agent_session=Mock(
                    side_effect=RuntimeError("prepare_agent_session should not run")
                ),
                install_agent_hooks=Mock(),
                start_agent_session=Mock(),
            ),
            worker_session_worktree=SimpleNamespace(prepare_worktrees=Mock()),
        ),
        lifecycle=SimpleNamespace(
            capture_review_feedback_snapshot=Mock(side_effect=AssertionError),
            changeset_parent_branch=lambda _issue, **_kwargs: "feat/root",
            changeset_pr_url=lambda _issue: None,
            changeset_work_branch=lambda _issue: None,
            extract_changeset_root_branch=lambda _issue: "feat/root",
            extract_workspace_parent_branch=lambda _issue: "main",
            finalize_changeset=lambda **_kwargs: FinalizeResult(
                continue_running=False,
                reason="done",
            ),
            find_invalid_changeset_labels=lambda **_kwargs: [],
            lookup_pr_payload=lambda _repo_slug, _branch: None,
            mark_changeset_blocked=_noop,
            mark_changeset_in_progress=_noop,
            next_changeset=lambda **_kwargs: None,
            persist_review_feedback_cursor=_noop,
            release_epic_assignment=_noop,
            reconcile_blocked_merged_changesets=Mock(),
            resolve_epic_id_for_changeset=lambda _issue, **_kwargs: None,
            review_feedback_progressed=lambda _before, _after: False,
            run_startup_contract=run_startup_contract,
            send_invalid_changeset_labels_notification=lambda **_kwargs: "sent",
            send_no_ready_changesets=_noop,
            send_planner_notification=_noop,
        ),
        commands=SimpleNamespace(
            ensure_exec_subcommand_flag=lambda args, _flag: args,
            strip_flag_with_value=lambda args, _flag: args,
            with_codex_exec=lambda cmd, _prompt: cmd,
            worker_opening_prompt=lambda **_kwargs: "open",
        ),
        control=_TestControl(),
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
    deps.infra.beads.run_bd_command.assert_called_once()
    deps.lifecycle.run_startup_contract.assert_called_once()


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
    deps.infra.agent_home.preview_agent_home.assert_called_once()
    deps.infra.agent_home.resolve_agent_home.assert_not_called()


def test_run_worker_once_retries_after_claim_conflict() -> None:
    agent = AgentHome(
        name="worker",
        agent_id="atelier/worker/codex/p3",
        role="worker",
        path=Path("/tmp/worker"),
        session_key="p3",
    )
    deps = _build_runner_deps(
        startup_result=StartupContractResult(
            epic_id="at-conflict",
            changeset_id=None,
            should_exit=False,
            reason="selected_auto",
        ),
        preview_agent=agent,
    )
    startup_contexts: list[runner.StartupContractContext] = []

    def run_startup_contract(*, context: runner.StartupContractContext) -> StartupContractResult:
        startup_contexts.append(context)
        if "at-conflict" in context.excluded_epic_ids:
            return StartupContractResult(
                epic_id="at-alt",
                changeset_id=None,
                should_exit=False,
                reason="selected_auto",
            )
        return StartupContractResult(
            epic_id="at-conflict",
            changeset_id=None,
            should_exit=False,
            reason="selected_auto",
        )

    claim_attempts: list[str] = []

    def claim_epic(epic_id: str, *_args: object, **_kwargs: object) -> dict[str, object]:
        claim_attempts.append(epic_id)
        if epic_id == "at-conflict":
            raise SystemExit(1)
        return {"id": epic_id, "title": epic_id}

    def run_bd_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:  # noqa: ARG001
        if args[:2] == ["show", "at-conflict"]:
            return [{"id": "at-conflict", "assignee": "atelier/planner/codex/p777"}]
        return []

    deps.lifecycle.run_startup_contract = Mock(side_effect=run_startup_contract)
    deps.infra.beads.claim_epic = Mock(side_effect=claim_epic)
    deps.infra.beads.run_bd_json = Mock(side_effect=run_bd_json)
    deps.lifecycle.find_invalid_changeset_labels = lambda *_args, **_kwargs: []

    summary = runner.run_worker_once(
        SimpleNamespace(epic_id=None, queue=False, yes=False, reconcile=False),
        run_context=WorkerRunContext(mode="auto", dry_run=False, session_key="p3"),
        deps=deps,
    )

    assert summary.started is False
    assert summary.reason == "no_ready_changesets"
    assert summary.epic_id == "at-alt"
    assert claim_attempts == ["at-conflict", "at-alt"]
    assert len(startup_contexts) == 2
    assert startup_contexts[0].excluded_epic_ids == ()
    assert startup_contexts[1].excluded_epic_ids == ("at-conflict",)


def test_run_worker_once_releases_epic_when_label_validation_reads_fail() -> None:
    agent = AgentHome(
        name="worker",
        agent_id="atelier/worker/codex/p4",
        role="worker",
        path=Path("/tmp/worker"),
        session_key="p4",
    )
    deps = _build_runner_deps(
        startup_result=StartupContractResult(
            epic_id="at-epic",
            changeset_id=None,
            should_exit=False,
            reason="selected_auto",
        ),
        preview_agent=agent,
    )
    deps.lifecycle.find_invalid_changeset_labels = Mock(side_effect=SystemExit(1))
    deps.lifecycle.release_epic_assignment = Mock()
    deps.lifecycle.send_planner_notification = Mock()

    summary = runner.run_worker_once(
        SimpleNamespace(epic_id=None, queue=False, yes=False, reconcile=False),
        run_context=WorkerRunContext(mode="auto", dry_run=False, session_key="p4"),
        deps=deps,
    )

    assert summary.started is False
    assert summary.reason == "changeset_label_validation_failed"
    assert summary.epic_id == "at-epic"
    deps.lifecycle.send_planner_notification.assert_called_once()
    deps.lifecycle.release_epic_assignment.assert_called_once_with(
        "at-epic",
        beads_root=Path("/project/.atelier/.beads"),
        repo_root=Path("/repo"),
    )
    deps.infra.beads.clear_agent_hook.assert_called_once_with(
        "at-agent",
        beads_root=Path("/project/.atelier/.beads"),
        cwd=Path("/repo"),
    )
    assert not deps.control._die.called


def test_run_worker_once_releases_epic_when_changeset_selection_reads_fail() -> None:
    agent = AgentHome(
        name="worker",
        agent_id="atelier/worker/codex/p5",
        role="worker",
        path=Path("/tmp/worker"),
        session_key="p5",
    )
    deps = _build_runner_deps(
        startup_result=StartupContractResult(
            epic_id="at-epic",
            changeset_id="at-epic.2",
            should_exit=False,
            reason="selected_auto",
        ),
        preview_agent=agent,
    )

    def run_bd_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:  # noqa: ARG001
        if args[:2] == ["show", "at-epic.2"]:
            raise SystemExit(1)
        return []

    deps.infra.beads.run_bd_json = Mock(side_effect=run_bd_json)
    deps.lifecycle.find_invalid_changeset_labels = lambda *_args, **_kwargs: []
    deps.lifecycle.release_epic_assignment = Mock()
    deps.lifecycle.send_planner_notification = Mock()

    summary = runner.run_worker_once(
        SimpleNamespace(epic_id=None, queue=False, yes=False, reconcile=False),
        run_context=WorkerRunContext(mode="auto", dry_run=False, session_key="p5"),
        deps=deps,
    )

    assert summary.started is False
    assert summary.reason == "changeset_selection_read_failed"
    assert summary.epic_id == "at-epic"
    deps.lifecycle.send_planner_notification.assert_called_once()
    deps.lifecycle.release_epic_assignment.assert_called_once_with(
        "at-epic",
        beads_root=Path("/project/.atelier/.beads"),
        repo_root=Path("/repo"),
    )
    deps.infra.beads.clear_agent_hook.assert_called_once_with(
        "at-agent",
        beads_root=Path("/project/.atelier/.beads"),
        cwd=Path("/repo"),
    )
    assert not deps.control._die.called


def test_run_worker_once_releases_epic_when_selected_changeset_read_fails() -> None:
    agent = AgentHome(
        name="worker",
        agent_id="atelier/worker/codex/p6",
        role="worker",
        path=Path("/tmp/worker"),
        session_key="p6",
    )
    deps = _build_runner_deps(
        startup_result=StartupContractResult(
            epic_id="at-epic",
            changeset_id=None,
            should_exit=False,
            reason="selected_auto",
        ),
        preview_agent=agent,
    )
    deps.lifecycle.next_changeset = lambda **_kwargs: {"id": "at-epic.1", "title": "Changeset"}
    deps.lifecycle.find_invalid_changeset_labels = lambda *_args, **_kwargs: []

    def run_bd_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:  # noqa: ARG001
        if args[:2] == ["show", "at-epic.1"]:
            raise SystemExit(1)
        return []

    deps.infra.beads.run_bd_json = Mock(side_effect=run_bd_json)
    deps.lifecycle.find_invalid_changeset_labels = lambda *_args, **_kwargs: []
    deps.lifecycle.release_epic_assignment = Mock()
    deps.lifecycle.send_planner_notification = Mock()

    summary = runner.run_worker_once(
        SimpleNamespace(epic_id=None, queue=False, yes=False, reconcile=False),
        run_context=WorkerRunContext(mode="auto", dry_run=False, session_key="p6"),
        deps=deps,
    )

    assert summary.started is False
    assert summary.reason == "changeset_metadata_read_failed"
    assert summary.epic_id == "at-epic"
    deps.lifecycle.send_planner_notification.assert_called_once()
    deps.lifecycle.release_epic_assignment.assert_called_once_with(
        "at-epic",
        beads_root=Path("/project/.atelier/.beads"),
        repo_root=Path("/repo"),
    )
    deps.infra.beads.clear_agent_hook.assert_called_once_with(
        "at-agent",
        beads_root=Path("/project/.atelier/.beads"),
        cwd=Path("/repo"),
    )
    assert not deps.control._die.called


def test_run_worker_once_returns_terminal_handoff_after_review_pending_finalize() -> None:
    agent = AgentHome(
        name="worker",
        agent_id="atelier/worker/codex/p7",
        role="worker",
        path=Path("/tmp/worker"),
        session_key="p7",
    )
    deps = _build_runner_deps(
        startup_result=StartupContractResult(
            epic_id="at-epic",
            changeset_id=None,
            should_exit=False,
            reason="selected_auto",
        ),
        preview_agent=agent,
    )
    deps.lifecycle.next_changeset = lambda **_kwargs: {"id": "at-epic.1", "title": "Changeset"}
    deps.lifecycle.find_invalid_changeset_labels = lambda *_args, **_kwargs: []
    deps.infra.beads.run_bd_json = Mock(
        side_effect=lambda args, **_kwargs: (
            [{"id": "at-epic.1", "title": "Changeset", "description": ""}]
            if args[:2] == ["show", "at-epic.1"]
            else []
        )
    )
    deps.infra.worker_session_worktree.prepare_worktrees = Mock(
        return_value=SimpleNamespace(
            epic_worktree_path=Path("/tmp/epic"),
            changeset_worktree_path=Path("/tmp/changeset"),
            branch="feat/root-at-epic.1",
        )
    )
    deps.infra.worker_session_agent.prepare_agent_session = Mock(
        return_value=SimpleNamespace(
            agent_spec=SimpleNamespace(name="demo", display_name="Demo"),
            agent_options=[],
            project_enlistment=Path("/repo"),
            workspace_branch="feat/root",
            env={},
        )
    )
    deps.infra.worker_session_agent.start_agent_session = Mock(
        return_value=SimpleNamespace(
            started_at=dt.datetime.now(dt.timezone.utc),
            returncode=0,
        )
    )
    deps.lifecycle.finalize_changeset = lambda **_kwargs: FinalizeResult(
        continue_running=True,
        reason="changeset_review_pending",
    )

    summary = runner.run_worker_once(
        SimpleNamespace(epic_id=None, queue=False, yes=False, reconcile=False),
        run_context=WorkerRunContext(mode="auto", dry_run=False, session_key="p7"),
        deps=deps,
    )

    assert summary.started is False
    assert summary.reason == "changeset_review_handoff"
    deps.infra.worker_session_agent.start_agent_session.assert_called_once()

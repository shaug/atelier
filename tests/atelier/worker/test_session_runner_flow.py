from __future__ import annotations

import datetime as dt
import subprocess
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

import pytest

from atelier import config
from atelier.agent_home import AgentHome
from atelier.worker.context import WorkerRunContext
from atelier.worker.models import (
    FinalizeResult,
    StartupContractResult,
    StartupFinalizePreflightResult,
)
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
    runtime_profile: str = "standard",
) -> WorkerRuntimeDependencies:
    project_config = config.ProjectConfig(project=config.ProjectSection(origin="org/repo"))
    project_config = project_config.model_copy(
        update={
            "runtime": project_config.runtime.model_copy(
                update={
                    "worker": project_config.runtime.worker.model_copy(
                        update={"profile": runtime_profile}
                    )
                }
            )
        }
    )
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
            startup_finalize_preflight=lambda **_kwargs: StartupFinalizePreflightResult(
                should_finalize_only=False,
                reason="normal_path:integration_unproven",
            ),
            finalize_changeset=lambda **_kwargs: FinalizeResult(
                continue_running=False,
                reason="done",
            ),
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


def test_changeset_block_handler_marks_and_notifies() -> None:
    lifecycle = SimpleNamespace(
        mark_changeset_blocked=Mock(),
        send_planner_notification=Mock(),
    )
    handler = runner._ChangesetBlockHandler(  # pyright: ignore[reportPrivateUsage]
        lifecycle=lifecycle,
        agent_id="atelier/worker/codex/p9",
        changeset_id="at-epic.1",
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
    )

    handler.mark_changeset_blocked("missing required command: codex")

    lifecycle.mark_changeset_blocked.assert_called_once_with(
        "at-epic.1",
        beads_root=Path("/beads"),
        repo_root=Path("/repo"),
        reason="missing required command: codex",
    )
    lifecycle.send_planner_notification.assert_called_once()
    call = lifecycle.send_planner_notification.call_args.kwargs
    assert call["agent_id"] == "atelier/worker/codex/p9"
    assert call["thread_id"] == "at-epic.1"
    assert "Stage: start agent session" in call["body"]
    assert "Diagnostics: missing required command: codex" in call["body"]


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


def test_run_worker_once_reuses_provided_agent_bead_id() -> None:
    agent = AgentHome(
        name="worker",
        agent_id="atelier/worker/codex/p1a",
        role="worker",
        path=Path("/tmp/worker"),
        session_key="p1a",
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
        SimpleNamespace(
            epic_id=None,
            queue=False,
            yes=False,
            reconcile=False,
            agent_bead_id="at-provided-agent",
        ),
        run_context=WorkerRunContext(mode="auto", dry_run=False, session_key="p1a"),
        deps=deps,
    )

    assert summary.started is False
    assert summary.reason == "no_eligible_epics"
    deps.infra.beads.ensure_agent_bead.assert_not_called()
    context = deps.lifecycle.run_startup_contract.call_args.kwargs["context"]
    assert context.agent_bead_id == "at-provided-agent"


def test_run_worker_once_skips_claim_for_non_actionable_explicit_epic() -> None:
    agent = AgentHome(
        name="worker",
        agent_id="atelier/worker/codex/p1x",
        role="worker",
        path=Path("/tmp/worker"),
        session_key="p1x",
    )
    deps = _build_runner_deps(
        startup_result=StartupContractResult(
            epic_id="at-explicit",
            changeset_id=None,
            should_exit=True,
            reason="explicit_epic_review_pending",
        ),
        preview_agent=agent,
    )

    summary = runner.run_worker_once(
        SimpleNamespace(epic_id="at-explicit", queue=False, yes=False, reconcile=False),
        run_context=WorkerRunContext(mode="auto", dry_run=False, session_key="p1x"),
        deps=deps,
    )

    assert summary.started is False
    assert summary.reason == "explicit_epic_review_pending"
    assert summary.epic_id == "at-explicit"
    deps.infra.beads.claim_epic.assert_not_called()


def test_run_worker_once_blocks_on_active_root_branch_conflict() -> None:
    agent = AgentHome(
        name="worker",
        agent_id="atelier/worker/codex/p1root",
        role="worker",
        path=Path("/tmp/worker"),
        session_key="p1root",
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
    deps.infra.beads.claim_epic = Mock(return_value={"id": "at-epic", "title": "Epic"})

    def run_bd_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:  # noqa: ARG001
        if args == ["list", "--label", "at:epic", "--all", "--limit", "0"]:
            return [
                {
                    "id": "at-owner",
                    "status": "hooked",
                    "title": "Owner epic",
                    "labels": ["at:epic", "at:hooked"],
                    "description": "workspace.root_branch: feat/root\n",
                }
            ]
        return []

    deps.infra.beads.run_bd_json = Mock(side_effect=run_bd_json)
    deps.lifecycle.release_epic_assignment = Mock()
    deps.lifecycle.send_planner_notification = Mock()

    summary = runner.run_worker_once(
        SimpleNamespace(epic_id=None, queue=False, yes=False, reconcile=False),
        run_context=WorkerRunContext(mode="auto", dry_run=False, session_key="p1root"),
        deps=deps,
    )

    assert summary.started is False
    assert summary.reason == "root_branch_conflict"
    assert summary.epic_id == "at-epic"
    deps.lifecycle.release_epic_assignment.assert_called_once_with(
        "at-epic",
        agent_id="atelier/worker/codex/p1root",
        beads_root=Path("/project/.atelier/.beads"),
        repo_root=Path("/repo"),
    )
    deps.lifecycle.send_planner_notification.assert_called_once()
    assert "at-owner [hooked] Owner epic" in str(
        deps.lifecycle.send_planner_notification.call_args.kwargs["body"]
    )
    deps.infra.beads.set_agent_hook.assert_not_called()


def test_run_worker_once_forwards_epic_id_for_missing_root_branch_prompt() -> None:
    agent = AgentHome(
        name="worker",
        agent_id="atelier/worker/codex/p1prompt",
        role="worker",
        path=Path("/tmp/worker"),
        session_key="p1prompt",
    )
    deps = _build_runner_deps(
        startup_result=StartupContractResult(
            epic_id="at-uuzc",
            changeset_id=None,
            should_exit=False,
            reason="selected_auto",
        ),
        preview_agent=agent,
    )
    deps.infra.beads.claim_epic = Mock(
        return_value={"id": "at-uuzc", "title": "Collision proof startup"}
    )
    deps.infra.beads.extract_workspace_root_branch = Mock(return_value="")
    deps.lifecycle.extract_changeset_root_branch = lambda _issue: ""
    deps.infra.branching.suggest_root_branch = Mock(
        return_value="feat/collision-proof-startup-at-uuzc"
    )
    deps.infra.root_branch.prompt_root_branch = Mock(
        return_value="feat/collision-proof-startup-at-uuzc"
    )

    summary = runner.run_worker_once(
        SimpleNamespace(epic_id=None, queue=False, yes=True, reconcile=False),
        run_context=WorkerRunContext(mode="auto", dry_run=False, session_key="p1prompt"),
        deps=deps,
    )

    assert summary.started is False
    assert summary.reason == "no_ready_changesets"
    assert summary.epic_id == "at-uuzc"
    assert deps.infra.branching.suggest_root_branch.call_args.kwargs["bead_id"] == "at-uuzc"
    assert deps.infra.root_branch.prompt_root_branch.call_args.kwargs["epic_id"] == "at-uuzc"
    assert deps.infra.root_branch.prompt_root_branch.call_args.kwargs["assume_yes"] is True
    deps.infra.beads.update_workspace_root_branch.assert_called_once_with(
        "at-uuzc",
        "feat/collision-proof-startup-at-uuzc",
        beads_root=Path("/project/.atelier/.beads"),
        cwd=Path("/repo"),
    )


def test_run_worker_once_auto_confirms_unique_bead_suffix_root_branch() -> None:
    agent = AgentHome(
        name="worker",
        agent_id="atelier/worker/codex/p1autoc",
        role="worker",
        path=Path("/tmp/worker"),
        session_key="p1autoc",
    )
    deps = _build_runner_deps(
        startup_result=StartupContractResult(
            epic_id="at-uuzc",
            changeset_id=None,
            should_exit=False,
            reason="selected_auto",
        ),
        preview_agent=agent,
    )
    deps.infra.beads.claim_epic = Mock(
        return_value={"id": "at-uuzc", "title": "Collision proof startup"}
    )
    deps.infra.beads.extract_workspace_root_branch = Mock(return_value="")
    deps.lifecycle.extract_changeset_root_branch = lambda _issue: ""
    deps.infra.root_branch.prompt_root_branch = Mock(
        side_effect=AssertionError("prompt_root_branch should not be called")
    )
    local_refs = subprocess.CompletedProcess(
        args=["git", "for-each-ref"],
        returncode=0,
        stdout="feat/collision-proof-startup-at-uuzc.1\n",
        stderr="",
    )

    with patch("atelier.exec.try_run_command", return_value=local_refs):
        summary = runner.run_worker_once(
            SimpleNamespace(epic_id=None, queue=False, yes=False, reconcile=False),
            run_context=WorkerRunContext(mode="auto", dry_run=False, session_key="p1autoc"),
            deps=deps,
        )

    assert summary.started is False
    assert summary.reason == "no_ready_changesets"
    assert summary.epic_id == "at-uuzc"
    deps.infra.beads.update_workspace_root_branch.assert_called_once_with(
        "at-uuzc",
        "feat/collision-proof-startup-at-uuzc.1",
        beads_root=Path("/project/.atelier/.beads"),
        cwd=Path("/repo"),
    )
    assert any(
        "auto-confirmed via bead-suffix rule" in str(call.args[0])
        for call in deps.control._say.call_args_list
    )


def test_run_worker_once_multiple_bead_suffix_matches_fall_back_to_prompt() -> None:
    agent = AgentHome(
        name="worker",
        agent_id="atelier/worker/codex/p1multi",
        role="worker",
        path=Path("/tmp/worker"),
        session_key="p1multi",
    )
    deps = _build_runner_deps(
        startup_result=StartupContractResult(
            epic_id="at-uuzc",
            changeset_id=None,
            should_exit=False,
            reason="selected_auto",
        ),
        preview_agent=agent,
    )
    deps.infra.beads.claim_epic = Mock(
        return_value={"id": "at-uuzc", "title": "Collision proof startup"}
    )
    deps.infra.beads.extract_workspace_root_branch = Mock(return_value="")
    deps.lifecycle.extract_changeset_root_branch = lambda _issue: ""
    deps.infra.root_branch.prompt_root_branch = Mock(
        return_value="feat/collision-proof-startup-at-uuzc.2"
    )
    local_refs = subprocess.CompletedProcess(
        args=["git", "for-each-ref"],
        returncode=0,
        stdout=("feat/collision-proof-startup-at-uuzc\nfeat/collision-proof-startup-at-uuzc.1\n"),
        stderr="",
    )

    with patch("atelier.exec.try_run_command", return_value=local_refs):
        summary = runner.run_worker_once(
            SimpleNamespace(epic_id=None, queue=False, yes=False, reconcile=False),
            run_context=WorkerRunContext(mode="auto", dry_run=False, session_key="p1multi"),
            deps=deps,
        )

    assert summary.started is False
    assert summary.reason == "no_ready_changesets"
    assert summary.epic_id == "at-uuzc"
    deps.infra.root_branch.prompt_root_branch.assert_called_once()
    deps.infra.beads.update_workspace_root_branch.assert_called_once_with(
        "at-uuzc",
        "feat/collision-proof-startup-at-uuzc.2",
        beads_root=Path("/project/.atelier/.beads"),
        cwd=Path("/repo"),
    )
    assert any(
        "multiple local bead-suffix matches" in str(call.args[0])
        for call in deps.control._say.call_args_list
    )


def test_run_worker_once_nonmatching_suffix_falls_back_to_prompt() -> None:
    agent = AgentHome(
        name="worker",
        agent_id="atelier/worker/codex/p1nomatch",
        role="worker",
        path=Path("/tmp/worker"),
        session_key="p1nomatch",
    )
    deps = _build_runner_deps(
        startup_result=StartupContractResult(
            epic_id="at-uuzc",
            changeset_id=None,
            should_exit=False,
            reason="selected_auto",
        ),
        preview_agent=agent,
    )
    deps.infra.beads.claim_epic = Mock(
        return_value={"id": "at-uuzc", "title": "Collision proof startup"}
    )
    deps.infra.beads.extract_workspace_root_branch = Mock(return_value="")
    deps.lifecycle.extract_changeset_root_branch = lambda _issue: ""
    deps.infra.root_branch.prompt_root_branch = Mock(
        return_value="feat/collision-proof-startup-at-uuzc"
    )
    local_refs = subprocess.CompletedProcess(
        args=["git", "for-each-ref"],
        returncode=0,
        stdout="feat/unrelated\n",
        stderr="",
    )

    with patch("atelier.exec.try_run_command", return_value=local_refs):
        summary = runner.run_worker_once(
            SimpleNamespace(epic_id=None, queue=False, yes=False, reconcile=False),
            run_context=WorkerRunContext(mode="auto", dry_run=False, session_key="p1nomatch"),
            deps=deps,
        )

    assert summary.started is False
    assert summary.reason == "no_ready_changesets"
    assert summary.epic_id == "at-uuzc"
    deps.infra.root_branch.prompt_root_branch.assert_called_once()
    deps.infra.beads.update_workspace_root_branch.assert_called_once_with(
        "at-uuzc",
        "feat/collision-proof-startup-at-uuzc",
        beads_root=Path("/project/.atelier/.beads"),
        cwd=Path("/repo"),
    )
    assert any(
        "no local bead-suffix match for at-uuzc" in str(call.args[0])
        for call in deps.control._say.call_args_list
    )


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


def test_run_worker_once_retries_claim_as_stale_reclaim_after_claim_time_conflict() -> None:
    agent = AgentHome(
        name="worker",
        agent_id="atelier/worker/codex/p3c",
        role="worker",
        path=Path("/tmp/worker"),
        session_key="p3c",
    )
    stale_assignee = "atelier/worker/codex/runtime"
    deps = _build_runner_deps(
        startup_result=StartupContractResult(
            epic_id="at-conflict",
            changeset_id=None,
            should_exit=False,
            reason="selected_auto",
        ),
        preview_agent=agent,
    )

    claim_calls: list[str | None] = []

    def claim_epic(
        epic_id: str,
        *_args: object,
        allow_takeover_from: str | None = None,
        **_kwargs: object,
    ) -> dict[str, object]:
        assert epic_id == "at-conflict"
        claim_calls.append(allow_takeover_from)
        if allow_takeover_from is None:
            raise SystemExit(1)
        return {"id": epic_id, "title": epic_id}

    def run_bd_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:  # noqa: ARG001
        if args[:2] == ["show", "at-conflict"]:
            return [{"id": "at-conflict", "assignee": stale_assignee}]
        return []

    def run_bd_command(
        args: list[str], *, beads_root: Path, cwd: Path, allow_failure: bool = False
    ):  # noqa: ANN001, ARG001
        if args[:3] == ["slot", "show", "at-stale-agent"]:
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout='{"slots":{"hook":null}}',
                stderr="",
            )
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    deps.infra.beads.claim_epic = Mock(side_effect=claim_epic)
    deps.infra.beads.run_bd_json = Mock(side_effect=run_bd_json)
    deps.infra.beads.run_bd_command = Mock(side_effect=run_bd_command)
    deps.infra.beads.find_agent_bead = Mock(
        side_effect=lambda agent_id, **_kwargs: (
            {
                "id": "at-stale-agent",
                "description": "heartbeat_at: 2026-02-01T00:00:00Z\n",
            }
            if agent_id == stale_assignee
            else {"id": "at-agent"}
        )
    )

    summary = runner.run_worker_once(
        SimpleNamespace(epic_id=None, queue=False, yes=False, reconcile=False),
        run_context=WorkerRunContext(mode="auto", dry_run=False, session_key="p3c"),
        deps=deps,
    )

    assert summary.started is False
    assert summary.reason == "no_ready_changesets"
    assert summary.epic_id == "at-conflict"
    assert claim_calls == [None, stale_assignee]
    assert any(
        "Retrying stale-assignee reclaim after claim conflict" in str(call.args[0])
        for call in deps.control._say.call_args_list
    )
    deps.infra.beads.clear_agent_hook.assert_any_call(
        "at-stale-agent",
        beads_root=Path("/project/.atelier/.beads"),
        cwd=Path("/repo"),
        expected_hook="at-conflict",
    )


def test_classify_claim_failure_fails_closed_when_hook_lookup_fails() -> None:
    stale_assignee = "atelier/worker/codex/p777"
    beads = SimpleNamespace(
        run_bd_json=Mock(return_value=[{"id": "at-conflict", "assignee": stale_assignee}]),
        find_agent_bead=Mock(return_value={"id": "at-stale-agent"}),
        run_bd_command=Mock(
            return_value=subprocess.CompletedProcess(
                args=["slot", "show", "at-stale-agent", "--json"],
                returncode=1,
                stdout="",
                stderr="slot read failed",
            )
        ),
    )

    with patch(
        "atelier.worker.session.runner.agent_home.is_session_agent_active",
        return_value=True,
    ):
        failure = runner._classify_claim_failure(  # pyright: ignore[reportPrivateUsage]
            beads=beads,
            epic_id="at-conflict",
            agent_id="atelier/worker/codex/p3c",
            allow_takeover_from=None,
            beads_root=Path("/project/.atelier/.beads"),
            repo_root=Path("/repo"),
        )

    assert failure.kind == "assignee_conflict"
    assert failure.assignee == stale_assignee
    assert failure.detail == "hook_lookup_failed"


def test_run_worker_once_reclaims_stale_explicit_assignment_and_clears_old_hook() -> None:
    agent = AgentHome(
        name="worker",
        agent_id="atelier/worker/codex/p3b",
        role="worker",
        path=Path("/tmp/worker"),
        session_key="p3b",
    )
    stale_assignee = "atelier/worker/codex/p777"
    deps = _build_runner_deps(
        startup_result=StartupContractResult(
            epic_id="at-explicit",
            changeset_id=None,
            should_exit=False,
            reason="explicit_epic",
            reassign_from=stale_assignee,
        ),
        preview_agent=agent,
    )
    deps.infra.beads.find_agent_bead = Mock(
        side_effect=lambda agent_id, **_kwargs: (
            {"id": "at-previous-agent"} if agent_id == stale_assignee else {"id": "at-agent"}
        )
    )

    summary = runner.run_worker_once(
        SimpleNamespace(epic_id="at-explicit", queue=False, yes=False, reconcile=False),
        run_context=WorkerRunContext(mode="auto", dry_run=False, session_key="p3b"),
        deps=deps,
    )

    assert summary.started is False
    assert summary.reason == "no_ready_changesets"
    assert summary.epic_id == "at-explicit"
    deps.infra.beads.claim_epic.assert_called_once_with(
        "at-explicit",
        "atelier/worker/codex/p3b",
        beads_root=Path("/project/.atelier/.beads"),
        cwd=Path("/repo"),
        allow_takeover_from=stale_assignee,
    )
    assert deps.infra.beads.clear_agent_hook.call_args_list == [
        call(
            "at-previous-agent",
            beads_root=Path("/project/.atelier/.beads"),
            cwd=Path("/repo"),
            expected_hook="at-explicit",
        ),
        call(
            "at-agent",
            beads_root=Path("/project/.atelier/.beads"),
            cwd=Path("/repo"),
            expected_hook="at-explicit",
        ),
    ]


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
    notification = deps.lifecycle.send_planner_notification.call_args.kwargs
    assert "Startup state: Startup Beads state:" in str(notification.get("body"))
    deps.lifecycle.release_epic_assignment.assert_called_once_with(
        "at-epic",
        agent_id="atelier/worker/codex/p5",
        beads_root=Path("/project/.atelier/.beads"),
        repo_root=Path("/repo"),
    )
    deps.infra.beads.clear_agent_hook.assert_called_once_with(
        "at-agent",
        beads_root=Path("/project/.atelier/.beads"),
        cwd=Path("/repo"),
        expected_hook="at-epic",
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

    def run_bd_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:  # noqa: ARG001
        if args[:2] == ["show", "at-epic.1"]:
            raise SystemExit(1)
        return []

    deps.infra.beads.run_bd_json = Mock(side_effect=run_bd_json)
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
    notification = deps.lifecycle.send_planner_notification.call_args.kwargs
    assert "Startup state: Startup Beads state:" in str(notification.get("body"))
    deps.lifecycle.release_epic_assignment.assert_called_once_with(
        "at-epic",
        agent_id="atelier/worker/codex/p6",
        beads_root=Path("/project/.atelier/.beads"),
        repo_root=Path("/repo"),
    )
    deps.infra.beads.clear_agent_hook.assert_called_once_with(
        "at-agent",
        beads_root=Path("/project/.atelier/.beads"),
        cwd=Path("/repo"),
        expected_hook="at-epic",
    )
    assert not deps.control._die.called


def test_run_worker_once_blocks_changeset_on_non_recoverable_worktree_prep_error() -> None:
    agent = AgentHome(
        name="worker",
        agent_id="atelier/worker/codex/p6b",
        role="worker",
        path=Path("/tmp/worker"),
        session_key="p6b",
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
    deps.infra.beads.run_bd_json = Mock(
        side_effect=lambda args, **_kwargs: (
            [{"id": "at-epic.1", "title": "Changeset", "description": ""}]
            if args[:2] == ["show", "at-epic.1"]
            else []
        )
    )
    deps.infra.worker_session_worktree.prepare_worktrees = Mock(
        side_effect=RuntimeError(
            "worktree mapping migration blocked: expected 'feat/old' or 'feat/new'"
        )
    )
    deps.lifecycle.mark_changeset_blocked = Mock()
    deps.lifecycle.send_planner_notification = Mock()
    deps.lifecycle.release_epic_assignment = Mock()
    deps.infra.beads.clear_agent_hook = Mock()

    summary = runner.run_worker_once(
        SimpleNamespace(epic_id=None, queue=False, yes=False, reconcile=False),
        run_context=WorkerRunContext(mode="auto", dry_run=False, session_key="p6b"),
        deps=deps,
    )

    assert summary.started is False
    assert summary.reason == "changeset_startup_preparation_blocked"
    assert summary.epic_id == "at-epic"
    assert summary.changeset_id == "at-epic.1"
    assert deps.infra.worker_session_worktree.prepare_worktrees.call_count == 1
    deps.lifecycle.mark_changeset_blocked.assert_called_once()
    blocked_args = deps.lifecycle.mark_changeset_blocked.call_args.kwargs
    assert "startup preparation failed at prepare worktrees" in str(blocked_args["reason"])
    deps.lifecycle.send_planner_notification.assert_called_once()
    subject = str(deps.lifecycle.send_planner_notification.call_args.kwargs["subject"])
    assert subject == "NEEDS-DECISION: Startup preparation failed (at-epic.1)"
    deps.lifecycle.release_epic_assignment.assert_called_once_with(
        "at-epic",
        agent_id="atelier/worker/codex/p6b",
        beads_root=Path("/project/.atelier/.beads"),
        repo_root=Path("/repo"),
    )
    deps.infra.beads.clear_agent_hook.assert_called_once_with(
        "at-agent",
        beads_root=Path("/project/.atelier/.beads"),
        cwd=Path("/repo"),
        expected_hook="at-epic",
    )
    assert not deps.control._die.called


def test_run_worker_once_retries_transient_prepare_worktree_failures_before_blocking() -> None:
    agent = AgentHome(
        name="worker",
        agent_id="atelier/worker/codex/p6bt",
        role="worker",
        path=Path("/tmp/worker"),
        session_key="p6bt",
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
    deps.infra.beads.run_bd_json = Mock(
        side_effect=lambda args, **_kwargs: (
            [{"id": "at-epic.1", "title": "Changeset", "description": ""}]
            if args[:2] == ["show", "at-epic.1"]
            else []
        )
    )
    deps.infra.worker_session_worktree.prepare_worktrees = Mock(
        side_effect=[
            RuntimeError(
                "command failed: git -C /repo worktree add /tmp/worktrees/at-epic.1 feat/branch "
                "(exit 128)\nstderr:\nfatal: Unable to create '/repo/.git/index.lock': File exists."
            ),
            RuntimeError(
                "command failed: git -C /repo worktree add /tmp/worktrees/at-epic.1 feat/branch "
                "(exit 128)\nstderr:\nfatal: Unable to create '/repo/.git/index.lock': File exists."
            ),
        ]
    )
    deps.lifecycle.mark_changeset_blocked = Mock()
    deps.lifecycle.send_planner_notification = Mock()
    deps.lifecycle.release_epic_assignment = Mock()
    deps.infra.beads.clear_agent_hook = Mock()

    summary = runner.run_worker_once(
        SimpleNamespace(epic_id=None, queue=False, yes=False, reconcile=False),
        run_context=WorkerRunContext(mode="auto", dry_run=False, session_key="p6bt"),
        deps=deps,
    )

    assert summary.started is False
    assert summary.reason == "changeset_startup_preparation_blocked"
    assert summary.epic_id == "at-epic"
    assert summary.changeset_id == "at-epic.1"
    assert deps.infra.worker_session_worktree.prepare_worktrees.call_count == 2
    retry_logs = [str(call.args[0]) for call in deps.control._say.call_args_list]
    assert any("Prepare worktrees transient failure; retrying" in line for line in retry_logs)
    deps.lifecycle.mark_changeset_blocked.assert_called_once()
    blocked_reason = str(deps.lifecycle.mark_changeset_blocked.call_args.kwargs["reason"])
    assert "attempt 1/2" in blocked_reason
    assert "attempt 2/2" in blocked_reason
    assert "index.lock" in blocked_reason
    deps.lifecycle.send_planner_notification.assert_called_once()
    notification_body = str(deps.lifecycle.send_planner_notification.call_args.kwargs["body"])
    assert "attempt 1/2" in notification_body
    assert "attempt 2/2" in notification_body
    assert "index.lock" in notification_body
    deps.lifecycle.release_epic_assignment.assert_called_once_with(
        "at-epic",
        agent_id="atelier/worker/codex/p6bt",
        beads_root=Path("/project/.atelier/.beads"),
        repo_root=Path("/repo"),
    )
    deps.infra.beads.clear_agent_hook.assert_called_once_with(
        "at-agent",
        beads_root=Path("/project/.atelier/.beads"),
        cwd=Path("/repo"),
        expected_hook="at-epic",
    )


def test_run_worker_once_reports_worker_template_load_failure_reason_code() -> None:
    agent = AgentHome(
        name="worker",
        agent_id="atelier/worker/codex/p6c",
        role="worker",
        path=Path("/tmp/worker"),
        session_key="p6c",
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
        side_effect=RuntimeError(
            "worker_template_load_failed: epic=at-epic; worktree=/tmp/changeset; "
            "template=AGENTS.worker.md.tmpl; fallback_attempts=installed cache missing: "
            "/tmp/cache/AGENTS.worker.md.tmpl | packaged default unreadable: "
            "/tmp/worktree/src/atelier/templates/AGENTS.worker.md.tmpl "
            "(FileNotFoundError: missing)"
        )
    )
    deps.lifecycle.mark_changeset_blocked = Mock()
    deps.lifecycle.send_planner_notification = Mock()
    deps.lifecycle.release_epic_assignment = Mock()
    deps.infra.beads.clear_agent_hook = Mock()

    summary = runner.run_worker_once(
        SimpleNamespace(epic_id=None, queue=False, yes=False, reconcile=False),
        run_context=WorkerRunContext(mode="auto", dry_run=False, session_key="p6c"),
        deps=deps,
    )

    assert summary.started is False
    assert summary.reason == "worker_template_unavailable"
    assert summary.epic_id == "at-epic"
    assert summary.changeset_id == "at-epic.1"
    deps.lifecycle.mark_changeset_blocked.assert_called_once()
    blocked_reason = str(deps.lifecycle.mark_changeset_blocked.call_args.kwargs["reason"])
    assert "startup preparation failed at prepare agent session" in blocked_reason
    assert "worker_template_load_failed:" in blocked_reason
    deps.lifecycle.send_planner_notification.assert_called_once()
    notification_body = str(deps.lifecycle.send_planner_notification.call_args.kwargs["body"])
    assert "Epic: at-epic" in notification_body
    assert "Changeset: at-epic.1" in notification_body
    assert "Stage: prepare agent session" in notification_body
    assert "AGENTS.worker.md.tmpl" in notification_body
    assert "fallback_attempts=" in notification_body
    deps.lifecycle.release_epic_assignment.assert_called_once_with(
        "at-epic",
        agent_id="atelier/worker/codex/p6c",
        beads_root=Path("/project/.atelier/.beads"),
        repo_root=Path("/repo"),
    )
    deps.infra.beads.clear_agent_hook.assert_called_once_with(
        "at-agent",
        beads_root=Path("/project/.atelier/.beads"),
        cwd=Path("/repo"),
        expected_hook="at-epic",
    )
    assert not deps.control._die.called


def test_run_worker_once_short_circuits_terminal_finalize_before_agent_startup() -> None:
    agent = AgentHome(
        name="worker",
        agent_id="atelier/worker/codex/p6d",
        role="worker",
        path=Path("/tmp/worker"),
        session_key="p6d",
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
    _, project_config, _, _ = deps.infra.resolve_current_project_with_repo_root.return_value
    project_config.branch.pr_mode = "ready"
    selected_changeset = {
        "id": "at-epic.1",
        "title": "Changeset",
        "status": "in_progress",
        "labels": [],
        "description": "changeset.work_branch: feat/root-at-epic.1\n",
    }
    deps.lifecycle.next_changeset = lambda **_kwargs: selected_changeset
    deps.infra.beads.run_bd_json = Mock(
        side_effect=lambda args, **_kwargs: (
            [selected_changeset] if args[:2] == ["show", "at-epic.1"] else []
        )
    )
    deps.lifecycle.startup_finalize_preflight = Mock(
        return_value=StartupFinalizePreflightResult(
            should_finalize_only=True,
            reason="finalize_only:pr_lifecycle_merged_integration_proven",
        )
    )
    deps.lifecycle.finalize_changeset = Mock(
        return_value=FinalizeResult(
            continue_running=True,
            reason="changeset_complete",
        )
    )
    deps.lifecycle.mark_changeset_in_progress = Mock()

    summary = runner.run_worker_once(
        SimpleNamespace(epic_id=None, queue=False, yes=False, reconcile=False),
        run_context=WorkerRunContext(mode="auto", dry_run=False, session_key="p6d"),
        deps=deps,
    )

    assert summary.started is True
    assert summary.reason == "startup_finalize_only"
    assert summary.epic_id == "at-epic"
    assert summary.changeset_id == "at-epic.1"
    deps.lifecycle.startup_finalize_preflight.assert_called_once_with(
        issue=selected_changeset,
        repo_slug="org/repo",
        branch_pr=True,
        repo_root=Path("/repo"),
        git_path="git",
    )
    deps.lifecycle.finalize_changeset.assert_called_once()
    finalize_kwargs = deps.lifecycle.finalize_changeset.call_args.kwargs
    assert finalize_kwargs["changeset_id"] == "at-epic.1"
    assert finalize_kwargs["epic_id"] == "at-epic"
    assert finalize_kwargs["squash_message_agent_spec"] is None
    assert finalize_kwargs["squash_message_agent_options"] == []
    assert finalize_kwargs["squash_message_agent_home"] == Path("/tmp/worker")
    assert finalize_kwargs["squash_message_agent_env"] == {}
    deps.infra.worker_session_worktree.prepare_worktrees.assert_not_called()
    deps.lifecycle.mark_changeset_in_progress.assert_not_called()
    deps.infra.worker_session_agent.prepare_agent_session.assert_not_called()
    deps.infra.worker_session_agent.start_agent_session.assert_not_called()
    assert any(
        "Skipping worker agent startup; finalizing changeset via startup preflight"
        in str(call.args[0])
        for call in deps.control._say.call_args_list
    )


def test_run_worker_once_dry_run_short_circuits_terminal_finalize_without_mutation() -> None:
    agent = AgentHome(
        name="worker",
        agent_id="atelier/worker/codex/p6dr",
        role="worker",
        path=Path("/tmp/worker"),
        session_key="p6dr",
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
    dry_run_logs: list[str] = []
    deps.control.dry_run_log = dry_run_logs.append  # type: ignore[method-assign]
    selected_changeset = {
        "id": "at-epic.1",
        "title": "Changeset",
        "status": "in_progress",
        "labels": [],
        "description": "changeset.work_branch: feat/root-at-epic.1\n",
    }
    deps.lifecycle.next_changeset = lambda **_kwargs: selected_changeset
    deps.infra.beads.run_bd_json = Mock(
        side_effect=lambda args, **_kwargs: (
            [{"id": "at-epic", "title": "Epic", "description": ""}]
            if args[:2] == ["show", "at-epic"]
            else []
        )
    )
    deps.lifecycle.startup_finalize_preflight = Mock(
        return_value=StartupFinalizePreflightResult(
            should_finalize_only=True,
            reason="finalize_only:pr_lifecycle_merged_integration_proven",
        )
    )
    deps.lifecycle.finalize_changeset = Mock(
        return_value=FinalizeResult(
            continue_running=True,
            reason="changeset_complete",
        )
    )

    summary = runner.run_worker_once(
        SimpleNamespace(epic_id=None, queue=False, yes=False, reconcile=False),
        run_context=WorkerRunContext(mode="auto", dry_run=True, session_key="p6dr"),
        deps=deps,
    )

    assert summary.started is False
    assert summary.reason == "dry_run"
    assert summary.epic_id == "at-epic"
    assert summary.changeset_id == "at-epic.1"
    deps.lifecycle.finalize_changeset.assert_not_called()
    deps.infra.worker_session_worktree.prepare_worktrees.assert_not_called()
    deps.infra.worker_session_agent.prepare_agent_session.assert_not_called()
    deps.infra.worker_session_agent.start_agent_session.assert_not_called()
    assert any(
        "Startup preflight would skip worker agent startup and finalize changeset" in message
        for message in dry_run_logs
    )


def test_run_worker_once_startup_finalize_dependency_gate_failure_returns_summary() -> None:
    agent = AgentHome(
        name="worker",
        agent_id="atelier/worker/codex/p6e",
        role="worker",
        path=Path("/tmp/worker"),
        session_key="p6e",
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
    selected_changeset = {
        "id": "at-epic.1",
        "title": "Changeset",
        "status": "in_progress",
        "labels": [],
        "description": "changeset.work_branch: feat/root-at-epic.1\n",
    }
    deps.lifecycle.next_changeset = lambda **_kwargs: selected_changeset
    deps.infra.beads.run_bd_json = Mock(
        side_effect=lambda args, **_kwargs: (
            [selected_changeset] if args[:2] == ["show", "at-epic.1"] else []
        )
    )
    deps.lifecycle.startup_finalize_preflight = Mock(
        return_value=StartupFinalizePreflightResult(
            should_finalize_only=True,
            reason="finalize_only:pr_lifecycle_merged_integration_proven",
        )
    )
    deps.lifecycle.finalize_changeset = Mock(
        side_effect=SystemExit(
            "cannot set changeset at-epic.1 to in_progress: blocking dependencies "
            "not complete (at-epic.0(in_progress)). Close dependencies before retrying."
        )
    )

    summary = runner.run_worker_once(
        SimpleNamespace(epic_id=None, queue=False, yes=False, reconcile=False),
        run_context=WorkerRunContext(mode="auto", dry_run=False, session_key="p6e"),
        deps=deps,
    )

    assert summary.started is False
    assert summary.reason == "changeset_finalize_in_progress_dependency_gate_failed"
    assert summary.epic_id == "at-epic"
    assert summary.changeset_id == "at-epic.1"
    deps.lifecycle.finalize_changeset.assert_called_once()
    deps.infra.worker_session_worktree.prepare_worktrees.assert_not_called()
    deps.infra.worker_session_agent.prepare_agent_session.assert_not_called()
    deps.infra.worker_session_agent.start_agent_session.assert_not_called()
    assert any(
        "Finalize status recovery hit dependency-gate rejection" in str(call.args[0])
        for call in deps.control._say.call_args_list
    )


def test_run_worker_once_startup_finalize_non_dependency_gate_failure_reraises() -> None:
    agent = AgentHome(
        name="worker",
        agent_id="atelier/worker/codex/p6e1",
        role="worker",
        path=Path("/tmp/worker"),
        session_key="p6e1",
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
    selected_changeset = {
        "id": "at-epic.1",
        "title": "Changeset",
        "status": "in_progress",
        "labels": [],
        "description": "changeset.work_branch: feat/root-at-epic.1\n",
    }
    deps.lifecycle.next_changeset = lambda **_kwargs: selected_changeset
    deps.infra.beads.run_bd_json = Mock(
        side_effect=lambda args, **_kwargs: (
            [selected_changeset] if args[:2] == ["show", "at-epic.1"] else []
        )
    )
    deps.lifecycle.startup_finalize_preflight = Mock(
        return_value=StartupFinalizePreflightResult(
            should_finalize_only=True,
            reason="finalize_only:pr_lifecycle_merged_integration_proven",
        )
    )
    deps.lifecycle.finalize_changeset = Mock(
        side_effect=SystemExit("failed to load finalize metadata cursor")
    )

    with pytest.raises(SystemExit, match="failed to load finalize metadata cursor"):
        runner.run_worker_once(
            SimpleNamespace(epic_id=None, queue=False, yes=False, reconcile=False),
            run_context=WorkerRunContext(mode="auto", dry_run=False, session_key="p6e1"),
            deps=deps,
        )

    deps.lifecycle.finalize_changeset.assert_called_once()
    deps.infra.worker_session_worktree.prepare_worktrees.assert_not_called()
    deps.infra.worker_session_agent.prepare_agent_session.assert_not_called()
    deps.infra.worker_session_agent.start_agent_session.assert_not_called()
    assert not any(
        "Finalize status recovery hit dependency-gate rejection" in str(call.args[0])
        for call in deps.control._say.call_args_list
    )


def test_run_worker_once_finalize_dependency_gate_failure_returns_summary() -> None:
    agent = AgentHome(
        name="worker",
        agent_id="atelier/worker/codex/p6f",
        role="worker",
        path=Path("/tmp/worker"),
        session_key="p6f",
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
    selected_changeset = {
        "id": "at-epic.1",
        "title": "Changeset",
        "status": "open",
        "labels": [],
        "description": "changeset.work_branch: feat/root-at-epic.1\n",
    }
    deps.lifecycle.next_changeset = lambda **_kwargs: selected_changeset
    deps.infra.beads.run_bd_json = Mock(
        side_effect=lambda args, **_kwargs: (
            [selected_changeset] if args[:2] == ["show", "at-epic.1"] else []
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
            agent_spec=SimpleNamespace(name="codex", display_name="Codex"),
            agent_options=[],
            project_enlistment=Path("/repo"),
            workspace_branch="feat/root-at-epic.1",
            env={},
        )
    )
    deps.infra.worker_session_agent.start_agent_session = Mock(
        return_value=SimpleNamespace(
            started_at=dt.datetime.now(dt.timezone.utc),
            returncode=0,
        )
    )
    deps.lifecycle.finalize_changeset = Mock(
        side_effect=SystemExit(
            "cannot set changeset at-epic.1 to in_progress: blocking dependencies "
            "not complete (at-epic.0(in_progress)). Close dependencies before retrying."
        )
    )

    summary = runner.run_worker_once(
        SimpleNamespace(epic_id=None, queue=False, yes=False, reconcile=False),
        run_context=WorkerRunContext(mode="auto", dry_run=False, session_key="p6f"),
        deps=deps,
    )

    assert summary.started is False
    assert summary.reason == "changeset_finalize_in_progress_dependency_gate_failed"
    assert summary.epic_id == "at-epic"
    assert summary.changeset_id == "at-epic.1"
    deps.infra.worker_session_agent.start_agent_session.assert_called_once()
    deps.lifecycle.finalize_changeset.assert_called_once()
    assert any(
        "Finalize status recovery hit dependency-gate rejection" in str(call.args[0])
        for call in deps.control._say.call_args_list
    )


def test_run_worker_once_finalize_non_dependency_gate_failure_reraises() -> None:
    agent = AgentHome(
        name="worker",
        agent_id="atelier/worker/codex/p6f1",
        role="worker",
        path=Path("/tmp/worker"),
        session_key="p6f1",
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
    selected_changeset = {
        "id": "at-epic.1",
        "title": "Changeset",
        "status": "open",
        "labels": [],
        "description": "changeset.work_branch: feat/root-at-epic.1\n",
    }
    deps.lifecycle.next_changeset = lambda **_kwargs: selected_changeset
    deps.infra.beads.run_bd_json = Mock(
        side_effect=lambda args, **_kwargs: (
            [selected_changeset] if args[:2] == ["show", "at-epic.1"] else []
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
            agent_spec=SimpleNamespace(name="codex", display_name="Codex"),
            agent_options=[],
            project_enlistment=Path("/repo"),
            workspace_branch="feat/root-at-epic.1",
            env={},
        )
    )
    deps.infra.worker_session_agent.start_agent_session = Mock(
        return_value=SimpleNamespace(
            started_at=dt.datetime.now(dt.timezone.utc),
            returncode=0,
        )
    )
    deps.lifecycle.finalize_changeset = Mock(
        side_effect=SystemExit("failed to persist finalize completion metadata")
    )

    with pytest.raises(SystemExit, match="failed to persist finalize completion metadata"):
        runner.run_worker_once(
            SimpleNamespace(epic_id=None, queue=False, yes=False, reconcile=False),
            run_context=WorkerRunContext(mode="auto", dry_run=False, session_key="p6f1"),
            deps=deps,
        )

    deps.infra.worker_session_agent.start_agent_session.assert_called_once()
    deps.lifecycle.finalize_changeset.assert_called_once()
    assert not any(
        "Finalize status recovery hit dependency-gate rejection" in str(call.args[0])
        for call in deps.control._say.call_args_list
    )


def test_run_worker_once_continues_after_review_pending_finalize() -> None:
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

    assert summary.started is True
    assert summary.reason == "agent_session_complete"
    deps.infra.worker_session_agent.start_agent_session.assert_called_once()


def test_run_worker_once_passes_opening_prompt_to_non_codex_agents() -> None:
    agent = AgentHome(
        name="worker",
        agent_id="atelier/worker/codex/p8",
        role="worker",
        path=Path("/tmp/worker"),
        session_key="p8",
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
            agent_spec=SimpleNamespace(name="claude", display_name="Claude"),
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
    deps.commands.worker_opening_prompt = Mock(return_value="open-prompt")

    summary = runner.run_worker_once(
        SimpleNamespace(epic_id=None, queue=False, yes=False, reconcile=False, yolo=True),
        run_context=WorkerRunContext(mode="auto", dry_run=False, session_key="p8"),
        deps=deps,
    )

    assert summary.started is True
    assert summary.reason == "agent_session_complete"
    deps.commands.worker_opening_prompt.assert_called_once()
    deps.infra.worker_session_agent.start_agent_session.assert_called_once()
    prep_kwargs = deps.infra.worker_session_agent.prepare_agent_session.call_args.kwargs
    assert prep_kwargs["yolo"] is True
    start_kwargs = deps.infra.worker_session_agent.start_agent_session.call_args.kwargs
    assert start_kwargs["opening_prompt"] == "open-prompt"


def test_run_worker_once_fails_closed_when_bounded_runtime_evidence_is_missing() -> None:
    agent = AgentHome(
        name="worker",
        agent_id="atelier/worker/codex/p-bounded-missing",
        role="worker",
        path=Path("/tmp/worker"),
        session_key="p-bounded-missing",
    )
    deps = _build_runner_deps(
        startup_result=StartupContractResult(
            epic_id="at-epic",
            changeset_id=None,
            should_exit=False,
            reason="selected_auto",
        ),
        preview_agent=agent,
        runtime_profile="trycycle-bounded",
    )
    deps.lifecycle.next_changeset = lambda **_kwargs: {"id": "at-epic.1", "title": "Changeset"}
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
            agent_spec=SimpleNamespace(name="codex", display_name="Codex"),
            agent_options=[],
            project_enlistment=Path("/repo"),
            workspace_branch="feat/root-at-epic.1",
            env={
                "ATELIER_WORKER_RUNTIME_PROFILE": "trycycle-bounded",
                "ATELIER_BOUNDED_RUNTIME_EVIDENCE": "/tmp/missing-evidence.json",
            },
        )
    )
    deps.infra.worker_session_agent.start_agent_session = Mock(
        return_value=SimpleNamespace(started_at=dt.datetime.now(dt.timezone.utc), returncode=0)
    )
    deps.lifecycle.finalize_changeset = Mock()
    deps.lifecycle.mark_changeset_blocked = Mock()

    summary = runner.run_worker_once(
        SimpleNamespace(epic_id=None, queue=False, yes=False, reconcile=False),
        run_context=WorkerRunContext(
            mode="auto",
            dry_run=False,
            session_key="p-bounded-missing",
            runtime_profile="trycycle-bounded",
        ),
        deps=deps,
    )

    assert summary.started is False
    assert summary.reason == "bounded_runtime_convergence_unproven"
    deps.lifecycle.mark_changeset_blocked.assert_called_once()
    deps.lifecycle.finalize_changeset.assert_not_called()


def test_run_worker_once_allows_bounded_runtime_with_valid_evidence(tmp_path: Path) -> None:
    agent = AgentHome(
        name="worker",
        agent_id="atelier/worker/codex/p-bounded-ok",
        role="worker",
        path=tmp_path / "agent-home",
        session_key="p-bounded-ok",
    )
    agent.path.mkdir()
    evidence_path = agent.path / "bounded-runtime-evidence.json"
    deps = _build_runner_deps(
        startup_result=StartupContractResult(
            epic_id="at-epic",
            changeset_id=None,
            should_exit=False,
            reason="selected_auto",
        ),
        preview_agent=agent,
        runtime_profile="trycycle-bounded",
    )
    deps.lifecycle.next_changeset = lambda **_kwargs: {"id": "at-epic.1", "title": "Changeset"}
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
        side_effect=lambda **kwargs: SimpleNamespace(
            agent_spec=SimpleNamespace(name="codex", display_name="Codex"),
            agent_options=[],
            project_enlistment=Path("/repo"),
            workspace_branch="feat/root-at-epic.1",
            env={
                "ATELIER_WORKER_RUNTIME_PROFILE": "trycycle-bounded",
                "ATELIER_BOUNDED_RUNTIME_EVIDENCE": str(
                    kwargs["bounded_runtime_evidence_path_override"]
                ),
            },
        )
    )

    def start_agent_session(**_kwargs):
        evidence_path.write_text(
            '{"status":"converged","helper_session_id":"sess-123"}',
            encoding="utf-8",
        )
        return SimpleNamespace(started_at=dt.datetime.now(dt.timezone.utc), returncode=0)

    deps.infra.worker_session_agent.start_agent_session = Mock(side_effect=start_agent_session)
    deps.lifecycle.finalize_changeset = Mock(
        return_value=FinalizeResult(continue_running=True, reason="changeset_review_pending")
    )
    deps.lifecycle.mark_changeset_blocked = Mock()

    summary = runner.run_worker_once(
        SimpleNamespace(epic_id=None, queue=False, yes=False, reconcile=False),
        run_context=WorkerRunContext(
            mode="auto",
            dry_run=False,
            session_key="p-bounded-ok",
            runtime_profile="trycycle-bounded",
        ),
        deps=deps,
    )

    assert summary.started is True
    assert summary.reason == "agent_session_complete"
    deps.lifecycle.mark_changeset_blocked.assert_not_called()
    deps.lifecycle.finalize_changeset.assert_called_once()
    prepare_kwargs = deps.infra.worker_session_agent.prepare_agent_session.call_args.kwargs
    assert prepare_kwargs["bounded_runtime_evidence_path_override"] == evidence_path


def test_run_worker_once_fails_closed_when_bounded_runtime_evidence_cleanup_fails(
    tmp_path: Path,
) -> None:
    agent = AgentHome(
        name="worker",
        agent_id="atelier/worker/codex/p-bounded-cleanup",
        role="worker",
        path=tmp_path / "agent-home",
        session_key="p-bounded-cleanup",
    )
    agent.path.mkdir()
    evidence_path = agent.path / "bounded-runtime-evidence.json"
    evidence_path.write_text(
        '{"status":"converged","helper_session_id":"stale-sess"}',
        encoding="utf-8",
    )
    deps = _build_runner_deps(
        startup_result=StartupContractResult(
            epic_id="at-epic",
            changeset_id=None,
            should_exit=False,
            reason="selected_auto",
        ),
        preview_agent=agent,
        runtime_profile="trycycle-bounded",
    )
    deps.lifecycle.next_changeset = lambda **_kwargs: {"id": "at-epic.1", "title": "Changeset"}
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
        side_effect=lambda **kwargs: SimpleNamespace(
            agent_spec=SimpleNamespace(name="codex", display_name="Codex"),
            agent_options=[],
            project_enlistment=Path("/repo"),
            workspace_branch="feat/root-at-epic.1",
            env={
                "ATELIER_WORKER_RUNTIME_PROFILE": "trycycle-bounded",
                "ATELIER_BOUNDED_RUNTIME_EVIDENCE": str(
                    kwargs["bounded_runtime_evidence_path_override"]
                ),
            },
        )
    )
    deps.infra.worker_session_agent.start_agent_session = Mock()
    deps.lifecycle.finalize_changeset = Mock()
    deps.lifecycle.mark_changeset_blocked = Mock()

    with patch(
        "atelier.worker.session.runner.work_runtime_profile.clear_bounded_runtime_evidence",
        return_value="bounded runtime convergence unproven: failed to clear stale helper-session evidence",
    ):
        summary = runner.run_worker_once(
            SimpleNamespace(epic_id=None, queue=False, yes=False, reconcile=False),
            run_context=WorkerRunContext(
                mode="auto",
                dry_run=False,
                session_key="p-bounded-cleanup",
                runtime_profile="trycycle-bounded",
            ),
            deps=deps,
        )

    assert summary.started is False
    assert summary.reason == "bounded_runtime_convergence_unproven"
    deps.lifecycle.mark_changeset_blocked.assert_called_once_with(
        "at-epic.1",
        beads_root=Path("/project/.atelier/.beads"),
        repo_root=Path("/repo"),
        reason="bounded runtime convergence unproven: failed to clear stale helper-session evidence",
    )
    deps.infra.worker_session_agent.start_agent_session.assert_not_called()
    deps.lifecycle.finalize_changeset.assert_not_called()


def test_run_worker_once_skips_redundant_mark_in_progress_for_in_progress_changeset() -> None:
    agent = AgentHome(
        name="worker",
        agent_id="atelier/worker/codex/p9",
        role="worker",
        path=Path("/tmp/worker"),
        session_key="p9",
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
    changeset_issue = {
        "id": "at-epic.1",
        "title": "Changeset",
        "status": "in_progress",
        "labels": [],
        "description": "",
    }
    deps.lifecycle.next_changeset = lambda **_kwargs: changeset_issue
    deps.infra.beads.run_bd_json = Mock(
        side_effect=lambda args, **_kwargs: (
            [changeset_issue] if args[:2] == ["show", "at-epic.1"] else []
        )
    )
    deps.lifecycle.mark_changeset_in_progress = Mock()
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
        continue_running=False,
        reason="done",
    )

    summary = runner.run_worker_once(
        SimpleNamespace(epic_id=None, queue=False, yes=False, reconcile=False),
        run_context=WorkerRunContext(mode="auto", dry_run=False, session_key="p9"),
        deps=deps,
    )

    assert summary.started is False
    assert summary.reason == "done"
    deps.lifecycle.mark_changeset_in_progress.assert_not_called()
    deps.infra.worker_session_agent.start_agent_session.assert_called_once()


def test_run_worker_once_loads_worker_thread_messages_before_agent_start() -> None:
    agent = AgentHome(
        name="worker",
        agent_id="atelier/worker/codex/p-thread",
        role="worker",
        path=Path("/tmp/worker"),
        session_key="p-thread",
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
    changeset_issue = {
        "id": "at-epic.1",
        "title": "Handle threaded startup messages",
        "status": "open",
        "labels": [],
        "description": "",
    }
    threaded_message = {
        "id": "at-msg-1",
        "title": "Worker handoff",
        "assignee": "atelier/worker/codex/p-old",
        "description": (
            "---\n"
            "from: atelier/planner/codex/p200\n"
            "thread: at-epic.1\n"
            "---\n\n"
            "Review the work-thread handoff before proceeding."
        ),
    }

    def run_bd_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:  # noqa: ARG001
        if args[:2] == ["show", "at-epic.1"]:
            return [changeset_issue]
        if args and args[0] == "list":
            return [threaded_message]
        return []

    deps.infra.beads.run_bd_json = Mock(side_effect=run_bd_json)
    deps.lifecycle.next_changeset = lambda **_kwargs: changeset_issue
    deps.lifecycle.startup_finalize_preflight = lambda **_kwargs: StartupFinalizePreflightResult(
        should_finalize_only=True,
        reason="finalize_only:pr_lifecycle_merged_integration_proven",
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
    deps.commands.worker_opening_prompt = Mock(return_value="open-prompt")

    summary = runner.run_worker_once(
        SimpleNamespace(epic_id=None, queue=False, yes=False, reconcile=False),
        run_context=WorkerRunContext(mode="auto", dry_run=False, session_key="p-thread"),
        deps=deps,
    )

    assert summary.started is True
    assert summary.reason == "agent_session_complete"
    deps.infra.worker_session_agent.start_agent_session.assert_called_once()
    start_kwargs = deps.infra.worker_session_agent.start_agent_session.call_args.kwargs
    assert (
        "Blocking work-thread messages to process before coding" in start_kwargs["opening_prompt"]
    )
    assert "Review the work-thread handoff before proceeding." in start_kwargs["opening_prompt"]


def test_run_worker_once_followup_dependency_gate_skip_is_non_blocking() -> None:
    for startup_reason in ("review_feedback", "merge_conflict"):
        agent = AgentHome(
            name="worker",
            agent_id=f"atelier/worker/codex/p9b-{startup_reason}",
            role="worker",
            path=Path("/tmp/worker"),
            session_key=f"p9b-{startup_reason}",
        )
        deps = _build_runner_deps(
            startup_result=StartupContractResult(
                epic_id="at-epic",
                changeset_id="at-epic.2",
                should_exit=False,
                reason=startup_reason,
            ),
            preview_agent=agent,
        )
        selected_changeset = {
            "id": "at-epic.2",
            "title": "Follow-up",
            "status": "open",
            "labels": [],
            "description": "",
            "dependencies": ["at-epic.1"],
        }
        dependency_issue = {
            "id": "at-epic.1",
            "title": "Blocking dependency",
            "status": "in_progress",
            "labels": [],
            "description": "",
        }

        def run_bd_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:  # noqa: ARG001
            if args[:2] == ["show", "at-epic.2"]:
                return [selected_changeset]
            if args[:2] == ["show", "at-epic.1"]:
                return [dependency_issue]
            if args[:4] == ["list", "--parent", "at-epic.1", "--all"]:
                return []
            return []

        deps.infra.beads.run_bd_json = Mock(side_effect=run_bd_json)
        deps.lifecycle.resolve_epic_id_for_changeset = lambda _issue, **_kwargs: "at-epic"
        deps.lifecycle.mark_changeset_in_progress = Mock()
        deps.lifecycle.capture_review_feedback_snapshot = Mock(return_value=SimpleNamespace())
        deps.infra.worker_session_worktree.prepare_worktrees = Mock(
            return_value=SimpleNamespace(
                epic_worktree_path=Path("/tmp/epic"),
                changeset_worktree_path=Path("/tmp/changeset"),
                branch="feat/root-at-epic.2",
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
            continue_running=False,
            reason="done",
        )

        summary = runner.run_worker_once(
            SimpleNamespace(epic_id=None, queue=False, yes=False, reconcile=False),
            run_context=WorkerRunContext(
                mode="auto", dry_run=False, session_key=f"p9b-{startup_reason}"
            ),
            deps=deps,
        )

        assert summary.started is False
        assert summary.reason == "done"
        deps.lifecycle.mark_changeset_in_progress.assert_not_called()
        deps.infra.worker_session_agent.start_agent_session.assert_called_once()
        assert any(
            "follow-up dependency gate still active" in str(call.args[0])
            for call in deps.control._say.call_args_list
        )


def test_run_worker_once_releases_epic_when_dependency_gate_read_fails() -> None:
    agent = AgentHome(
        name="worker",
        agent_id="atelier/worker/codex/p9c",
        role="worker",
        path=Path("/tmp/worker"),
        session_key="p9c",
    )
    deps = _build_runner_deps(
        startup_result=StartupContractResult(
            epic_id="at-epic",
            changeset_id="at-epic.2",
            should_exit=False,
            reason="review_feedback",
        ),
        preview_agent=agent,
    )
    selected_changeset = {
        "id": "at-epic.2",
        "title": "Follow-up",
        "status": "open",
        "labels": [],
        "description": "",
        "dependencies": ["at-epic.1"],
    }

    def run_bd_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:  # noqa: ARG001
        if args[:2] == ["show", "at-epic.2"]:
            return [selected_changeset]
        if args[:2] == ["show", "at-epic.1"]:
            raise SystemExit(1)
        return []

    deps.infra.beads.run_bd_json = Mock(side_effect=run_bd_json)
    deps.lifecycle.resolve_epic_id_for_changeset = lambda _issue, **_kwargs: "at-epic"
    deps.lifecycle.mark_changeset_in_progress = Mock()
    deps.lifecycle.capture_review_feedback_snapshot = Mock(return_value=SimpleNamespace())
    deps.lifecycle.release_epic_assignment = Mock()
    deps.lifecycle.send_planner_notification = Mock()
    deps.infra.worker_session_worktree.prepare_worktrees = Mock(
        return_value=SimpleNamespace(
            epic_worktree_path=Path("/tmp/epic"),
            changeset_worktree_path=Path("/tmp/changeset"),
            branch="feat/root-at-epic.2",
        )
    )

    summary = runner.run_worker_once(
        SimpleNamespace(epic_id=None, queue=False, yes=False, reconcile=False),
        run_context=WorkerRunContext(mode="auto", dry_run=False, session_key="p9c"),
        deps=deps,
    )

    assert summary.started is False
    assert summary.reason == "changeset_dependency_gate_read_failed"
    assert summary.epic_id == "at-epic"
    deps.lifecycle.send_planner_notification.assert_called_once()
    deps.lifecycle.release_epic_assignment.assert_called_once_with(
        "at-epic",
        agent_id="atelier/worker/codex/p9c",
        beads_root=Path("/project/.atelier/.beads"),
        repo_root=Path("/repo"),
    )
    deps.infra.beads.clear_agent_hook.assert_called_once_with(
        "at-agent",
        beads_root=Path("/project/.atelier/.beads"),
        cwd=Path("/repo"),
        expected_hook="at-epic",
    )
    deps.lifecycle.mark_changeset_in_progress.assert_not_called()
    deps.infra.worker_session_agent.start_agent_session.assert_not_called()

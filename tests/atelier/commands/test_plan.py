from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import atelier.codex as codex
import atelier.commands.plan as plan_cmd
import atelier.external_registry as external_registry
import atelier.worktrees as worktrees
from atelier.agent_home import AgentHome
from atelier.config import ProjectConfig


def _fake_project_payload() -> ProjectConfig:
    return ProjectConfig()


def test_plan_starts_agent_session(tmp_path: Path) -> None:
    worktree_path = tmp_path / "worktrees" / "planner"
    agent = AgentHome(
        name="planner",
        agent_id="atelier/planner/planner",
        role="planner",
        path=Path("/project/agents/planner"),
    )
    calls: list[list[str]] = []
    captured_env: dict[str, str] = {}

    def fake_run_bd_command(args, *, beads_root: Path, cwd: Path, allow_failure: bool = False):
        calls.append(args)

        class Result:
            stdout = ""
            returncode = 0

        return Result()

    def fake_run_codex_command(cmd, *, cwd: Path | None, env: dict | None):
        if env:
            captured_env.update({str(k): str(v) for k, v in env.items()})
        return codex.CodexRunResult(returncode=0, session_id=None, resume_command=None)

    class DummyResult:
        stdout = ""
        returncode = 0

    with (
        patch(
            "atelier.commands.plan.resolve_current_project_with_repo_root",
            return_value=(
                Path("/project"),
                _fake_project_payload(),
                "/repo",
                Path("/repo"),
            ),
        ),
        patch(
            "atelier.commands.plan.config.resolve_project_data_dir",
            return_value=tmp_path,
        ),
        patch(
            "atelier.commands.plan.config.resolve_beads_root",
            return_value=Path("/beads"),
        ),
        patch(
            "atelier.commands.plan.agent_home.resolve_agent_home",
            return_value=agent,
        ),
        patch("atelier.commands.plan.agent_home.cleanup_agent_home") as cleanup_home,
        patch("atelier.commands.plan.beads.ensure_agent_bead"),
        patch(
            "atelier.commands.plan.work_cmd.reconcile_blocked_merged_changesets",
            return_value=SimpleNamespace(scanned=0, actionable=0, reconciled=0, failed=0),
        ) as reconcile,
        patch(
            "atelier.commands.plan.beads.run_bd_command",
            side_effect=fake_run_bd_command,
        ),
        patch("atelier.commands.plan.beads.run_bd_json", return_value=[]),
        patch("atelier.commands.plan.beads.list_inbox_messages", return_value=[]),
        patch("atelier.commands.plan.beads.list_queue_messages", return_value=[]),
        patch("atelier.commands.plan.policy.sync_agent_home_policy"),
        patch("atelier.commands.plan.config.write_project_config"),
        patch("atelier.commands.plan.git.git_default_branch", return_value="main"),
        patch(
            "atelier.commands.plan.worktrees.ensure_git_worktree",
            return_value=worktree_path,
        ) as ensure_git_worktree,
        patch(
            "atelier.commands.plan.codex.run_codex_command",
            side_effect=fake_run_codex_command,
        ),
        patch("atelier.commands.plan.say"),
    ):
        plan_cmd.run_planner(SimpleNamespace(epic_id="atelier-epic", reconcile=True))

    assert calls
    assert calls[0][0] == "prime"
    assert captured_env.get("ATELIER_PLAN_EPIC") == "atelier-epic"
    assert captured_env.get("ATELIER_WORKSPACE") == "main-planner-planner"
    reconcile.assert_called_once()
    cleanup_home.assert_called_once_with(agent, project_dir=tmp_path)
    ensure_git_worktree.assert_called_once_with(
        tmp_path,
        Path("/repo"),
        "planner-planner",
        root_branch="main-planner-planner",
        git_path="git",
    )


def test_plan_does_not_query_or_prompt_draft_epics_on_startup(tmp_path: Path) -> None:
    worktree_path = tmp_path / "worktrees" / "planner"
    agent = AgentHome(
        name="planner",
        agent_id="atelier/planner/planner",
        role="planner",
        path=Path("/project/agents/planner"),
    )
    json_calls: list[list[str]] = []

    def fake_run_bd_command(args, *, beads_root: Path, cwd: Path, allow_failure: bool = False):
        class Result:
            stdout = ""
            returncode = 0

        return Result()

    def fake_run_bd_json(args, *, beads_root: Path, cwd: Path):
        json_calls.append(list(args))
        return []

    with (
        patch(
            "atelier.commands.plan.resolve_current_project_with_repo_root",
            return_value=(
                Path("/project"),
                _fake_project_payload(),
                "/repo",
                Path("/repo"),
            ),
        ),
        patch(
            "atelier.commands.plan.config.resolve_project_data_dir",
            return_value=tmp_path,
        ),
        patch(
            "atelier.commands.plan.config.resolve_beads_root",
            return_value=Path("/beads"),
        ),
        patch(
            "atelier.commands.plan.agent_home.resolve_agent_home",
            return_value=agent,
        ),
        patch("atelier.commands.plan.beads.ensure_agent_bead"),
        patch(
            "atelier.commands.plan.work_cmd.reconcile_blocked_merged_changesets",
            return_value=SimpleNamespace(scanned=0, actionable=0, reconciled=0, failed=0),
        ) as reconcile,
        patch(
            "atelier.commands.plan.beads.run_bd_command",
            side_effect=fake_run_bd_command,
        ),
        patch("atelier.commands.plan.beads.run_bd_json", side_effect=fake_run_bd_json),
        patch("atelier.commands.plan.beads.list_inbox_messages", return_value=[]),
        patch("atelier.commands.plan.beads.list_queue_messages", return_value=[]),
        patch("atelier.commands.plan.policy.sync_agent_home_policy"),
        patch("atelier.commands.plan.config.write_project_config"),
        patch("atelier.commands.plan.git.git_default_branch", return_value="main"),
        patch(
            "atelier.commands.plan.worktrees.ensure_git_worktree",
            return_value=worktree_path,
        ),
        patch(
            "atelier.commands.plan.codex.run_codex_command",
            return_value=codex.CodexRunResult(returncode=0, session_id=None, resume_command=None),
        ),
        patch("atelier.commands.plan.say"),
    ):
        plan_cmd.run_planner(SimpleNamespace(epic_id=None))

    assert not any("at:draft" in call for call in json_calls)
    reconcile.assert_not_called()


def test_plan_template_variables_include_provider_info(tmp_path: Path) -> None:
    worktree_path = tmp_path / "worktrees" / "planner"
    agent = AgentHome(
        name="planner",
        agent_id="atelier/planner/planner",
        role="planner",
        path=Path("/project/agents/planner"),
    )
    captured: dict[str, str] = {}

    def fake_render_template(template: str, context: dict[str, str]) -> str:
        captured.update({str(k): str(v) for k, v in context.items()})
        return "rendered"

    class DummyResult:
        stdout = ""
        returncode = 0

    with (
        patch(
            "atelier.commands.plan.resolve_current_project_with_repo_root",
            return_value=(
                Path("/project"),
                _fake_project_payload(),
                "/repo",
                Path("/repo"),
            ),
        ),
        patch(
            "atelier.commands.plan.config.resolve_project_data_dir",
            return_value=tmp_path,
        ),
        patch(
            "atelier.commands.plan.config.resolve_beads_root",
            return_value=Path("/beads"),
        ),
        patch(
            "atelier.commands.plan.agent_home.resolve_agent_home",
            return_value=agent,
        ),
        patch("atelier.commands.plan.beads.ensure_agent_bead"),
        patch(
            "atelier.commands.plan.beads.run_bd_command",
            return_value=DummyResult(),
        ),
        patch("atelier.commands.plan.beads.run_bd_json", return_value=[]),
        patch("atelier.commands.plan.beads.list_inbox_messages", return_value=[]),
        patch("atelier.commands.plan.beads.list_queue_messages", return_value=[]),
        patch("atelier.commands.plan.policy.sync_agent_home_policy"),
        patch("atelier.commands.plan.config.write_project_config"),
        patch("atelier.commands.plan.git.git_default_branch", return_value="main"),
        patch(
            "atelier.commands.plan.worktrees.ensure_git_worktree",
            return_value=worktree_path,
        ),
        patch(
            "atelier.commands.plan.prompting.render_template",
            side_effect=fake_render_template,
        ),
        patch(
            "atelier.commands.plan.external_registry.resolve_planner_provider",
            return_value=external_registry.PlannerProviderResolution(
                selected_provider="github",
                available_providers=("github",),
                github_repo="acme/widgets",
            ),
        ),
        patch(
            "atelier.commands.plan.external_registry.planner_provider_environment",
            return_value={},
        ),
        patch(
            "atelier.commands.plan.codex.run_codex_command",
            return_value=codex.CodexRunResult(returncode=0, session_id=None, resume_command=None),
        ),
        patch("atelier.commands.plan.say"),
    ):
        plan_cmd.run_planner(SimpleNamespace(epic_id=None))

    assert captured["repo_root"] == "/repo"
    assert captured["default_branch"] == "main"
    assert captured["planner_branch"] == "main-planner-planner"
    assert captured["external_providers"] == "github"


def test_plan_does_not_persist_selected_provider(tmp_path: Path) -> None:
    worktree_path = tmp_path / "worktrees" / "planner"
    agent = AgentHome(
        name="planner",
        agent_id="atelier/planner/planner",
        role="planner",
        path=Path("/project/agents/planner"),
    )

    class DummyResult:
        stdout = ""
        returncode = 0

    with (
        patch(
            "atelier.commands.plan.resolve_current_project_with_repo_root",
            return_value=(
                Path("/project"),
                _fake_project_payload(),
                "/repo",
                Path("/repo"),
            ),
        ),
        patch(
            "atelier.commands.plan.config.resolve_project_data_dir",
            return_value=tmp_path,
        ),
        patch(
            "atelier.commands.plan.config.resolve_beads_root",
            return_value=Path("/beads"),
        ),
        patch(
            "atelier.commands.plan.agent_home.resolve_agent_home",
            return_value=agent,
        ),
        patch("atelier.commands.plan.beads.ensure_agent_bead"),
        patch(
            "atelier.commands.plan.beads.run_bd_command",
            return_value=DummyResult(),
        ),
        patch("atelier.commands.plan.beads.run_bd_json", return_value=[]),
        patch("atelier.commands.plan.beads.list_inbox_messages", return_value=[]),
        patch("atelier.commands.plan.beads.list_queue_messages", return_value=[]),
        patch("atelier.commands.plan.policy.sync_agent_home_policy"),
        patch("atelier.commands.plan.git.git_default_branch", return_value="main"),
        patch(
            "atelier.commands.plan.worktrees.ensure_git_worktree",
            return_value=worktree_path,
        ),
        patch(
            "atelier.commands.plan.external_registry.resolve_planner_provider",
            return_value=external_registry.PlannerProviderResolution(
                selected_provider="github",
                available_providers=("github",),
                github_repo="acme/widgets",
            ),
        ),
        patch(
            "atelier.commands.plan.codex.run_codex_command",
            return_value=codex.CodexRunResult(returncode=0, session_id=None, resume_command=None),
        ),
        patch("atelier.commands.plan.say"),
        patch("atelier.commands.plan.config.write_project_config") as write_config,
    ):
        plan_cmd.run_planner(SimpleNamespace(epic_id=None))

    write_config.assert_not_called()


def test_planner_guardrails_install_commit_blocker(tmp_path: Path) -> None:
    worktree_path = tmp_path / "planner"
    worktree_path.mkdir(parents=True)
    (worktree_path / ".git").write_text("gitdir: /tmp/gitdir", encoding="utf-8")

    with (
        patch("atelier.commands.plan.exec.run_command") as run_command,
        patch(
            "atelier.commands.plan.exec.try_run_command",
            return_value=SimpleNamespace(returncode=1, stdout=""),
        ),
        patch(
            "atelier.commands.plan.git.git_status_porcelain",
            return_value=[" M example.txt"],
        ),
        patch("atelier.commands.plan.say") as say,
    ):
        plan_cmd._ensure_planner_read_only_guardrails(
            worktree_path, tmp_path / "hooks", git_path="git"
        )

    hooks_dir = tmp_path / "hooks"
    hook_path = hooks_dir / "pre-commit"
    assert hook_path.exists()
    assert run_command.call_count == 2
    assert any(
        call.args and "--worktree" in call.args[0] and "core.hooksPath" in call.args[0]
        for call in run_command.call_args_list
    )
    assert say.call_args_list


def test_planner_migration_prompts_when_worktree_dirty(tmp_path: Path) -> None:
    planner_key = "planner-codex"
    mapping_path = worktrees.mapping_path(tmp_path, planner_key)
    mapping_path.parent.mkdir(parents=True, exist_ok=True)
    worktrees.write_mapping(
        mapping_path,
        worktrees.WorktreeMapping(
            epic_id=planner_key,
            worktree_path="worktrees/planner-codex",
            root_branch="main",
            changesets={},
            changeset_worktrees={},
        ),
    )
    planner_worktree = tmp_path / "worktrees" / "planner-codex"
    planner_worktree.mkdir(parents=True)
    (planner_worktree / ".git").write_text("gitdir: /tmp/gitdir", encoding="utf-8")

    with (
        patch(
            "atelier.commands.plan.git.git_status_porcelain",
            return_value=[" M src/example.py", "?? notes.txt"],
        ),
        patch("atelier.commands.plan.confirm", return_value=False) as confirm,
        patch("atelier.commands.plan.say") as say,
    ):
        with pytest.raises(SystemExit):
            plan_cmd._maybe_migrate_planner_mapping(
                project_data_dir=tmp_path,
                planner_key=planner_key,
                planner_branch="main-planner-codex",
                default_branch="main",
                git_path="git",
            )

    confirm.assert_called_once()
    assert any(
        "Planner worktree has local changes" in str(call.args[0]) for call in say.call_args_list
    )
    assert any("Local changes:" in str(call.args[0]) for call in say.call_args_list)

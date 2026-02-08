from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import atelier.codex as codex
import atelier.commands.plan as plan_cmd
import atelier.external_registry as external_registry
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

    def fake_run_bd_command(
        args, *, beads_root: Path, cwd: Path, allow_failure: bool = False
    ):
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
        patch("atelier.commands.plan.beads.ensure_agent_bead"),
        patch(
            "atelier.commands.plan.beads.run_bd_command",
            side_effect=fake_run_bd_command,
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
            "atelier.commands.plan.codex.run_codex_command",
            side_effect=fake_run_codex_command,
        ),
        patch("atelier.commands.plan.prompt", return_value=""),
        patch("atelier.commands.plan.say"),
    ):
        plan_cmd.run_planner(SimpleNamespace(epic_id="atelier-epic"))

    assert calls
    assert calls[0][0] == "prime"
    assert captured_env.get("ATELIER_PLAN_EPIC") == "atelier-epic"


def test_plan_promotes_draft_epic_with_approval(tmp_path: Path) -> None:
    worktree_path = tmp_path / "worktrees" / "planner"
    agent = AgentHome(
        name="planner",
        agent_id="atelier/planner/planner",
        role="planner",
        path=Path("/project/agents/planner"),
    )
    calls: list[list[str]] = []
    prompt_answers = iter(["y", "atelier-draft", "y"])

    def fake_run_bd_command(
        args, *, beads_root: Path, cwd: Path, allow_failure: bool = False
    ):
        calls.append(list(args))

        class Result:
            stdout = ""
            returncode = 0

        return Result()

    def fake_run_bd_json(args, *, beads_root: Path, cwd: Path):
        if "at:draft" in args:
            return [
                {
                    "id": "atelier-draft",
                    "title": "Draft",
                    "status": "open",
                    "labels": ["at:epic", "at:draft"],
                }
            ]
        return []

    def fake_prompt(_: str) -> str:
        return next(prompt_answers)

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
            side_effect=fake_run_bd_command,
        ),
        patch("atelier.commands.plan.beads.run_bd_json", side_effect=fake_run_bd_json),
        patch("atelier.commands.plan.beads.list_inbox_messages", return_value=[]),
        patch("atelier.commands.plan.beads.list_queue_messages", return_value=[]),
        patch("atelier.commands.plan.policy.sync_agent_home_policy"),
        patch("atelier.commands.plan.git.git_default_branch", return_value="main"),
        patch(
            "atelier.commands.plan.worktrees.ensure_git_worktree",
            return_value=worktree_path,
        ),
        patch(
            "atelier.commands.plan.codex.run_codex_command",
            return_value=codex.CodexRunResult(
                returncode=0, session_id=None, resume_command=None
            ),
        ),
        patch("atelier.commands.plan.prompt", side_effect=fake_prompt),
        patch("atelier.commands.plan.say"),
    ):
        plan_cmd.run_planner(SimpleNamespace(epic_id=None))

    assert any(
        call[:2] == ["update", "atelier-draft"] and "at:draft" in call for call in calls
    )


def test_plan_template_variables_include_provider_info(tmp_path: Path) -> None:
    worktree_path = tmp_path / "worktrees" / "planner"
    agent = AgentHome(
        name="planner",
        agent_id="atelier/planner/planner",
        role="planner",
        path=Path("/project/agents/planner"),
    )
    captured: dict[str, str] = {}

    class FakeProvider:
        slug = "github"

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
            "atelier.commands.plan.external_registry.resolve_external_providers",
            return_value=[
                external_registry.ExternalProviderContext(provider=FakeProvider())
            ],
        ),
        patch(
            "atelier.commands.plan.external_registry.planner_provider_environment",
            return_value={},
        ),
        patch(
            "atelier.commands.plan.codex.run_codex_command",
            return_value=codex.CodexRunResult(
                returncode=0, session_id=None, resume_command=None
            ),
        ),
        patch("atelier.commands.plan.prompt", return_value=""),
        patch("atelier.commands.plan.say"),
    ):
        plan_cmd.run_planner(SimpleNamespace(epic_id=None))

    assert captured["repo_root"] == "/repo"
    assert captured["default_branch"] == "main"
    assert captured["external_providers"] == "github"


def test_planner_guardrails_install_commit_blocker(tmp_path: Path) -> None:
    worktree_path = tmp_path / "planner"
    worktree_path.mkdir(parents=True)
    (worktree_path / ".git").write_text("gitdir: /tmp/gitdir", encoding="utf-8")

    with (
        patch("atelier.commands.plan.exec.run_command") as run_command,
        patch(
            "atelier.commands.plan.git.git_status_porcelain",
            return_value=[" M example.txt"],
        ),
        patch("atelier.commands.plan.say") as say,
    ):
        plan_cmd._ensure_planner_read_only_guardrails(worktree_path, git_path="git")

    hooks_dir = plan_cmd._planner_hooks_dir(worktree_path)
    hook_path = hooks_dir / "pre-commit"
    assert hook_path.exists()
    run_command.assert_called_once()
    assert "core.hooksPath" in run_command.call_args.args[0]
    assert say.call_args_list

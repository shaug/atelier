from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import atelier.codex as codex
import atelier.commands.plan as plan_cmd
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
        patch("atelier.commands.plan.say"),
    ):
        plan_cmd.run_planner(SimpleNamespace(epic_id="atelier-epic"))

    assert calls
    assert calls[0][0] == "prime"
    assert captured_env.get("ATELIER_PLAN_EPIC") == "atelier-epic"

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import atelier.commands.plan as plan_cmd
from atelier.agent_home import AgentHome
from atelier.config import ProjectConfig


def _fake_project_payload() -> ProjectConfig:
    return ProjectConfig()


def test_plan_create_epic_uses_form() -> None:
    agent = AgentHome(
        name="planner",
        agent_id="atelier/planner/planner",
        role="planner",
        path=Path("/project/agents/planner"),
    )
    calls: list[list[str]] = []

    def fake_run_bd_command(
        args, *, beads_root: Path, cwd: Path, allow_failure: bool = False
    ):
        calls.append(args)

        class Result:
            stdout = ""
            returncode = 0

        return Result()

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
            return_value=Path("/project"),
        ),
        patch(
            "atelier.commands.plan.config.resolve_beads_root",
            return_value=Path("/beads"),
        ),
        patch(
            "atelier.commands.plan.agent_home.resolve_agent_home",
            return_value=agent,
        ),
        patch(
            "atelier.commands.plan.beads.ensure_agent_bead",
        ),
        patch(
            "atelier.commands.plan.beads.run_bd_command",
            side_effect=fake_run_bd_command,
        ),
        patch("atelier.commands.plan.say"),
    ):
        plan_cmd.run_planner(SimpleNamespace(create_epic=True, epic_id=None))

    assert calls
    assert calls[0][0] == "prime"
    assert calls[1][0] == "list"
    assert calls[2][0] == "create-form"

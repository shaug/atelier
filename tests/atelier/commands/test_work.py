from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import atelier.commands.work as work_cmd
import atelier.config as config
import atelier.worktrees as worktrees


def _fake_project_payload() -> config.ProjectConfig:
    return config.ProjectConfig()


def test_work_prompt_selects_epic_and_changeset() -> None:
    epics = [
        {
            "id": "atelier-epic",
            "title": "Epic",
            "status": "open",
            "labels": ["at:epic"],
        }
    ]
    changesets = [{"id": "atelier-epic.1", "title": "First changeset"}]
    calls: list[list[str]] = []

    def fake_run_bd_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict]:
        calls.append(args)
        if args[0] == "list":
            return epics
        return changesets

    mapping = worktrees.WorktreeMapping(
        epic_id="atelier-epic",
        worktree_path="worktrees/atelier-epic",
        changesets={"atelier-epic.1": "atelier-epic-1"},
    )

    with (
        patch(
            "atelier.commands.work.resolve_current_project_with_repo_root",
            return_value=(
                Path("/project"),
                _fake_project_payload(),
                "/repo",
                Path("/repo"),
            ),
        ),
        patch(
            "atelier.commands.work.config.resolve_beads_root",
            return_value=Path("/beads"),
        ),
        patch("atelier.commands.work.beads.run_bd_json", side_effect=fake_run_bd_json),
        patch(
            "atelier.commands.work.worktrees.ensure_changeset_branch",
            return_value=("atelier-epic-1", mapping),
        ),
        patch("atelier.commands.work.worktrees.ensure_git_worktree"),
        patch(
            "atelier.commands.work.beads.ensure_agent_bead",
            return_value={"id": "atelier-agent"},
        ),
        patch("atelier.commands.work.beads.claim_epic"),
        patch("atelier.commands.work.beads.set_agent_hook"),
        patch("atelier.commands.work.agent_home.resolve_agent_home"),
        patch("atelier.commands.work.prompt", return_value="atelier-epic"),
        patch("atelier.commands.work.say"),
    ):
        work_cmd.start_worker(SimpleNamespace(epic_id=None, mode="prompt"))

    assert calls[0][0] == "list"
    assert calls[1][0] == "ready"


def test_work_auto_picks_ready_or_in_progress() -> None:
    ready_epics: list[dict[str, object]] = []
    in_progress_epics = [
        {
            "id": "atelier-epic",
            "title": "Epic",
            "status": "in_progress",
            "labels": ["at:epic"],
        }
    ]
    changesets = [{"id": "atelier-epic.1", "title": "First changeset"}]
    calls: list[list[str]] = []

    def fake_run_bd_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict]:
        calls.append(args)
        if args[0] == "list" and "--ready" in args:
            return ready_epics
        if args[0] == "list" and "--status" in args:
            return in_progress_epics
        return changesets

    mapping = worktrees.WorktreeMapping(
        epic_id="atelier-epic",
        worktree_path="worktrees/atelier-epic",
        changesets={"atelier-epic.1": "atelier-epic-1"},
    )

    with (
        patch(
            "atelier.commands.work.resolve_current_project_with_repo_root",
            return_value=(
                Path("/project"),
                _fake_project_payload(),
                "/repo",
                Path("/repo"),
            ),
        ),
        patch(
            "atelier.commands.work.config.resolve_beads_root",
            return_value=Path("/beads"),
        ),
        patch("atelier.commands.work.beads.run_bd_json", side_effect=fake_run_bd_json),
        patch(
            "atelier.commands.work.worktrees.ensure_changeset_branch",
            return_value=("atelier-epic-1", mapping),
        ),
        patch("atelier.commands.work.worktrees.ensure_git_worktree"),
        patch(
            "atelier.commands.work.beads.ensure_agent_bead",
            return_value={"id": "atelier-agent"},
        ),
        patch("atelier.commands.work.beads.claim_epic"),
        patch("atelier.commands.work.beads.set_agent_hook"),
        patch("atelier.commands.work.agent_home.resolve_agent_home"),
        patch("atelier.commands.work.say"),
    ):
        work_cmd.start_worker(SimpleNamespace(epic_id=None, mode="auto"))

    assert calls[0][0] == "list"
    assert "--ready" in calls[0]
    assert calls[1][0] == "list"
    assert "--status" in calls[1]
    assert calls[2][0] == "ready"


def test_work_uses_explicit_epic_id() -> None:
    changesets = [{"id": "atelier-epic.1", "title": "First changeset"}]
    calls: list[list[str]] = []

    def fake_run_bd_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict]:
        calls.append(args)
        return changesets

    mapping = worktrees.WorktreeMapping(
        epic_id="atelier-epic",
        worktree_path="worktrees/atelier-epic",
        changesets={"atelier-epic.1": "atelier-epic-1"},
    )

    with (
        patch(
            "atelier.commands.work.resolve_current_project_with_repo_root",
            return_value=(
                Path("/project"),
                _fake_project_payload(),
                "/repo",
                Path("/repo"),
            ),
        ),
        patch(
            "atelier.commands.work.config.resolve_beads_root",
            return_value=Path("/beads"),
        ),
        patch("atelier.commands.work.beads.run_bd_json", side_effect=fake_run_bd_json),
        patch(
            "atelier.commands.work.worktrees.ensure_changeset_branch",
            return_value=("atelier-epic-1", mapping),
        ),
        patch("atelier.commands.work.worktrees.ensure_git_worktree"),
        patch(
            "atelier.commands.work.beads.ensure_agent_bead",
            return_value={"id": "atelier-agent"},
        ),
        patch("atelier.commands.work.beads.claim_epic"),
        patch("atelier.commands.work.beads.set_agent_hook"),
        patch("atelier.commands.work.agent_home.resolve_agent_home"),
        patch("atelier.commands.work.say"),
    ):
        work_cmd.start_worker(SimpleNamespace(epic_id="atelier-epic", mode="prompt"))

    assert calls[0][0] == "ready"

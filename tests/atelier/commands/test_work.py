from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import atelier.codex as codex
import atelier.commands.work as work_cmd
import atelier.config as config
import atelier.worktrees as worktrees
from atelier.agent_home import AgentHome


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
        root_branch="feat/root",
        changesets={"atelier-epic.1": "feat/root-atelier-epic.1"},
    )
    agent = AgentHome(
        name="worker",
        agent_id="atelier/worker/agent",
        role="worker",
        path=Path("/project/agents/worker"),
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
        patch("atelier.commands.work.beads.run_bd_command"),
        patch("atelier.commands.work.beads.list_inbox_messages", return_value=[]),
        patch("atelier.commands.work.beads.list_queue_messages", return_value=[]),
        patch("atelier.commands.work.beads.get_agent_hook", return_value=None),
        patch(
            "atelier.commands.work.worktrees.ensure_changeset_branch",
            return_value=("feat/root-atelier-epic.1", mapping),
        ),
        patch("atelier.commands.work.worktrees.ensure_changeset_checkout"),
        patch("atelier.commands.work.worktrees.ensure_git_worktree"),
        patch(
            "atelier.commands.work.codex.run_codex_command",
            return_value=codex.CodexRunResult(
                returncode=0, session_id=None, resume_command=None
            ),
        ),
        patch(
            "atelier.commands.work.beads.ensure_agent_bead",
            return_value={"id": "atelier-agent"},
        ),
        patch("atelier.commands.work.policy.sync_agent_home_policy"),
        patch(
            "atelier.commands.work.beads.claim_epic",
            return_value={
                "id": "atelier-epic",
                "title": "Epic",
                "description": "workspace.root_branch: feat/root\n",
            },
        ),
        patch("atelier.commands.work.beads.update_worktree_path"),
        patch("atelier.commands.work.beads.set_agent_hook"),
        patch(
            "atelier.commands.work.agent_home.resolve_agent_home", return_value=agent
        ),
        patch("atelier.commands.work.prompt", return_value="atelier-epic"),
        patch("atelier.commands.work.say"),
    ):
        work_cmd.start_worker(SimpleNamespace(epic_id=None, mode="prompt"))

    assert calls[0][0] == "list"
    assert calls[1][0] == "ready"


def test_work_prompt_allows_resume_epic() -> None:
    epics = [
        {
            "id": "atelier-epic",
            "title": "Epic",
            "status": "open",
            "labels": ["at:epic"],
        },
        {
            "id": "atelier-epic-hooked",
            "title": "Epic hooked",
            "status": "hooked",
            "labels": ["at:epic", "at:hooked"],
            "assignee": "atelier/worker/agent",
        },
    ]
    changesets = [{"id": "atelier-epic-hooked.1", "title": "First changeset"}]
    calls: list[list[str]] = []
    claimed: list[str] = []

    def fake_run_bd_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict]:
        calls.append(args)
        if args[0] == "list":
            return epics
        return changesets

    def fake_claim_epic(epic_id: str, *args: object, **kwargs: object) -> dict:
        claimed.append(epic_id)
        return {
            "id": epic_id,
            "title": "Epic",
            "description": "workspace.root_branch: feat/root\n",
        }

    mapping = worktrees.WorktreeMapping(
        epic_id="atelier-epic-hooked",
        worktree_path="worktrees/atelier-epic-hooked",
        root_branch="feat/root",
        changesets={"atelier-epic-hooked.1": "feat/root-atelier-epic-hooked.1"},
    )
    agent = AgentHome(
        name="worker",
        agent_id="atelier/worker/agent",
        role="worker",
        path=Path("/project/agents/worker"),
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
        patch("atelier.commands.work.beads.run_bd_command"),
        patch("atelier.commands.work.beads.list_inbox_messages", return_value=[]),
        patch("atelier.commands.work.beads.list_queue_messages", return_value=[]),
        patch("atelier.commands.work.beads.get_agent_hook", return_value=None),
        patch(
            "atelier.commands.work.worktrees.ensure_changeset_branch",
            return_value=("feat/root-atelier-epic-hooked.1", mapping),
        ),
        patch("atelier.commands.work.worktrees.ensure_changeset_checkout"),
        patch("atelier.commands.work.worktrees.ensure_git_worktree"),
        patch(
            "atelier.commands.work.codex.run_codex_command",
            return_value=codex.CodexRunResult(
                returncode=0, session_id=None, resume_command=None
            ),
        ),
        patch(
            "atelier.commands.work.beads.ensure_agent_bead",
            return_value={"id": "atelier-agent"},
        ),
        patch("atelier.commands.work.policy.sync_agent_home_policy"),
        patch("atelier.commands.work.beads.claim_epic", side_effect=fake_claim_epic),
        patch("atelier.commands.work.beads.update_worktree_path"),
        patch("atelier.commands.work.beads.set_agent_hook"),
        patch(
            "atelier.commands.work.agent_home.resolve_agent_home", return_value=agent
        ),
        patch("atelier.commands.work.prompt", return_value="atelier-epic-hooked"),
        patch("atelier.commands.work.say"),
    ):
        work_cmd.start_worker(SimpleNamespace(epic_id=None, mode="prompt"))

    assert calls[0][0] == "list"
    assert calls[1][0] == "ready"
    assert claimed == ["atelier-epic-hooked"]


def test_work_auto_picks_ready_epic() -> None:
    open_epics = [
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
            return open_epics
        return changesets

    mapping = worktrees.WorktreeMapping(
        epic_id="atelier-epic",
        worktree_path="worktrees/atelier-epic",
        root_branch="feat/root",
        changesets={"atelier-epic.1": "feat/root-atelier-epic.1"},
    )
    agent = AgentHome(
        name="worker",
        agent_id="atelier/worker/agent",
        role="worker",
        path=Path("/project/agents/worker"),
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
        patch("atelier.commands.work.beads.run_bd_command"),
        patch("atelier.commands.work.beads.list_inbox_messages", return_value=[]),
        patch("atelier.commands.work.beads.list_queue_messages", return_value=[]),
        patch("atelier.commands.work.beads.get_agent_hook", return_value=None),
        patch(
            "atelier.commands.work.worktrees.ensure_changeset_branch",
            return_value=("feat/root-atelier-epic.1", mapping),
        ),
        patch("atelier.commands.work.worktrees.ensure_changeset_checkout"),
        patch("atelier.commands.work.worktrees.ensure_git_worktree"),
        patch(
            "atelier.commands.work.codex.run_codex_command",
            return_value=codex.CodexRunResult(
                returncode=0, session_id=None, resume_command=None
            ),
        ),
        patch(
            "atelier.commands.work.beads.ensure_agent_bead",
            return_value={"id": "atelier-agent"},
        ),
        patch("atelier.commands.work.policy.sync_agent_home_policy"),
        patch(
            "atelier.commands.work.beads.claim_epic",
            return_value={
                "id": "atelier-epic",
                "title": "Epic",
                "description": "workspace.root_branch: feat/root\n",
            },
        ),
        patch("atelier.commands.work.beads.update_worktree_path"),
        patch("atelier.commands.work.beads.set_agent_hook"),
        patch(
            "atelier.commands.work.agent_home.resolve_agent_home", return_value=agent
        ),
        patch("atelier.commands.work.say"),
    ):
        work_cmd.start_worker(SimpleNamespace(epic_id=None, mode="auto"))

    assert calls[0][0] == "list"
    assert calls[1][0] == "ready"


def test_work_auto_falls_back_to_oldest_unfinished() -> None:
    open_epics = [
        {
            "id": "atelier-epic-old",
            "title": "Epic old",
            "status": "hooked",
            "labels": ["at:epic", "at:hooked"],
            "assignee": "atelier/worker/agent",
            "created_at": "2025-01-01T00:00:00+00:00",
        },
        {
            "id": "atelier-epic-new",
            "title": "Epic new",
            "status": "hooked",
            "labels": ["at:epic", "at:hooked"],
            "assignee": "atelier/worker/agent",
            "created_at": "2025-01-02T00:00:00+00:00",
        },
    ]
    changesets = [{"id": "atelier-epic-old.1", "title": "First changeset"}]
    calls: list[list[str]] = []
    claimed: list[str] = []

    def fake_run_bd_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict]:
        calls.append(args)
        if args[0] == "list":
            return open_epics
        return changesets

    def fake_claim_epic(epic_id: str, *args: object, **kwargs: object) -> dict:
        claimed.append(epic_id)
        return {
            "id": epic_id,
            "title": "Epic",
            "description": "workspace.root_branch: feat/root\n",
        }

    mapping = worktrees.WorktreeMapping(
        epic_id="atelier-epic-old",
        worktree_path="worktrees/atelier-epic-old",
        root_branch="feat/root",
        changesets={"atelier-epic-old.1": "feat/root-atelier-epic-old.1"},
    )
    agent = AgentHome(
        name="worker",
        agent_id="atelier/worker/agent",
        role="worker",
        path=Path("/project/agents/worker"),
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
        patch("atelier.commands.work.beads.run_bd_command"),
        patch("atelier.commands.work.beads.list_inbox_messages", return_value=[]),
        patch("atelier.commands.work.beads.list_queue_messages", return_value=[]),
        patch("atelier.commands.work.beads.get_agent_hook", return_value=None),
        patch(
            "atelier.commands.work.worktrees.ensure_changeset_branch",
            return_value=("feat/root-atelier-epic-old.1", mapping),
        ),
        patch("atelier.commands.work.worktrees.ensure_changeset_checkout"),
        patch("atelier.commands.work.worktrees.ensure_git_worktree"),
        patch(
            "atelier.commands.work.codex.run_codex_command",
            return_value=codex.CodexRunResult(
                returncode=0, session_id=None, resume_command=None
            ),
        ),
        patch(
            "atelier.commands.work.beads.ensure_agent_bead",
            return_value={"id": "atelier-agent"},
        ),
        patch("atelier.commands.work.policy.sync_agent_home_policy"),
        patch("atelier.commands.work.beads.claim_epic", side_effect=fake_claim_epic),
        patch("atelier.commands.work.beads.update_worktree_path"),
        patch("atelier.commands.work.beads.set_agent_hook"),
        patch(
            "atelier.commands.work.agent_home.resolve_agent_home", return_value=agent
        ),
        patch("atelier.commands.work.say"),
    ):
        work_cmd.start_worker(SimpleNamespace(epic_id=None, mode="auto"))

    assert calls[0][0] == "list"
    assert calls[1][0] == "ready"
    assert claimed == ["atelier-epic-old"]


def test_work_resumes_hooked_epic() -> None:
    epic = {
        "id": "atelier-epic",
        "title": "Epic",
        "status": "open",
        "assignee": "atelier/worker/agent",
        "labels": ["at:epic", "at:hooked"],
    }
    changesets = [{"id": "atelier-epic.1", "title": "First changeset"}]
    calls: list[list[str]] = []
    claimed: list[str] = []

    def fake_run_bd_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict]:
        calls.append(args)
        if args[0] == "show":
            return [epic]
        return changesets

    def fake_claim_epic(epic_id: str, *args: object, **kwargs: object) -> dict:
        claimed.append(epic_id)
        return {
            "id": epic_id,
            "title": "Epic",
            "description": "workspace.root_branch: feat/root\n",
        }

    mapping = worktrees.WorktreeMapping(
        epic_id="atelier-epic",
        worktree_path="worktrees/atelier-epic",
        root_branch="feat/root",
        changesets={"atelier-epic.1": "feat/root-atelier-epic.1"},
    )
    agent = AgentHome(
        name="worker",
        agent_id="atelier/worker/agent",
        role="worker",
        path=Path("/project/agents/worker"),
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
        patch("atelier.commands.work.beads.run_bd_command"),
        patch(
            "atelier.commands.work.beads.get_agent_hook", return_value="atelier-epic"
        ),
        patch(
            "atelier.commands.work.worktrees.ensure_changeset_branch",
            return_value=("feat/root-atelier-epic.1", mapping),
        ),
        patch("atelier.commands.work.worktrees.ensure_changeset_checkout"),
        patch("atelier.commands.work.worktrees.ensure_git_worktree"),
        patch(
            "atelier.commands.work.codex.run_codex_command",
            return_value=codex.CodexRunResult(
                returncode=0, session_id=None, resume_command=None
            ),
        ),
        patch(
            "atelier.commands.work.beads.ensure_agent_bead",
            return_value={"id": "atelier-agent"},
        ),
        patch("atelier.commands.work.policy.sync_agent_home_policy"),
        patch("atelier.commands.work.beads.claim_epic", side_effect=fake_claim_epic),
        patch("atelier.commands.work.beads.update_worktree_path"),
        patch("atelier.commands.work.beads.set_agent_hook"),
        patch(
            "atelier.commands.work.agent_home.resolve_agent_home", return_value=agent
        ),
        patch("atelier.commands.work.say"),
    ):
        work_cmd.start_worker(SimpleNamespace(epic_id=None, mode="auto"))

    assert calls[0][0] == "show"
    assert calls[1][0] == "ready"
    assert claimed == ["atelier-epic"]


def test_work_stops_for_unread_inbox() -> None:
    agent = AgentHome(
        name="worker",
        agent_id="atelier/worker/agent",
        role="worker",
        path=Path("/project/agents/worker"),
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
        patch("atelier.commands.work.beads.run_bd_json", return_value=[]),
        patch("atelier.commands.work.beads.run_bd_command"),
        patch("atelier.commands.work.beads.get_agent_hook", return_value=None),
        patch(
            "atelier.commands.work.beads.list_inbox_messages",
            return_value=[{"id": "msg-1"}],
        ),
        patch("atelier.commands.work.beads.list_queue_messages", return_value=[]),
        patch(
            "atelier.commands.work.beads.ensure_agent_bead",
            return_value={"id": "atelier-agent"},
        ),
        patch("atelier.commands.work.policy.sync_agent_home_policy"),
        patch("atelier.commands.work.beads.claim_epic") as claim_epic,
        patch(
            "atelier.commands.work.agent_home.resolve_agent_home", return_value=agent
        ),
        patch("atelier.commands.work.say"),
    ):
        work_cmd.start_worker(SimpleNamespace(epic_id=None, mode="auto"))

    claim_epic.assert_not_called()


def test_work_resumes_assigned_epic_before_inbox() -> None:
    epics = [
        {
            "id": "atelier-epic-hooked",
            "title": "Epic hooked",
            "status": "hooked",
            "labels": ["at:epic", "at:hooked"],
            "assignee": "atelier/worker/agent",
        }
    ]
    changesets = [{"id": "atelier-epic-hooked.1", "title": "First changeset"}]
    claimed: list[str] = []

    def fake_run_bd_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict]:
        if args[0] == "list":
            return epics
        return changesets

    def fake_claim_epic(epic_id: str, *args: object, **kwargs: object) -> dict:
        claimed.append(epic_id)
        return {
            "id": epic_id,
            "title": "Epic",
            "description": "workspace.root_branch: feat/root\n",
        }

    mapping = worktrees.WorktreeMapping(
        epic_id="atelier-epic-hooked",
        worktree_path="worktrees/atelier-epic-hooked",
        root_branch="feat/root",
        changesets={"atelier-epic-hooked.1": "feat/root-atelier-epic-hooked.1"},
    )
    agent = AgentHome(
        name="worker",
        agent_id="atelier/worker/agent",
        role="worker",
        path=Path("/project/agents/worker"),
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
        patch("atelier.commands.work.beads.run_bd_command"),
        patch("atelier.commands.work.beads.get_agent_hook", return_value=None),
        patch(
            "atelier.commands.work.beads.list_inbox_messages",
            return_value=[{"id": "msg-1"}],
        ),
        patch("atelier.commands.work.beads.list_queue_messages", return_value=[]),
        patch(
            "atelier.commands.work.worktrees.ensure_changeset_branch",
            return_value=("feat/root-atelier-epic-hooked.1", mapping),
        ),
        patch("atelier.commands.work.worktrees.ensure_changeset_checkout"),
        patch("atelier.commands.work.worktrees.ensure_git_worktree"),
        patch(
            "atelier.commands.work.codex.run_codex_command",
            return_value=codex.CodexRunResult(
                returncode=0, session_id=None, resume_command=None
            ),
        ),
        patch(
            "atelier.commands.work.beads.ensure_agent_bead",
            return_value={"id": "atelier-agent"},
        ),
        patch("atelier.commands.work.policy.sync_agent_home_policy"),
        patch("atelier.commands.work.beads.claim_epic", side_effect=fake_claim_epic),
        patch("atelier.commands.work.beads.update_worktree_path"),
        patch("atelier.commands.work.beads.set_agent_hook"),
        patch(
            "atelier.commands.work.agent_home.resolve_agent_home", return_value=agent
        ),
        patch("atelier.commands.work.say"),
    ):
        work_cmd.start_worker(SimpleNamespace(epic_id=None, mode="auto"))

    assert claimed == ["atelier-epic-hooked"]


def test_work_prompts_for_queue_before_claiming() -> None:
    queued = [
        {"id": "msg-1", "title": "Queue item", "queue": "triage"},
    ]
    agent = AgentHome(
        name="worker",
        agent_id="atelier/worker/agent",
        role="worker",
        path=Path("/project/agents/worker"),
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
        patch("atelier.commands.work.beads.run_bd_json", return_value=[]),
        patch("atelier.commands.work.beads.run_bd_command"),
        patch(
            "atelier.commands.work.beads.ensure_agent_bead",
            return_value={"id": "atelier-agent"},
        ),
        patch("atelier.commands.work.policy.sync_agent_home_policy"),
        patch("atelier.commands.work.beads.get_agent_hook", return_value=None),
        patch("atelier.commands.work.beads.list_inbox_messages", return_value=[]),
        patch("atelier.commands.work.beads.list_queue_messages", return_value=queued),
        patch("atelier.commands.work.beads.claim_queue_message") as claim_queue,
        patch("atelier.commands.work.beads.claim_epic") as claim_epic,
        patch(
            "atelier.commands.work.agent_home.resolve_agent_home", return_value=agent
        ),
        patch("atelier.commands.work.prompt", return_value="msg-1"),
        patch("atelier.commands.work.say"),
    ):
        work_cmd.start_worker(SimpleNamespace(epic_id=None, mode="auto"))

    claim_queue.assert_called_once_with(
        "msg-1",
        "atelier/worker/agent",
        beads_root=Path("/beads"),
        cwd=Path("/repo"),
    )
    claim_epic.assert_not_called()


def test_work_queue_option_stops_when_empty() -> None:
    agent = AgentHome(
        name="worker",
        agent_id="atelier/worker/agent",
        role="worker",
        path=Path("/project/agents/worker"),
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
        patch("atelier.commands.work.beads.run_bd_command"),
        patch(
            "atelier.commands.work.beads.ensure_agent_bead",
            return_value={"id": "atelier-agent"},
        ),
        patch("atelier.commands.work.policy.sync_agent_home_policy"),
        patch("atelier.commands.work.beads.list_queue_messages", return_value=[]),
        patch("atelier.commands.work.beads.claim_epic") as claim_epic,
        patch(
            "atelier.commands.work.agent_home.resolve_agent_home", return_value=agent
        ),
        patch("atelier.commands.work.say"),
    ):
        work_cmd.start_worker(SimpleNamespace(epic_id=None, mode="auto", queue=True))

    claim_epic.assert_not_called()


def test_work_uses_explicit_epic_id() -> None:
    changesets = [{"id": "atelier-epic.1", "title": "First changeset"}]
    calls: list[list[str]] = []

    def fake_run_bd_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict]:
        calls.append(args)
        return changesets

    mapping = worktrees.WorktreeMapping(
        epic_id="atelier-epic",
        worktree_path="worktrees/atelier-epic",
        root_branch="feat/root",
        changesets={"atelier-epic.1": "feat/root-atelier-epic.1"},
    )
    agent = AgentHome(
        name="worker",
        agent_id="atelier/worker/agent",
        role="worker",
        path=Path("/project/agents/worker"),
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
        patch("atelier.commands.work.beads.run_bd_command"),
        patch(
            "atelier.commands.work.worktrees.ensure_changeset_branch",
            return_value=("feat/root-atelier-epic.1", mapping),
        ),
        patch("atelier.commands.work.worktrees.ensure_changeset_checkout"),
        patch("atelier.commands.work.worktrees.ensure_git_worktree"),
        patch(
            "atelier.commands.work.codex.run_codex_command",
            return_value=codex.CodexRunResult(
                returncode=0, session_id=None, resume_command=None
            ),
        ),
        patch(
            "atelier.commands.work.beads.ensure_agent_bead",
            return_value={"id": "atelier-agent"},
        ),
        patch("atelier.commands.work.policy.sync_agent_home_policy"),
        patch(
            "atelier.commands.work.beads.claim_epic",
            return_value={
                "id": "atelier-epic",
                "title": "Epic",
                "description": "workspace.root_branch: feat/root\n",
            },
        ),
        patch("atelier.commands.work.beads.update_worktree_path"),
        patch("atelier.commands.work.beads.set_agent_hook"),
        patch(
            "atelier.commands.work.agent_home.resolve_agent_home", return_value=agent
        ),
        patch("atelier.commands.work.say"),
    ):
        work_cmd.start_worker(SimpleNamespace(epic_id="atelier-epic", mode="prompt"))

    assert calls[0][0] == "ready"

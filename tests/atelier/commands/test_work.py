from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import atelier.codex as codex
import atelier.commands.work as work_cmd
import atelier.config as config
import atelier.messages as messages
import atelier.worktrees as worktrees
from atelier.agent_home import AgentHome


def _fake_project_payload() -> config.ProjectConfig:
    return config.ProjectConfig()


def _post_session_payload(args: list[str], *, changeset_id: str) -> list[dict] | None:
    if args[:2] == ["list", "--label"] and "at:message" in args:
        return []
    if args[:2] == ["show", changeset_id]:
        description = f"changeset.work_branch: feat/root-{changeset_id}\n"
        return [
            {
                "id": changeset_id,
                "labels": ["at:changeset", "cs:ready"],
                "description": description,
            }
        ]
    return None


@pytest.fixture(autouse=True)
def _project_data_dir(tmp_path: Path) -> object:
    with patch(
        "atelier.commands.work.config.resolve_project_data_dir", return_value=tmp_path
    ):
        yield


@pytest.fixture(autouse=True)
def _branch_metadata_updates() -> object:
    with (
        patch(
            "atelier.commands.work.beads.update_workspace_parent_branch"
        ) as update_epic,
        patch(
            "atelier.commands.work.beads.update_changeset_branch_metadata"
        ) as update_changeset,
        patch("atelier.commands.work.git.git_rev_parse", return_value=None),
    ):
        yield update_epic, update_changeset


@pytest.fixture(autouse=True)
def _changeset_worktree(tmp_path: Path) -> object:
    worktree_path = tmp_path / "worktrees" / "changeset"
    with patch(
        "atelier.commands.work.worktrees.ensure_changeset_worktree",
        return_value=worktree_path,
    ):
        yield


@pytest.fixture(autouse=True)
def _publish_signals() -> object:
    with (
        patch("atelier.commands.work.git.git_ref_exists", return_value=True),
        patch("atelier.commands.work.prs.read_github_pr_status", return_value=None),
    ):
        yield


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
        post_session = _post_session_payload(args, changeset_id="atelier-epic.1")
        if post_session is not None:
            return post_session
        calls.append(args)
        if args[0] == "list":
            return epics
        return changesets

    mapping = worktrees.WorktreeMapping(
        epic_id="atelier-epic",
        worktree_path="worktrees/atelier-epic",
        root_branch="feat/root",
        changesets={"atelier-epic.1": "feat/root-atelier-epic.1"},
        changeset_worktrees={},
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
        patch(
            "atelier.commands.work.select",
            return_value="available | atelier-epic [open] unset Epic",
        ) as select_epic,
        patch("atelier.commands.work.say"),
    ):
        work_cmd.start_worker(
            SimpleNamespace(epic_id=None, mode="prompt", run_mode="once")
        )

    assert calls[0][0] == "list"
    assert calls[1][0] == "ready"
    assert select_epic.called


def test_work_prompt_yes_uses_first_epic_without_select() -> None:
    epics = [
        {
            "id": "atelier-epic-a",
            "title": "Epic A",
            "status": "open",
            "labels": ["at:epic"],
        },
        {
            "id": "atelier-epic-b",
            "title": "Epic B",
            "status": "open",
            "labels": ["at:epic"],
        },
    ]
    changesets = [{"id": "atelier-epic-a.1", "title": "First changeset"}]
    claimed: list[str] = []

    def fake_run_bd_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict]:
        post_session = _post_session_payload(args, changeset_id="atelier-epic-a.1")
        if post_session is not None:
            return post_session
        if args[0] == "list":
            return epics
        return changesets

    mapping = worktrees.WorktreeMapping(
        epic_id="atelier-epic-a",
        worktree_path="worktrees/atelier-epic-a",
        root_branch="feat/root",
        changesets={"atelier-epic-a.1": "feat/root-atelier-epic-a.1"},
        changeset_worktrees={},
    )
    agent = AgentHome(
        name="worker",
        agent_id="atelier/worker/agent",
        role="worker",
        path=Path("/project/agents/worker"),
    )

    def fake_claim_epic(epic_id: str, *args: object, **kwargs: object) -> dict:
        claimed.append(epic_id)
        return {
            "id": epic_id,
            "title": "Epic A",
            "description": "workspace.root_branch: feat/root\n",
        }

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
            return_value=("feat/root-atelier-epic-a.1", mapping),
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
        patch("atelier.commands.work.select") as select_epic,
        patch("atelier.commands.work.say"),
    ):
        work_cmd.start_worker(
            SimpleNamespace(epic_id=None, mode="prompt", run_mode="once", yes=True)
        )

    select_epic.assert_not_called()
    assert claimed == ["atelier-epic-a"]


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
        post_session = _post_session_payload(args, changeset_id="atelier-epic-hooked.1")
        if post_session is not None:
            return post_session
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
        changeset_worktrees={},
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
        patch(
            "atelier.commands.work.select",
            return_value="resume | atelier-epic-hooked [hooked] unset Epic hooked",
        ),
        patch("atelier.commands.work.say"),
    ):
        work_cmd.start_worker(
            SimpleNamespace(epic_id=None, mode="prompt", run_mode="once")
        )

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
        post_session = _post_session_payload(args, changeset_id="atelier-epic.1")
        if post_session is not None:
            return post_session
        calls.append(args)
        if args[0] == "list":
            return open_epics
        return changesets

    mapping = worktrees.WorktreeMapping(
        epic_id="atelier-epic",
        worktree_path="worktrees/atelier-epic",
        root_branch="feat/root",
        changesets={"atelier-epic.1": "feat/root-atelier-epic.1"},
        changeset_worktrees={},
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
        work_cmd.start_worker(
            SimpleNamespace(epic_id=None, mode="auto", run_mode="once")
        )

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
        post_session = _post_session_payload(args, changeset_id="atelier-epic-old.1")
        if post_session is not None:
            return post_session
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
        changeset_worktrees={},
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
        work_cmd.start_worker(
            SimpleNamespace(epic_id=None, mode="auto", run_mode="once")
        )

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
        post_session = _post_session_payload(args, changeset_id="atelier-epic.1")
        if post_session is not None:
            return post_session
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
        changeset_worktrees={},
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
        work_cmd.start_worker(
            SimpleNamespace(epic_id=None, mode="auto", run_mode="once")
        )

    assert calls[0][0] == "show"
    assert calls[1][0] == "ready"
    assert claimed == ["atelier-epic"]


def test_work_yes_passes_assume_yes_to_root_branch_prompt() -> None:
    epics = [
        {
            "id": "atelier-epic",
            "title": "Epic",
            "status": "open",
            "labels": ["at:epic"],
        }
    ]
    changesets = [{"id": "atelier-epic.1", "title": "First changeset"}]

    def fake_run_bd_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict]:
        post_session = _post_session_payload(args, changeset_id="atelier-epic.1")
        if post_session is not None:
            return post_session
        if args[0] == "list":
            return epics
        return changesets

    mapping = worktrees.WorktreeMapping(
        epic_id="atelier-epic",
        worktree_path="worktrees/atelier-epic",
        root_branch="feat/root",
        changesets={"atelier-epic.1": "feat/root-atelier-epic.1"},
        changeset_worktrees={},
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
                "description": "",
            },
        ),
        patch("atelier.commands.work.beads.update_worktree_path"),
        patch("atelier.commands.work.beads.set_agent_hook"),
        patch(
            "atelier.commands.work.agent_home.resolve_agent_home", return_value=agent
        ),
        patch("atelier.commands.work.select") as select_epic,
        patch(
            "atelier.commands.work.root_branch.prompt_root_branch",
            return_value="feat/root",
        ) as prompt_root_branch,
        patch("atelier.commands.work.say"),
    ):
        work_cmd.start_worker(
            SimpleNamespace(epic_id=None, mode="prompt", run_mode="once", yes=True)
        )

    select_epic.assert_not_called()
    assert prompt_root_branch.called
    assert prompt_root_branch.call_args.kwargs["assume_yes"] is True


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
        work_cmd.start_worker(
            SimpleNamespace(epic_id=None, mode="auto", run_mode="once")
        )

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
        post_session = _post_session_payload(args, changeset_id="atelier-epic-hooked.1")
        if post_session is not None:
            return post_session
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
        changeset_worktrees={},
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
        work_cmd.start_worker(
            SimpleNamespace(epic_id=None, mode="auto", run_mode="once")
        )

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
        work_cmd.start_worker(
            SimpleNamespace(epic_id=None, mode="auto", run_mode="once")
        )

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
        work_cmd.start_worker(
            SimpleNamespace(epic_id=None, mode="auto", queue=True, run_mode="once")
        )

    claim_epic.assert_not_called()


def test_work_invokes_startup_contract() -> None:
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
        patch(
            "atelier.commands.work.agent_home.resolve_agent_home", return_value=agent
        ),
        patch(
            "atelier.commands.work._run_startup_contract",
            return_value=work_cmd.StartupContractResult(
                epic_id=None, should_exit=True, reason="no_eligible_epics"
            ),
        ) as startup_contract,
        patch("atelier.commands.work.say"),
    ):
        work_cmd.start_worker(
            SimpleNamespace(epic_id=None, mode="auto", run_mode="once")
        )

    startup_contract.assert_called_once()
    assert startup_contract.call_args.kwargs["agent_id"] == "atelier/worker/agent"
    assert startup_contract.call_args.kwargs["explicit_epic_id"] is None


def test_work_auto_sends_needs_decision_when_idle() -> None:
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
        patch("atelier.commands.work.beads.list_queue_messages", return_value=[]),
        patch("atelier.commands.work.beads.claim_epic") as claim_epic,
        patch("atelier.commands.work.beads.create_message_bead") as send_message,
        patch(
            "atelier.commands.work.agent_home.resolve_agent_home", return_value=agent
        ),
        patch("atelier.commands.work.say"),
    ):
        work_cmd.start_worker(
            SimpleNamespace(epic_id=None, mode="auto", run_mode="once")
        )

    claim_epic.assert_not_called()
    send_message.assert_called_once()


def test_work_messages_planner_when_no_ready_changesets() -> None:
    epics = [
        {
            "id": "atelier-epic",
            "title": "Epic",
            "status": "open",
            "labels": ["at:epic"],
        }
    ]
    calls: list[list[str]] = []

    def fake_run_bd_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict]:
        calls.append(args)
        if args[0] == "list" and "at:epic" in args:
            return epics
        if args[0] == "show":
            return epics
        if args[0] == "ready":
            return []
        return []

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
        patch("atelier.commands.work.beads.run_bd_command") as run_bd_command,
        patch("atelier.commands.work.beads.list_inbox_messages", return_value=[]),
        patch("atelier.commands.work.beads.list_queue_messages", return_value=[]),
        patch("atelier.commands.work.beads.get_agent_hook", return_value=None),
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
        patch("atelier.commands.work.beads.set_agent_hook"),
        patch("atelier.commands.work.beads.clear_agent_hook") as clear_hook,
        patch("atelier.commands.work.beads.create_message_bead") as send_message,
        patch(
            "atelier.commands.work.agent_home.resolve_agent_home", return_value=agent
        ),
        patch("atelier.commands.work.say"),
    ):
        work_cmd.start_worker(
            SimpleNamespace(epic_id=None, mode="auto", run_mode="once")
        )

    assert calls[0][0] == "list"
    assert calls[1][0] == "ready"
    send_message.assert_called_once()
    clear_hook.assert_called_once()
    assert any(
        call.args[0][0] == "update" and "--assignee" in call.args[0]
        for call in run_bd_command.call_args_list
    )


def test_work_prompt_sends_needs_decision_when_idle() -> None:
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
        patch("atelier.commands.work.beads.list_queue_messages", return_value=[]),
        patch("atelier.commands.work.beads.claim_epic") as claim_epic,
        patch("atelier.commands.work.beads.create_message_bead") as send_message,
        patch(
            "atelier.commands.work.agent_home.resolve_agent_home", return_value=agent
        ),
        patch("atelier.commands.work.prompt") as prompt,
        patch("atelier.commands.work.say"),
    ):
        work_cmd.start_worker(
            SimpleNamespace(epic_id=None, mode="prompt", run_mode="once")
        )

    claim_epic.assert_not_called()
    prompt.assert_not_called()
    send_message.assert_called_once()


def test_work_dry_run_logs_and_skips_mutations() -> None:
    epics = [
        {
            "id": "atelier-epic",
            "title": "Epic",
            "status": "open",
            "labels": ["at:epic"],
        }
    ]
    changesets = [{"id": "atelier-epic.1", "title": "First changeset"}]

    def fake_run_bd_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict]:
        if args[0] == "list":
            return epics
        if args[0] == "ready":
            return changesets
        if args[0] == "show":
            return [
                {
                    "id": "atelier-epic",
                    "title": "Epic",
                    "description": "workspace.root_branch: feat/root\n",
                }
            ]
        return []

    agent = AgentHome(
        name="worker",
        agent_id="atelier/worker/agent",
        role="worker",
        path=Path("/project/agents/worker"),
    )

    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "atelier.commands.work.resolve_current_project_with_repo_root",
                return_value=(
                    Path("/project"),
                    _fake_project_payload(),
                    "/repo",
                    Path("/repo"),
                ),
            )
        )
        stack.enter_context(
            patch(
                "atelier.commands.work.config.resolve_beads_root",
                return_value=Path("/beads"),
            )
        )
        stack.enter_context(
            patch(
                "atelier.commands.work.beads.run_bd_json",
                side_effect=fake_run_bd_json,
            )
        )
        stack.enter_context(
            patch(
                "atelier.commands.work.beads.find_agent_bead",
                return_value={"id": "atelier-agent"},
            )
        )
        stack.enter_context(
            patch("atelier.commands.work.beads.get_agent_hook", return_value=None)
        )
        stack.enter_context(
            patch("atelier.commands.work.beads.list_inbox_messages", return_value=[])
        )
        stack.enter_context(
            patch("atelier.commands.work.beads.list_queue_messages", return_value=[])
        )
        claim_epic = stack.enter_context(
            patch("atelier.commands.work.beads.claim_epic")
        )
        set_hook = stack.enter_context(
            patch("atelier.commands.work.beads.set_agent_hook")
        )
        update_parent = stack.enter_context(
            patch("atelier.commands.work.beads.update_workspace_parent_branch")
        )
        ensure_git_worktree = stack.enter_context(
            patch("atelier.commands.work.worktrees.ensure_git_worktree")
        )
        run_codex = stack.enter_context(
            patch("atelier.commands.work.codex.run_codex_command")
        )
        say = stack.enter_context(patch("atelier.commands.work.say"))
        stack.enter_context(
            patch(
                "atelier.commands.work.agent_home.preview_agent_home",
                return_value=agent,
            )
        )

        work_cmd.start_worker(
            SimpleNamespace(epic_id=None, mode="auto", run_mode="once", dry_run=True)
        )

    claim_epic.assert_not_called()
    set_hook.assert_not_called()
    update_parent.assert_not_called()
    ensure_git_worktree.assert_not_called()
    run_codex.assert_not_called()
    assert any("DRY-RUN: Agent command:" in call.args[0] for call in say.call_args_list)


def test_work_dry_run_watch_sleeps() -> None:
    with (
        patch(
            "atelier.commands.work._run_worker_once",
            return_value=work_cmd.WorkerRunSummary(started=False, reason="no_work"),
        ) as run_once,
        patch("atelier.commands.work.time.sleep", side_effect=RuntimeError) as sleep,
    ):
        with pytest.raises(RuntimeError):
            work_cmd.start_worker(
                SimpleNamespace(
                    epic_id=None, mode="auto", run_mode="watch", dry_run=True
                )
            )

    assert run_once.call_args.kwargs["dry_run"] is True
    sleep.assert_called_once()


def test_work_uses_explicit_epic_id() -> None:
    changesets = [{"id": "atelier-epic.1", "title": "First changeset"}]
    calls: list[list[str]] = []

    def fake_run_bd_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict]:
        post_session = _post_session_payload(args, changeset_id="atelier-epic.1")
        if post_session is not None:
            return post_session
        calls.append(args)
        return changesets

    mapping = worktrees.WorktreeMapping(
        epic_id="atelier-epic",
        worktree_path="worktrees/atelier-epic",
        root_branch="feat/root",
        changesets={"atelier-epic.1": "feat/root-atelier-epic.1"},
        changeset_worktrees={},
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
        work_cmd.start_worker(
            SimpleNamespace(epic_id="atelier-epic", mode="prompt", run_mode="once")
        )

    assert calls[0][0] == "ready"


def test_work_records_branch_metadata(_branch_metadata_updates: object) -> None:
    update_epic, update_changeset = _branch_metadata_updates
    epics = [
        {
            "id": "atelier-epic",
            "title": "Epic",
            "status": "open",
            "labels": ["at:epic"],
        }
    ]
    changesets = [{"id": "atelier-epic.1", "title": "First changeset"}]

    def fake_run_bd_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict]:
        post_session = _post_session_payload(args, changeset_id="atelier-epic.1")
        if post_session is not None:
            return post_session
        if args[0] == "list":
            return epics
        return changesets

    mapping = worktrees.WorktreeMapping(
        epic_id="atelier-epic",
        worktree_path="worktrees/atelier-epic",
        root_branch="feat/root",
        changesets={"atelier-epic.1": "feat/root-atelier-epic.1"},
        changeset_worktrees={},
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
        patch("atelier.commands.work.git.git_rev_parse", return_value="deadbeef"),
        patch("atelier.commands.work.say"),
    ):
        work_cmd.start_worker(
            SimpleNamespace(epic_id=None, mode="auto", run_mode="once")
        )

    update_epic.assert_called_once_with(
        "atelier-epic",
        "feat/root",
        beads_root=Path("/beads"),
        cwd=Path("/repo"),
    )
    update_changeset.assert_called_once()
    kwargs = update_changeset.call_args.kwargs
    assert kwargs["root_branch"] == "feat/root"
    assert kwargs["parent_branch"] == "feat/root"
    assert kwargs["work_branch"] == "feat/root-atelier-epic.1"
    assert kwargs["root_base"] == "deadbeef"
    assert kwargs["parent_base"] == "deadbeef"


def test_work_marks_changeset_blocked_on_thread_message() -> None:
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
    message_description = messages.render_message(
        {"thread": "atelier-epic.1"}, "Need planner decision."
    )

    def fake_run_bd_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict]:
        if args[:2] == ["list", "--label"] and "at:message" in args:
            return [
                {
                    "id": "msg-1",
                    "description": message_description,
                    "created_at": "2999-01-01T00:00:00+00:00",
                }
            ]
        if args[:2] == ["show", "atelier-epic.1"]:
            return [{"id": "atelier-epic.1", "labels": ["cs:in_progress"]}]
        calls.append(args)
        if args[0] == "list":
            return epics
        return changesets

    mapping = worktrees.WorktreeMapping(
        epic_id="atelier-epic",
        worktree_path="worktrees/atelier-epic",
        root_branch="feat/root",
        changesets={"atelier-epic.1": "feat/root-atelier-epic.1"},
        changeset_worktrees={},
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
        patch("atelier.commands.work.beads.run_bd_command") as run_bd_command,
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
        work_cmd.start_worker(
            SimpleNamespace(epic_id=None, mode="auto", run_mode="once")
        )

    assert any(
        "--append-notes" in call.args[0] for call in run_bd_command.call_args_list
    )


def test_work_blocks_when_publish_signals_missing() -> None:
    epics = [
        {
            "id": "atelier-epic",
            "title": "Epic",
            "status": "open",
            "labels": ["at:epic"],
        }
    ]
    changesets = [{"id": "atelier-epic.1", "title": "First changeset"}]

    def fake_run_bd_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict]:
        post_session = _post_session_payload(args, changeset_id="atelier-epic.1")
        if post_session is not None:
            return post_session
        if args[0] == "list":
            return epics
        return changesets

    mapping = worktrees.WorktreeMapping(
        epic_id="atelier-epic",
        worktree_path="worktrees/atelier-epic",
        root_branch="feat/root",
        changesets={"atelier-epic.1": "feat/root-atelier-epic.1"},
        changeset_worktrees={},
    )
    agent = AgentHome(
        name="worker",
        agent_id="atelier/worker/agent",
        role="worker",
        path=Path("/project/agents/worker"),
    )

    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "atelier.commands.work.resolve_current_project_with_repo_root",
                return_value=(
                    Path("/project"),
                    _fake_project_payload(),
                    "/repo",
                    Path("/repo"),
                ),
            )
        )
        stack.enter_context(
            patch(
                "atelier.commands.work.config.resolve_beads_root",
                return_value=Path("/beads"),
            )
        )
        stack.enter_context(
            patch(
                "atelier.commands.work.beads.run_bd_json",
                side_effect=fake_run_bd_json,
            )
        )
        run_bd_command = stack.enter_context(
            patch("atelier.commands.work.beads.run_bd_command")
        )
        stack.enter_context(
            patch("atelier.commands.work.beads.list_inbox_messages", return_value=[])
        )
        stack.enter_context(
            patch("atelier.commands.work.beads.list_queue_messages", return_value=[])
        )
        stack.enter_context(
            patch("atelier.commands.work.beads.get_agent_hook", return_value=None)
        )
        stack.enter_context(
            patch(
                "atelier.commands.work.worktrees.ensure_changeset_branch",
                return_value=("feat/root-atelier-epic.1", mapping),
            )
        )
        stack.enter_context(
            patch("atelier.commands.work.worktrees.ensure_changeset_checkout")
        )
        stack.enter_context(
            patch("atelier.commands.work.worktrees.ensure_git_worktree")
        )
        stack.enter_context(
            patch(
                "atelier.commands.work.codex.run_codex_command",
                return_value=codex.CodexRunResult(
                    returncode=0, session_id=None, resume_command=None
                ),
            )
        )
        stack.enter_context(
            patch(
                "atelier.commands.work.beads.ensure_agent_bead",
                return_value={"id": "atelier-agent"},
            )
        )
        stack.enter_context(
            patch("atelier.commands.work.policy.sync_agent_home_policy")
        )
        stack.enter_context(
            patch(
                "atelier.commands.work.beads.claim_epic",
                return_value={
                    "id": "atelier-epic",
                    "title": "Epic",
                    "description": "workspace.root_branch: feat/root\n",
                },
            )
        )
        stack.enter_context(patch("atelier.commands.work.beads.update_worktree_path"))
        stack.enter_context(patch("atelier.commands.work.beads.set_agent_hook"))
        stack.enter_context(
            patch(
                "atelier.commands.work.agent_home.resolve_agent_home",
                return_value=agent,
            )
        )
        send_message = stack.enter_context(
            patch("atelier.commands.work.beads.create_message_bead")
        )
        stack.enter_context(
            patch("atelier.commands.work.git.git_ref_exists", return_value=False)
        )
        stack.enter_context(
            patch("atelier.commands.work.prs.read_github_pr_status", return_value=None)
        )
        stack.enter_context(patch("atelier.commands.work.say"))

        work_cmd.start_worker(
            SimpleNamespace(epic_id=None, mode="auto", run_mode="once")
        )

    send_message.assert_called_once()
    assert any(
        "--append-notes" in call.args[0] for call in run_bd_command.call_args_list
    )


def test_work_closes_epic_when_changeset_complete() -> None:
    epics = [
        {
            "id": "atelier-epic",
            "title": "Epic",
            "status": "open",
            "labels": ["at:epic"],
        }
    ]
    changesets = [{"id": "atelier-epic.1", "title": "First changeset"}]

    def fake_run_bd_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict]:
        if args[:2] == ["list", "--label"] and "at:message" in args:
            return []
        if args[:2] == ["show", "atelier-epic.1"]:
            return [{"id": "atelier-epic.1", "labels": ["cs:merged"]}]
        if args[0] == "list":
            return epics
        return changesets

    mapping = worktrees.WorktreeMapping(
        epic_id="atelier-epic",
        worktree_path="worktrees/atelier-epic",
        root_branch="feat/root",
        changesets={"atelier-epic.1": "feat/root-atelier-epic.1"},
        changeset_worktrees={},
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
        patch("atelier.commands.work.beads.close_epic_if_complete") as close_epic,
        patch(
            "atelier.commands.work.agent_home.resolve_agent_home", return_value=agent
        ),
        patch("atelier.commands.work.say"),
    ):
        work_cmd.start_worker(
            SimpleNamespace(epic_id=None, mode="auto", run_mode="once")
        )

    close_epic.assert_called_once()

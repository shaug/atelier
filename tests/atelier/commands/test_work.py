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


@pytest.fixture(autouse=True)
def _changeset_descendants() -> object:
    with patch(
        "atelier.commands.work.beads.list_descendant_changesets", return_value=[]
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
    changesets = [
        {
            "id": "atelier-epic.1",
            "title": "First changeset",
            "labels": ["at:changeset", "cs:ready"],
        }
    ]
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
    assert any(call and call[0] == "ready" for call in calls)
    assert select_epic.called


def test_mark_changeset_blocked_clears_terminal_labels() -> None:
    with patch("atelier.commands.work.beads.run_bd_command") as run_bd_command:
        work_cmd._mark_changeset_blocked(
            "atelier-epic.1",
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            reason="publish/checks signals missing",
        )

    args = run_bd_command.call_args.args[0]
    assert "cs:merged" in args
    assert "cs:abandoned" in args
    assert "cs:blocked" in args


def test_work_starts_codex_in_exec_mode() -> None:
    epics = [
        {
            "id": "atelier-epic",
            "title": "Epic",
            "status": "open",
            "labels": ["at:epic"],
        }
    ]
    changesets = [
        {
            "id": "atelier-epic.1",
            "title": "First changeset",
            "labels": ["at:changeset", "cs:ready"],
        }
    ]

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
        ),
        patch(
            "atelier.commands.work.codex.run_codex_command",
            return_value=codex.CodexRunResult(
                returncode=0, session_id=None, resume_command=None
            ),
        ) as run_codex,
        patch("atelier.commands.work.say"),
    ):
        work_cmd.start_worker(
            SimpleNamespace(epic_id=None, mode="prompt", run_mode="once")
        )

    started_cmd = run_codex.call_args.args[0]
    assert "exec" in started_cmd
    exec_index = started_cmd.index("exec")
    assert started_cmd[exec_index + 1] == "--skip-git-repo-check"
    opening_prompt = started_cmd[-1]
    assert "Execute only this assigned changeset" in opening_prompt
    assert "Changeset: atelier-epic.1: First changeset" in opening_prompt
    assert "--cd" not in started_cmd
    assert run_codex.call_args.kwargs["cwd"] == agent.path
    assert run_codex.call_args.kwargs["env"]["BEADS_DIR"] == "/beads"


def test_worker_opening_prompt_includes_review_feedback_context() -> None:
    opening_prompt = work_cmd._worker_opening_prompt(
        project_enlistment="/repo",
        workspace_branch="feat/root",
        epic_id="atelier-epic",
        changeset_id="atelier-epic.1",
        changeset_title="First changeset",
        review_feedback=True,
        review_pr_url="https://github.com/org/repo/pull/42",
    )

    assert "Priority mode: review-feedback" in opening_prompt
    assert "PR: https://github.com/org/repo/pull/42" in opening_prompt
    assert "Do not reset lifecycle labels to ready" in opening_prompt
    assert "reply inline to each comment and resolve the same thread" in opening_prompt
    assert "list_review_threads.py" in opening_prompt


def test_work_strips_codex_cd_option_override() -> None:
    project_config = _fake_project_payload()
    project_config.agent.options["codex"] = [
        "--cd",
        "/override/path",
        "--model",
        "gpt-5",
    ]
    epics = [
        {
            "id": "atelier-epic",
            "title": "Epic",
            "status": "open",
            "labels": ["at:epic"],
        }
    ]
    changesets = [
        {
            "id": "atelier-epic.1",
            "title": "First changeset",
            "labels": ["at:changeset", "cs:ready"],
        }
    ]

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
            return_value=(Path("/project"), project_config, "/repo", Path("/repo")),
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
        ),
        patch(
            "atelier.commands.work.codex.run_codex_command",
            return_value=codex.CodexRunResult(
                returncode=0, session_id=None, resume_command=None
            ),
        ) as run_codex,
        patch("atelier.commands.work.say"),
    ):
        work_cmd.start_worker(
            SimpleNamespace(epic_id=None, mode="prompt", run_mode="once")
        )

    started_cmd = run_codex.call_args.args[0]
    assert "--cd" not in started_cmd
    exec_index = started_cmd.index("exec")
    assert started_cmd[exec_index + 1] == "--skip-git-repo-check"
    assert "--model" in started_cmd
    assert run_codex.call_args.kwargs["cwd"] == agent.path


def test_next_changeset_prefers_in_progress() -> None:
    changesets = [
        {"id": "atelier-epic.1", "labels": ["at:changeset", "cs:ready"]},
        {"id": "atelier-epic.3", "labels": ["at:changeset", "cs:in_progress"]},
    ]

    def fake_run_bd_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict]:
        if args[:2] == ["show", "atelier-epic"]:
            return [{"id": "atelier-epic", "labels": ["at:epic"]}]
        return changesets

    with patch(
        "atelier.commands.work.beads.run_bd_json",
        side_effect=fake_run_bd_json,
    ):
        selected = work_cmd._next_changeset(
            epic_id="atelier-epic", beads_root=Path("/beads"), repo_root=Path("/repo")
        )

    assert selected is not None
    assert selected["id"] == "atelier-epic.3"


def test_next_changeset_skips_in_progress_waiting_on_review() -> None:
    changesets = [
        {
            "id": "atelier-epic.1",
            "labels": ["at:changeset", "cs:in_progress"],
            "description": "pr_state: in-review\n",
        },
        {"id": "atelier-epic.2", "labels": ["at:changeset", "cs:ready"]},
    ]

    def fake_run_bd_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict]:
        if args[:2] == ["show", "atelier-epic"]:
            return [{"id": "atelier-epic", "labels": ["at:epic"]}]
        return changesets

    with patch(
        "atelier.commands.work.beads.run_bd_json",
        side_effect=fake_run_bd_json,
    ):
        selected = work_cmd._next_changeset(
            epic_id="atelier-epic", beads_root=Path("/beads"), repo_root=Path("/repo")
        )

    assert selected is not None
    assert selected["id"] == "atelier-epic.2"


def test_next_changeset_skips_in_progress_with_push_signal_in_pr_mode() -> None:
    changesets = [
        {
            "id": "atelier-epic.1",
            "labels": ["at:changeset", "cs:in_progress"],
            "description": (
                "changeset.work_branch: feat/root-atelier-epic.1\n"
                "changeset.parent_branch: feat/root-atelier-epic.0\n"
            ),
        },
        {"id": "atelier-epic.2", "labels": ["at:changeset", "cs:ready"]},
    ]

    def fake_run_bd_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict]:
        if args[:2] == ["show", "atelier-epic"]:
            return [{"id": "atelier-epic", "labels": ["at:epic"]}]
        return changesets

    with (
        patch(
            "atelier.commands.work.beads.run_bd_json",
            side_effect=fake_run_bd_json,
        ),
        patch("atelier.commands.work.git.git_ref_exists", return_value=True),
        patch("atelier.commands.work.prs.read_github_pr_status", return_value=None),
    ):
        selected = work_cmd._next_changeset(
            epic_id="atelier-epic",
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            repo_slug="org/repo",
            branch_pr=True,
            branch_pr_strategy="on-parent-approved",
        )

    assert selected is not None
    assert selected["id"] == "atelier-epic.2"


def test_next_changeset_skips_non_leaf_parent() -> None:
    changesets = [
        {"id": "atelier-epic.1", "labels": ["at:changeset", "cs:in_progress"]},
        {"id": "atelier-epic.1.1", "labels": ["at:changeset", "cs:ready"]},
    ]

    def fake_descendants(
        issue_id: str, *, beads_root: Path, cwd: Path, include_closed: bool = False
    ) -> list[dict[str, object]]:
        if issue_id == "atelier-epic.1":
            return [{"id": "atelier-epic.1.1"}]
        return []

    def fake_run_bd_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict]:
        if args[:2] == ["show", "atelier-epic"]:
            return [{"id": "atelier-epic", "labels": ["at:epic"]}]
        return changesets

    with (
        patch(
            "atelier.commands.work.beads.run_bd_json",
            side_effect=fake_run_bd_json,
        ),
        patch(
            "atelier.commands.work.beads.list_descendant_changesets",
            side_effect=fake_descendants,
        ),
    ):
        selected = work_cmd._next_changeset(
            epic_id="atelier-epic", beads_root=Path("/beads"), repo_root=Path("/repo")
        )

    assert selected is not None
    assert selected["id"] == "atelier-epic.1.1"


def test_next_changeset_requires_ready_or_in_progress_label() -> None:
    changesets = [{"id": "atelier-epic.1", "labels": ["at:changeset"]}]

    def fake_run_bd_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict]:
        if args[:2] == ["show", "atelier-epic"]:
            return [{"id": "atelier-epic", "labels": ["at:epic"]}]
        return changesets

    with patch(
        "atelier.commands.work.beads.run_bd_json",
        side_effect=fake_run_bd_json,
    ):
        selected = work_cmd._next_changeset(
            epic_id="atelier-epic", beads_root=Path("/beads"), repo_root=Path("/repo")
        )

    assert selected is None


def test_next_changeset_treats_status_in_progress_as_active() -> None:
    changesets = [
        {"id": "atelier-epic.1", "labels": ["at:changeset"], "status": "in_progress"}
    ]

    def fake_run_bd_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict]:
        if args[:2] == ["show", "atelier-epic"]:
            return [{"id": "atelier-epic", "labels": ["at:epic"]}]
        return changesets

    with (
        patch("atelier.commands.work.beads.run_bd_json", side_effect=fake_run_bd_json),
        patch(
            "atelier.commands.work.beads.list_descendant_changesets", return_value=[]
        ),
    ):
        selected = work_cmd._next_changeset(
            epic_id="atelier-epic", beads_root=Path("/beads"), repo_root=Path("/repo")
        )

    assert selected is not None
    assert selected["id"] == "atelier-epic.1"


def test_next_changeset_allows_standalone_changeset() -> None:
    standalone = {
        "id": "at-irs",
        "labels": ["at:changeset", "cs:ready"],
    }

    def fake_run_bd_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict]:
        if args[:2] == ["show", "at-irs"]:
            return [standalone]
        if args[0] == "ready":
            return []
        return []

    with patch("atelier.commands.work.beads.run_bd_json", side_effect=fake_run_bd_json):
        selected = work_cmd._next_changeset(
            epic_id="at-irs", beads_root=Path("/beads"), repo_root=Path("/repo")
        )

    assert selected is not None
    assert selected["id"] == "at-irs"


def test_next_changeset_allows_ready_epic_without_child_changesets() -> None:
    epic = {"id": "at-ati", "labels": ["at:epic", "at:ready"], "status": "open"}

    def fake_run_bd_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict]:
        if args[:2] == ["show", "at-ati"]:
            return [epic]
        if args[0] == "ready":
            return []
        return []

    with (
        patch("atelier.commands.work.beads.run_bd_json", side_effect=fake_run_bd_json),
        patch(
            "atelier.commands.work.beads.list_descendant_changesets", return_value=[]
        ),
    ):
        selected = work_cmd._next_changeset(
            epic_id="at-ati", beads_root=Path("/beads"), repo_root=Path("/repo")
        )

    assert selected is not None
    assert selected["id"] == "at-ati"


def test_next_changeset_skips_ready_epic_when_child_changesets_exist() -> None:
    epic = {"id": "at-ati", "labels": ["at:epic", "at:ready"], "status": "open"}

    def fake_run_bd_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict]:
        if args[:2] == ["show", "at-ati"]:
            return [epic]
        if args[0] == "ready":
            return []
        return []

    with (
        patch("atelier.commands.work.beads.run_bd_json", side_effect=fake_run_bd_json),
        patch(
            "atelier.commands.work.beads.list_descendant_changesets",
            return_value=[{"id": "at-ati.1"}],
        ),
    ):
        selected = work_cmd._next_changeset(
            epic_id="at-ati", beads_root=Path("/beads"), repo_root=Path("/repo")
        )

    assert selected is None


def test_work_reuses_epic_worktree_for_epic_changeset() -> None:
    epic_issue = {
        "id": "at-ati",
        "title": "Epic as changeset",
        "status": "open",
        "labels": ["at:epic", "at:changeset", "at:ready", "cs:ready"],
        "description": (
            "workspace.root_branch: feat/root\n"
            "workspace.parent_branch: main\n"
            "changeset.root_branch: feat/root\n"
            "changeset.parent_branch: feat/root\n"
        ),
    }

    def fake_run_bd_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict]:
        if args[:2] == ["show", "at-ati"]:
            return [epic_issue]
        if args and args[0] == "list":
            return [epic_issue]
        if args and args[0] == "ready":
            return []
        return []

    mapping = worktrees.WorktreeMapping(
        epic_id="at-ati",
        worktree_path="worktrees/at-ati",
        root_branch="feat/root",
        changesets={"at-ati": "feat/root"},
        changeset_worktrees={},
    )
    agent = AgentHome(
        name="worker",
        agent_id="atelier/worker/agent",
        role="worker",
        path=Path("/project/agents/worker"),
    )
    epic_worktree = Path("/tmp/project/worktrees/at-ati")

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
            "atelier.commands.work.beads.ensure_agent_bead",
            return_value={"id": "atelier-agent"},
        ),
        patch("atelier.commands.work.policy.sync_agent_home_policy"),
        patch(
            "atelier.commands.work.beads.claim_epic",
            return_value=epic_issue,
        ),
        patch("atelier.commands.work.beads.update_worktree_path"),
        patch("atelier.commands.work.beads.set_agent_hook"),
        patch(
            "atelier.commands.work.agent_home.resolve_agent_home", return_value=agent
        ),
        patch(
            "atelier.commands.work.worktrees.ensure_git_worktree",
            return_value=epic_worktree,
        ),
        patch(
            "atelier.commands.work.worktrees.ensure_changeset_branch",
            return_value=("feat/root", mapping),
        ),
        patch("atelier.commands.work.worktrees.ensure_changeset_checkout"),
        patch(
            "atelier.commands.work.worktrees.ensure_changeset_worktree"
        ) as ensure_changeset_worktree,
        patch(
            "atelier.commands.work.codex.run_codex_command",
            return_value=codex.CodexRunResult(
                returncode=0, session_id=None, resume_command=None
            ),
        ),
        patch(
            "atelier.commands.work._finalize_changeset",
            return_value=work_cmd.FinalizeResult(
                continue_running=True, reason="changeset_complete"
            ),
        ),
        patch("atelier.commands.work.say"),
    ):
        work_cmd.start_worker(
            SimpleNamespace(epic_id=None, mode="auto", run_mode="once")
        )

    ensure_changeset_worktree.assert_not_called()


def test_mark_changeset_in_progress_adds_changeset_label() -> None:
    with patch("atelier.commands.work.beads.run_bd_command") as run_bd_command:
        work_cmd._mark_changeset_in_progress(
            "at-ati", beads_root=Path("/beads"), repo_root=Path("/repo")
        )

    args = run_bd_command.call_args.args[0]
    assert args[:2] == ["update", "at-ati"]
    assert "at:changeset" in args
    assert "cs:in_progress" in args


def test_find_invalid_changeset_labels_flags_subtasks() -> None:
    def fake_run_bd_json(
        args: list[str], *, beads_root: Path, cwd: Path
    ) -> list[dict[str, object]]:
        parent = args[2]
        if parent == "atelier-epic":
            return [{"id": "atelier-epic.1", "labels": ["at:changeset", "cs:ready"]}]
        if parent == "atelier-epic.1":
            return [{"id": "atelier-epic.1.1", "labels": ["at:subtask", "cs:ready"]}]
        return []

    with patch("atelier.commands.work.beads.run_bd_json", side_effect=fake_run_bd_json):
        invalid = work_cmd._find_invalid_changeset_labels(
            "atelier-epic", beads_root=Path("/beads"), repo_root=Path("/repo")
        )

    assert invalid == ["atelier-epic.1.1"]


def test_find_invalid_changeset_labels_flags_cs_without_changeset_label() -> None:
    def fake_run_bd_json(
        args: list[str], *, beads_root: Path, cwd: Path
    ) -> list[dict[str, object]]:
        parent = args[2]
        if parent == "atelier-epic":
            return [{"id": "atelier-epic.1", "labels": ["cs:ready"]}]
        return []

    with patch("atelier.commands.work.beads.run_bd_json", side_effect=fake_run_bd_json):
        invalid = work_cmd._find_invalid_changeset_labels(
            "atelier-epic", beads_root=Path("/beads"), repo_root=Path("/repo")
        )

    assert invalid == ["atelier-epic.1"]


def test_find_invalid_changeset_labels_flags_unknown_cs_label() -> None:
    def fake_run_bd_json(
        args: list[str], *, beads_root: Path, cwd: Path
    ) -> list[dict[str, object]]:
        parent = args[2]
        if parent == "atelier-epic":
            return [{"id": "atelier-epic.1", "labels": ["at:changeset", "cs:done"]}]
        return []

    with patch("atelier.commands.work.beads.run_bd_json", side_effect=fake_run_bd_json):
        invalid = work_cmd._find_invalid_changeset_labels(
            "atelier-epic", beads_root=Path("/beads"), repo_root=Path("/repo")
        )

    assert invalid == ["atelier-epic.1"]


def test_next_changeset_ignores_draft_top_level_changeset() -> None:
    with patch(
        "atelier.commands.work.beads.run_bd_json",
        return_value=[
            {
                "id": "at-9bh",
                "status": "open",
                "labels": ["at:changeset", "cs:ready", "at:draft"],
                "description": "changeset.work_branch: at-9bh\n",
            }
        ],
    ):
        selected = work_cmd._next_changeset(
            epic_id="at-9bh",
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
        )

    assert selected is None


def test_next_changeset_selects_blocked_top_level_with_push_signal() -> None:
    with (
        patch(
            "atelier.commands.work.beads.run_bd_json",
            return_value=[
                {
                    "id": "at-7tk",
                    "status": "in_progress",
                    "labels": ["at:changeset", "cs:blocked"],
                    "description": "changeset.work_branch: scott/at-7tk\n",
                }
            ],
        ),
        patch("atelier.commands.work.git.git_ref_exists", return_value=True),
        patch("atelier.commands.work.prs.read_github_pr_status", return_value=None),
    ):
        selected = work_cmd._next_changeset(
            epic_id="at-7tk",
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            repo_slug="org/repo",
            branch_pr=True,
            branch_pr_strategy="sequential",
        )

    assert selected is not None
    assert selected["id"] == "at-7tk"


def test_next_changeset_skips_blocked_top_level_without_publish_signal() -> None:
    with (
        patch(
            "atelier.commands.work.beads.run_bd_json",
            return_value=[
                {
                    "id": "at-7tk",
                    "status": "in_progress",
                    "labels": ["at:changeset", "cs:blocked"],
                    "description": "changeset.work_branch: scott/at-7tk\n",
                }
            ],
        ),
        patch("atelier.commands.work.git.git_ref_exists", return_value=False),
        patch("atelier.commands.work.prs.read_github_pr_status", return_value=None),
    ):
        selected = work_cmd._next_changeset(
            epic_id="at-7tk",
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            repo_slug="org/repo",
            branch_pr=True,
            branch_pr_strategy="sequential",
        )

    assert selected is None


def test_select_epic_from_ready_changesets_skips_draft_epics() -> None:
    issues = [
        {"id": "at-9bh", "status": "open", "labels": ["at:epic", "at:draft"]},
        {"id": "at-irs", "status": "open", "labels": ["at:epic", "at:ready"]},
    ]

    with patch(
        "atelier.commands.work.beads.run_bd_json",
        return_value=[
            {
                "id": "at-9bh.1",
                "created_at": "2026-02-01T00:00:00+00:00",
                "labels": ["at:changeset", "cs:ready"],
            },
            {
                "id": "at-irs.1",
                "created_at": "2026-02-02T00:00:00+00:00",
                "labels": ["at:changeset", "cs:ready"],
            },
        ],
    ):
        selected = work_cmd._select_epic_from_ready_changesets(
            issues=issues,
            is_actionable=lambda issue_id: issue_id in {"at-9bh", "at-irs"},
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
        )

    assert selected == "at-irs"


def test_select_epic_from_ready_changesets_skips_assigned_epics() -> None:
    issues = [
        {
            "id": "at-u9j",
            "status": "open",
            "labels": ["at:epic", "at:ready"],
            "assignee": "atelier/worker/codex/p123-t1",
        },
        {"id": "at-irs", "status": "open", "labels": ["at:epic", "at:ready"]},
    ]

    with patch(
        "atelier.commands.work.beads.run_bd_json",
        return_value=[
            {
                "id": "at-u9j.1",
                "created_at": "2026-02-01T00:00:00+00:00",
                "labels": ["at:changeset", "cs:ready"],
            },
            {
                "id": "at-irs.1",
                "created_at": "2026-02-02T00:00:00+00:00",
                "labels": ["at:changeset", "cs:ready"],
            },
        ],
    ):
        selected = work_cmd._select_epic_from_ready_changesets(
            issues=issues,
            is_actionable=lambda issue_id: issue_id in {"at-u9j", "at-irs"},
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
        )

    assert selected == "at-irs"


def test_changeset_base_branch_prefers_workspace_parent_when_parent_equals_root() -> (
    None
):
    issue = {
        "description": (
            "changeset.root_branch: scott/gum-1311-admin-role-update-end\n"
            "changeset.parent_branch: scott/gum-1311-admin-role-update-end\n"
            "workspace.parent_branch: main\n"
        )
    }

    base = work_cmd._changeset_base_branch(
        issue,
        repo_root=Path("/repo"),
        git_path=None,
    )

    assert base == "main"


def test_changeset_base_branch_uses_changeset_parent_when_distinct() -> None:
    issue = {
        "description": (
            "changeset.root_branch: scott/root\n"
            "changeset.parent_branch: scott/root-1\n"
            "workspace.parent_branch: main\n"
        )
    }

    base = work_cmd._changeset_base_branch(
        issue,
        repo_root=Path("/repo"),
        git_path=None,
    )

    assert base == "scott/root-1"


def test_changeset_base_branch_falls_back_to_epic_workspace_parent() -> None:
    issue = {
        "id": "at-7tk.1",
        "labels": ["at:changeset"],
        "parent": "at-7tk",
        "description": (
            "changeset.root_branch: scott/gum-1310-stripe-billing-webhoo\n"
            "changeset.parent_branch: scott/gum-1310-stripe-billing-webhoo\n"
        ),
    }

    def fake_run_bd_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict]:
        if args[:2] == ["show", "at-7tk"]:
            return [
                {
                    "id": "at-7tk",
                    "labels": ["at:epic"],
                    "description": "workspace.parent_branch: main\n",
                }
            ]
        return []

    with patch("atelier.commands.work.beads.run_bd_json", side_effect=fake_run_bd_json):
        base = work_cmd._changeset_base_branch(
            issue,
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            git_path=None,
        )

    assert base == "main"


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
    changesets = [
        {"id": "atelier-epic-a.1", "title": "First changeset", "labels": ["cs:ready"]}
    ]
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
    changesets = [
        {
            "id": "atelier-epic-hooked.1",
            "title": "First changeset",
            "labels": ["cs:ready"],
        }
    ]
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
    assert any(call and call[0] == "ready" for call in calls)
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
    changesets = [
        {"id": "atelier-epic.1", "title": "First changeset", "labels": ["cs:ready"]}
    ]
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
    assert any(call and call[0] == "ready" for call in calls)


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
    changesets = [
        {"id": "atelier-epic-old.1", "title": "First changeset", "labels": ["cs:ready"]}
    ]
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
    assert any(call and call[0] == "ready" for call in calls)
    assert claimed == ["atelier-epic-old"]


def test_work_resumes_hooked_epic() -> None:
    epic = {
        "id": "atelier-epic",
        "title": "Epic",
        "status": "open",
        "assignee": "atelier/worker/agent",
        "labels": ["at:epic", "at:hooked"],
    }
    changesets = [
        {
            "id": "atelier-epic.1",
            "title": "First changeset",
            "labels": ["at:changeset", "cs:ready"],
        }
    ]
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

    assert calls
    assert any(call[0] == "show" for call in calls)
    assert any(call and call[0] == "ready" for call in calls)
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
    changesets = [
        {"id": "atelier-epic.1", "title": "First changeset", "labels": ["cs:ready"]}
    ]

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
    changesets = [
        {
            "id": "atelier-epic-hooked.1",
            "title": "First changeset",
            "labels": ["cs:ready"],
        }
    ]
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


def test_startup_contract_reclaims_stale_same_family_epic() -> None:
    epics = [
        {
            "id": "atelier-epic-stale",
            "title": "Stale Epic",
            "status": "hooked",
            "labels": ["at:epic", "at:hooked"],
            "assignee": "atelier/worker/agent/p999999-t1",
            "created_at": "2026-02-01T00:00:00+00:00",
        }
    ]

    with (
        patch("atelier.commands.work.beads.run_bd_json", return_value=epics),
        patch(
            "atelier.commands.work._next_changeset",
            return_value={"id": "atelier-epic-stale.1"},
        ),
        patch("atelier.commands.work.os.kill", side_effect=ProcessLookupError),
        patch("atelier.commands.work.say"),
    ):
        result = work_cmd._run_startup_contract(
            agent_id="atelier/worker/agent/p123-t2",
            agent_bead_id=None,
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            mode="auto",
            explicit_epic_id=None,
            queue_only=False,
            dry_run=False,
            assume_yes=True,
        )

    assert result.should_exit is False
    assert result.reason == "stale_assignee_epic"
    assert result.epic_id == "atelier-epic-stale"
    assert result.reassign_from == "atelier/worker/agent/p999999-t1"


def test_startup_contract_skips_hooked_epic_without_ready_changesets() -> None:
    epics = [
        {
            "id": "atelier-epic-stalled",
            "title": "Stalled epic",
            "status": "open",
            "labels": ["at:epic"],
        },
        {
            "id": "atelier-epic-ready",
            "title": "Ready epic",
            "status": "open",
            "labels": ["at:epic"],
        },
    ]

    def fake_next_changeset(
        *,
        epic_id: str,
        beads_root: Path,
        repo_root: Path,
        repo_slug: str | None = None,
        branch_pr: bool = True,
        branch_pr_strategy: object = "sequential",
        git_path: str | None = None,
    ) -> dict[str, object] | None:
        if epic_id == "atelier-epic-ready":
            return {"id": "atelier-epic-ready.1"}
        return None

    with (
        patch(
            "atelier.commands.work._resolve_hooked_epic",
            return_value="atelier-epic-stalled",
        ),
        patch("atelier.commands.work.beads.run_bd_json", return_value=epics),
        patch("atelier.commands.work._next_changeset", side_effect=fake_next_changeset),
        patch("atelier.commands.work.beads.list_inbox_messages", return_value=[]),
        patch("atelier.commands.work.beads.list_queue_messages", return_value=[]),
        patch("atelier.commands.work.say"),
    ):
        result = work_cmd._run_startup_contract(
            agent_id="atelier/worker/agent/p123-t2",
            agent_bead_id="atelier-agent",
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            mode="auto",
            explicit_epic_id=None,
            queue_only=False,
            dry_run=False,
            assume_yes=True,
        )

    assert result.should_exit is False
    assert result.reason == "selected_auto"
    assert result.epic_id == "atelier-epic-ready"


def test_startup_contract_prioritizes_review_feedback_before_new_work() -> None:
    epics = [
        {
            "id": "atelier-epic-hooked",
            "title": "Hooked epic",
            "status": "open",
            "labels": ["at:epic"],
            "assignee": "atelier/worker/agent/p123-t2",
            "created_at": "2026-02-01T00:00:00+00:00",
        },
        {
            "id": "atelier-epic-ready",
            "title": "Ready epic",
            "status": "open",
            "labels": ["at:epic"],
            "created_at": "2026-02-02T00:00:00+00:00",
        },
    ]

    with (
        patch(
            "atelier.commands.work._resolve_hooked_epic",
            return_value="atelier-epic-hooked",
        ),
        patch("atelier.commands.work.beads.run_bd_json", return_value=epics),
        patch("atelier.commands.work.beads.list_inbox_messages", return_value=[]),
        patch("atelier.commands.work.beads.list_queue_messages", return_value=[]),
        patch(
            "atelier.commands.work._select_review_feedback_changeset",
            side_effect=lambda **kwargs: (
                work_cmd._ReviewFeedbackSelection(
                    epic_id="atelier-epic-hooked",
                    changeset_id="atelier-epic-hooked.2",
                    feedback_at="2026-02-20T12:00:00+00:00",
                )
                if kwargs["epic_id"] == "atelier-epic-hooked"
                else None
            ),
        ),
        patch(
            "atelier.commands.work.beads.update_changeset_review_feedback_cursor"
        ) as update_cursor,
        patch("atelier.commands.work.say"),
    ):
        result = work_cmd._run_startup_contract(
            agent_id="atelier/worker/agent/p123-t2",
            agent_bead_id="atelier-agent",
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            mode="auto",
            explicit_epic_id=None,
            queue_only=False,
            dry_run=False,
            assume_yes=True,
            repo_slug="org/repo",
            branch_pr=True,
        )

    assert result.should_exit is False
    assert result.reason == "review_feedback"
    assert result.epic_id == "atelier-epic-hooked"
    assert result.changeset_id == "atelier-epic-hooked.2"
    update_cursor.assert_not_called()


def test_select_review_feedback_changeset_ignores_cursor_for_blocked_changeset() -> (
    None
):
    descendants = [
        {
            "id": "at-u9j.1",
            "status": "blocked",
            "labels": ["at:changeset"],
            "description": (
                "changeset.work_branch: scott/gh-181-duplication-of-results-at-u9j.1\n"
                "pr_state: in-review\n"
                "review.last_feedback_seen_at: 2026-02-20T02:57:05Z\n"
            ),
        }
    ]
    with (
        patch(
            "atelier.commands.work.beads.list_descendant_changesets",
            return_value=descendants,
        ),
        patch("atelier.commands.work.prs.read_github_pr_status", return_value={}),
        patch(
            "atelier.commands.work.prs.latest_feedback_timestamp",
            return_value="2026-02-20T02:57:05Z",
        ),
    ):
        selected = work_cmd._select_review_feedback_changeset(
            epic_id="at-u9j",
            repo_slug="org/repo",
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
        )

    assert selected is not None
    assert selected.changeset_id == "at-u9j.1"


def test_select_review_feedback_changeset_respects_cursor_for_open_changeset() -> None:
    descendants = [
        {
            "id": "at-u9j.1",
            "status": "open",
            "labels": ["at:changeset"],
            "description": (
                "changeset.work_branch: scott/gh-181-duplication-of-results-at-u9j.1\n"
                "pr_state: in-review\n"
                "review.last_feedback_seen_at: 2026-02-20T02:57:05Z\n"
            ),
        }
    ]
    with (
        patch(
            "atelier.commands.work.beads.list_descendant_changesets",
            return_value=descendants,
        ),
        patch("atelier.commands.work.prs.read_github_pr_status", return_value={}),
        patch(
            "atelier.commands.work.prs.latest_feedback_timestamp",
            return_value="2026-02-20T02:57:05Z",
        ),
    ):
        selected = work_cmd._select_review_feedback_changeset(
            epic_id="at-u9j",
            repo_slug="org/repo",
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
        )

    assert selected is None


def test_select_review_feedback_changeset_uses_live_pr_state_without_pr_metadata() -> (
    None
):
    descendants = [
        {
            "id": "at-u9j.1",
            "status": "open",
            "labels": ["at:changeset"],
            "description": "changeset.work_branch: scott/gh-181-duplication-of-results-at-u9j.1\n",
        }
    ]
    with (
        patch(
            "atelier.commands.work.beads.list_descendant_changesets",
            return_value=descendants,
        ),
        patch(
            "atelier.commands.work.prs.read_github_pr_status",
            return_value={"state": "OPEN", "isDraft": False, "reviewDecision": None},
        ),
        patch(
            "atelier.commands.work.prs.latest_feedback_timestamp",
            return_value="2026-02-20T03:10:00Z",
        ),
    ):
        selected = work_cmd._select_review_feedback_changeset(
            epic_id="at-u9j",
            repo_slug="org/repo",
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
        )

    assert selected is not None
    assert selected.changeset_id == "at-u9j.1"


def test_select_review_feedback_changeset_prefers_live_terminal_state_over_stale_metadata() -> (
    None
):
    descendants = [
        {
            "id": "at-u9j.1",
            "status": "open",
            "labels": ["at:changeset"],
            "description": (
                "changeset.work_branch: scott/gh-181-duplication-of-results-at-u9j.1\n"
                "pr_state: in-review\n"
            ),
        }
    ]
    with (
        patch(
            "atelier.commands.work.beads.list_descendant_changesets",
            return_value=descendants,
        ),
        patch(
            "atelier.commands.work.prs.read_github_pr_status",
            return_value={"state": "CLOSED", "mergedAt": "2026-02-20T03:10:00Z"},
        ),
        patch(
            "atelier.commands.work.prs.latest_feedback_timestamp",
            return_value="2026-02-20T03:10:00Z",
        ),
    ):
        selected = work_cmd._select_review_feedback_changeset(
            epic_id="at-u9j",
            repo_slug="org/repo",
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
        )

    assert selected is None


def test_persist_review_feedback_cursor_updates_when_feedback_present() -> None:
    issue = {
        "id": "at-u9j.1",
        "description": "changeset.work_branch: scott/gh-181-duplication-of-results-at-u9j.1\n",
    }
    with (
        patch(
            "atelier.commands.work.prs.read_github_pr_status",
            return_value={"number": 204},
        ),
        patch(
            "atelier.commands.work.prs.latest_feedback_timestamp",
            return_value="2026-02-20T03:10:00Z",
        ),
        patch(
            "atelier.commands.work.beads.update_changeset_review_feedback_cursor"
        ) as update_cursor,
    ):
        work_cmd._persist_review_feedback_cursor(
            changeset_id="at-u9j.1",
            issue=issue,
            repo_slug="org/repo",
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
        )

    update_cursor.assert_called_once_with(
        "at-u9j.1",
        "2026-02-20T03:10:00Z",
        beads_root=Path("/beads"),
        cwd=Path("/repo"),
    )


def test_persist_review_feedback_cursor_skips_without_feedback_timestamp() -> None:
    issue = {
        "id": "at-u9j.1",
        "description": "changeset.work_branch: scott/gh-181-duplication-of-results-at-u9j.1\n",
    }
    with (
        patch(
            "atelier.commands.work.prs.read_github_pr_status",
            return_value={"number": 204},
        ),
        patch("atelier.commands.work.prs.latest_feedback_timestamp", return_value=None),
        patch(
            "atelier.commands.work.beads.update_changeset_review_feedback_cursor"
        ) as update_cursor,
    ):
        work_cmd._persist_review_feedback_cursor(
            changeset_id="at-u9j.1",
            issue=issue,
            repo_slug="org/repo",
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
        )

    update_cursor.assert_not_called()


def test_run_worker_once_persists_feedback_cursor_for_review_feedback() -> None:
    project_config = _fake_project_payload()
    project_config.branch.pr = True
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
    changeset = {
        "id": "atelier-epic.1",
        "title": "Feedback changeset",
        "labels": ["at:changeset", "cs:in_progress"],
        "description": (
            "changeset.work_branch: feat/root-atelier-epic.1\npr_state: in-review\n"
        ),
        "parent": "atelier-epic",
        "status": "in_progress",
    }

    def fake_run_bd_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict]:
        if args[:2] == ["show", "atelier-epic.1"]:
            return [changeset]
        if args[:2] == ["show", "atelier-epic"]:
            return [{"id": "atelier-epic", "labels": ["at:epic"], "status": "open"}]
        return []

    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "atelier.commands.work.resolve_current_project_with_repo_root",
                return_value=(
                    Path("/project"),
                    project_config,
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
                "atelier.commands.work.beads.run_bd_json", side_effect=fake_run_bd_json
            )
        )
        stack.enter_context(patch("atelier.commands.work.beads.run_bd_command"))
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
                    "description": (
                        "workspace.root_branch: feat/root\n"
                        "workspace.parent_branch: main\n"
                    ),
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
                "atelier.commands.work._run_startup_contract",
                return_value=work_cmd.StartupContractResult(
                    epic_id="atelier-epic",
                    changeset_id="atelier-epic.1",
                    should_exit=False,
                    reason="review_feedback",
                ),
            )
        )
        stack.enter_context(
            patch(
                "atelier.commands.work._find_invalid_changeset_labels", return_value=[]
            )
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
                "atelier.commands.work._finalize_changeset",
                return_value=work_cmd.FinalizeResult(
                    continue_running=True, reason="changeset_review_pending"
                ),
            )
        )
        persist_cursor = stack.enter_context(
            patch("atelier.commands.work._persist_review_feedback_cursor")
        )
        stack.enter_context(patch("atelier.commands.work.say"))

        summary = work_cmd._run_worker_once(
            SimpleNamespace(epic_id=None, mode="prompt", run_mode="once"),
            mode="prompt",
            dry_run=False,
            session_key="worker-test",
        )

    assert summary.started is True
    assert summary.reason == "agent_session_complete"
    persist_cursor.assert_called_once()
    assert persist_cursor.call_args.kwargs["changeset_id"] == "atelier-epic.1"


def test_startup_contract_review_feedback_reclaims_stale_assignee() -> None:
    epics = [
        {
            "id": "atelier-epic-stale",
            "title": "Stale epic",
            "status": "hooked",
            "labels": ["at:epic", "at:hooked"],
            "assignee": "atelier/worker/agent/p999999-t1",
            "created_at": "2026-02-01T00:00:00+00:00",
        }
    ]

    with (
        patch("atelier.commands.work.beads.run_bd_json", return_value=epics),
        patch("atelier.commands.work.beads.list_inbox_messages", return_value=[]),
        patch("atelier.commands.work.beads.list_queue_messages", return_value=[]),
        patch("atelier.commands.work.os.kill", side_effect=ProcessLookupError),
        patch(
            "atelier.commands.work._select_review_feedback_changeset",
            return_value=work_cmd._ReviewFeedbackSelection(
                epic_id="atelier-epic-stale",
                changeset_id="atelier-epic-stale.1",
                feedback_at="2026-02-20T12:00:00+00:00",
            ),
        ),
        patch(
            "atelier.commands.work.beads.update_changeset_review_feedback_cursor"
        ) as update_cursor,
        patch("atelier.commands.work.say"),
    ):
        result = work_cmd._run_startup_contract(
            agent_id="atelier/worker/agent/p123-t2",
            agent_bead_id=None,
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            mode="auto",
            explicit_epic_id=None,
            queue_only=False,
            dry_run=False,
            assume_yes=True,
            repo_slug="org/repo",
            branch_pr=True,
        )

    assert result.should_exit is False
    assert result.reason == "review_feedback"
    assert result.epic_id == "atelier-epic-stale"
    assert result.reassign_from == "atelier/worker/agent/p999999-t1"
    update_cursor.assert_not_called()


def test_startup_contract_prefers_hooked_ready_work_before_unhooked_feedback() -> None:
    epics = [
        {
            "id": "atelier-epic-hooked",
            "title": "Hooked epic",
            "status": "open",
            "labels": ["at:epic"],
            "assignee": "atelier/worker/agent/p123-t2",
            "created_at": "2026-02-01T00:00:00+00:00",
        },
        {
            "id": "atelier-epic-other",
            "title": "Other epic",
            "status": "open",
            "labels": ["at:epic"],
            "created_at": "2026-02-02T00:00:00+00:00",
        },
    ]
    selected_epics: list[str] = []

    with (
        patch(
            "atelier.commands.work._resolve_hooked_epic",
            return_value="atelier-epic-hooked",
        ),
        patch("atelier.commands.work.beads.run_bd_json", return_value=epics),
        patch("atelier.commands.work.beads.list_inbox_messages", return_value=[]),
        patch("atelier.commands.work.beads.list_queue_messages", return_value=[]),
        patch(
            "atelier.commands.work._next_changeset",
            side_effect=lambda **kwargs: (
                {"id": "atelier-epic-hooked.1"}
                if kwargs["epic_id"] == "atelier-epic-hooked"
                else {"id": "atelier-epic-other.1"}
            ),
        ),
        patch(
            "atelier.commands.work._select_review_feedback_changeset",
            side_effect=lambda **kwargs: (
                selected_epics.append(kwargs["epic_id"])
                or (
                    work_cmd._ReviewFeedbackSelection(
                        epic_id="atelier-epic-other",
                        changeset_id="atelier-epic-other.2",
                        feedback_at="2026-02-20T09:00:00+00:00",
                    )
                    if kwargs["epic_id"] == "atelier-epic-other"
                    else None
                )
            ),
        ),
        patch("atelier.commands.work.say"),
    ):
        result = work_cmd._run_startup_contract(
            agent_id="atelier/worker/agent/p123-t2",
            agent_bead_id="atelier-agent",
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            mode="auto",
            explicit_epic_id=None,
            queue_only=False,
            dry_run=False,
            assume_yes=True,
            repo_slug="org/repo",
            branch_pr=True,
        )

    assert result.should_exit is False
    assert result.reason == "hooked_epic"
    assert result.epic_id == "atelier-epic-hooked"
    assert selected_epics == ["atelier-epic-hooked"]


def test_startup_contract_checks_unhooked_feedback_when_hooked_has_no_work() -> None:
    epics = [
        {
            "id": "atelier-epic-hooked",
            "title": "Hooked epic",
            "status": "open",
            "labels": ["at:epic"],
            "assignee": "atelier/worker/agent/p123-t2",
            "created_at": "2026-02-01T00:00:00+00:00",
        },
        {
            "id": "atelier-epic-other",
            "title": "Other epic",
            "status": "open",
            "labels": ["at:epic"],
            "created_at": "2026-02-02T00:00:00+00:00",
        },
    ]

    with (
        patch(
            "atelier.commands.work._resolve_hooked_epic",
            return_value="atelier-epic-hooked",
        ),
        patch("atelier.commands.work.beads.run_bd_json", return_value=epics),
        patch("atelier.commands.work.beads.list_inbox_messages", return_value=[]),
        patch("atelier.commands.work.beads.list_queue_messages", return_value=[]),
        patch(
            "atelier.commands.work._next_changeset",
            side_effect=lambda **kwargs: (
                {"id": "atelier-epic-other.1"}
                if kwargs["epic_id"] == "atelier-epic-other"
                else None
            ),
        ),
        patch(
            "atelier.commands.work._select_review_feedback_changeset",
            side_effect=lambda **kwargs: (
                work_cmd._ReviewFeedbackSelection(
                    epic_id="atelier-epic-other",
                    changeset_id="atelier-epic-other.2",
                    feedback_at="2026-02-20T09:00:00+00:00",
                )
                if kwargs["epic_id"] == "atelier-epic-other"
                else None
            ),
        ),
        patch(
            "atelier.commands.work.beads.update_changeset_review_feedback_cursor"
        ) as update_cursor,
        patch("atelier.commands.work.say"),
    ):
        result = work_cmd._run_startup_contract(
            agent_id="atelier/worker/agent/p123-t2",
            agent_bead_id="atelier-agent",
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            mode="auto",
            explicit_epic_id=None,
            queue_only=False,
            dry_run=False,
            assume_yes=True,
            repo_slug="org/repo",
            branch_pr=True,
        )

    assert result.should_exit is False
    assert result.reason == "review_feedback"
    assert result.epic_id == "atelier-epic-other"
    assert result.changeset_id == "atelier-epic-other.2"
    update_cursor.assert_not_called()


def test_startup_contract_considers_blocked_epics_for_review_feedback() -> None:
    epics = [
        {
            "id": "atelier-epic-blocked",
            "title": "Blocked epic",
            "status": "blocked",
            "labels": ["at:epic"],
            "created_at": "2026-02-02T00:00:00+00:00",
        }
    ]

    with (
        patch("atelier.commands.work.beads.run_bd_json", return_value=epics),
        patch("atelier.commands.work.beads.list_inbox_messages", return_value=[]),
        patch("atelier.commands.work.beads.list_queue_messages", return_value=[]),
        patch(
            "atelier.commands.work._select_review_feedback_changeset",
            return_value=work_cmd._ReviewFeedbackSelection(
                epic_id="atelier-epic-blocked",
                changeset_id="atelier-epic-blocked.1",
                feedback_at="2026-02-20T09:00:00+00:00",
            ),
        ),
        patch(
            "atelier.commands.work.beads.update_changeset_review_feedback_cursor"
        ) as update_cursor,
        patch("atelier.commands.work.say"),
    ):
        result = work_cmd._run_startup_contract(
            agent_id="atelier/worker/agent/p123-t2",
            agent_bead_id=None,
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            mode="auto",
            explicit_epic_id=None,
            queue_only=False,
            dry_run=False,
            assume_yes=True,
            repo_slug="org/repo",
            branch_pr=True,
        )

    assert result.should_exit is False
    assert result.reason == "review_feedback"
    assert result.epic_id == "atelier-epic-blocked"
    assert result.changeset_id == "atelier-epic-blocked.1"
    update_cursor.assert_not_called()


def test_startup_contract_uses_global_feedback_when_no_epics_available() -> None:
    with (
        patch("atelier.commands.work.beads.run_bd_json", return_value=[]),
        patch("atelier.commands.work.beads.list_inbox_messages", return_value=[]),
        patch("atelier.commands.work.beads.list_queue_messages", return_value=[]),
        patch(
            "atelier.commands.work._select_global_review_feedback_changeset",
            return_value=work_cmd._ReviewFeedbackSelection(
                epic_id="at-u9j",
                changeset_id="at-u9j.1",
                feedback_at="2026-02-20T12:00:00+00:00",
            ),
        ),
        patch(
            "atelier.commands.work.beads.update_changeset_review_feedback_cursor"
        ) as update_cursor,
        patch("atelier.commands.work.say"),
    ):
        result = work_cmd._run_startup_contract(
            agent_id="atelier/worker/agent/p123-t2",
            agent_bead_id=None,
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            mode="auto",
            explicit_epic_id=None,
            queue_only=False,
            dry_run=False,
            assume_yes=True,
            repo_slug="org/repo",
            branch_pr=True,
        )

    assert result.should_exit is False
    assert result.reason == "review_feedback"
    assert result.epic_id == "at-u9j"
    assert result.changeset_id == "at-u9j.1"
    update_cursor.assert_not_called()


def test_startup_contract_global_feedback_reclaims_stale_same_family_assignee() -> None:
    def fake_run_bd_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict]:
        if args[:2] == ["list", "--label"]:
            return []
        if args[:2] == ["show", "at-u9j"]:
            return [
                {
                    "id": "at-u9j",
                    "assignee": "atelier/worker/agent/p999999-t1",
                    "labels": ["at:epic"],
                    "status": "open",
                }
            ]
        return []

    with (
        patch("atelier.commands.work.beads.run_bd_json", side_effect=fake_run_bd_json),
        patch("atelier.commands.work.beads.list_inbox_messages", return_value=[]),
        patch("atelier.commands.work.beads.list_queue_messages", return_value=[]),
        patch(
            "atelier.commands.work._select_global_review_feedback_changeset",
            return_value=work_cmd._ReviewFeedbackSelection(
                epic_id="at-u9j",
                changeset_id="at-u9j.1",
                feedback_at="2026-02-20T12:00:00+00:00",
            ),
        ),
        patch("atelier.commands.work.os.kill", side_effect=ProcessLookupError),
        patch("atelier.commands.work.beads.update_changeset_review_feedback_cursor"),
        patch("atelier.commands.work.say"),
    ):
        result = work_cmd._run_startup_contract(
            agent_id="atelier/worker/agent/p123-t2",
            agent_bead_id=None,
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            mode="auto",
            explicit_epic_id=None,
            queue_only=False,
            dry_run=False,
            assume_yes=True,
            repo_slug="org/repo",
            branch_pr=True,
        )

    assert result.reason == "review_feedback"
    assert result.reassign_from == "atelier/worker/agent/p999999-t1"


def test_startup_contract_falls_back_to_global_ready_changeset() -> None:
    epics = [
        {
            "id": "atelier-epic-stalled",
            "title": "Stalled epic",
            "status": "open",
            "labels": ["at:epic"],
        }
    ]

    def fake_run_bd_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict]:
        if args[:2] == ["list", "--label"]:
            return epics
        if args[:2] == ["ready", "--label"]:
            return [
                {
                    "id": "at-irs",
                    "title": "Guardrail changeset",
                    "labels": ["at:changeset", "cs:ready"],
                    "created_at": "2026-02-01T00:00:00+00:00",
                }
            ]
        return []

    def fake_next_changeset(
        *,
        epic_id: str,
        beads_root: Path,
        repo_root: Path,
        repo_slug: str | None = None,
        branch_pr: bool = True,
        branch_pr_strategy: object = "sequential",
        git_path: str | None = None,
    ) -> dict[str, object] | None:
        if epic_id == "at-irs":
            return {"id": "at-irs"}
        return None

    with (
        patch("atelier.commands.work.beads.run_bd_json", side_effect=fake_run_bd_json),
        patch("atelier.commands.work._next_changeset", side_effect=fake_next_changeset),
        patch("atelier.commands.work.beads.list_inbox_messages", return_value=[]),
        patch("atelier.commands.work.beads.list_queue_messages", return_value=[]),
        patch("atelier.commands.work.say"),
    ):
        result = work_cmd._run_startup_contract(
            agent_id="atelier/worker/agent/p123-t2",
            agent_bead_id=None,
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            mode="auto",
            explicit_epic_id=None,
            queue_only=False,
            dry_run=False,
            assume_yes=True,
        )

    assert result.should_exit is False
    assert result.reason == "selected_ready_changeset"
    assert result.epic_id == "at-irs"


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
        patch(
            "atelier.commands.work.beads.list_queue_messages", return_value=queued
        ) as list_queue,
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
    list_queue.assert_called_once_with(
        beads_root=Path("/beads"),
        cwd=Path("/repo"),
        queue="worker",
        unread_only=True,
    )
    claim_epic.assert_not_called()


def test_work_queue_prompt_skip_continues_to_epic_selection() -> None:
    queued = [{"id": "msg-1", "title": "Queue item", "queue": "worker"}]
    epics = [
        {
            "id": "atelier-epic",
            "title": "Epic",
            "status": "open",
            "labels": ["at:epic"],
        }
    ]
    changesets = [
        {
            "id": "atelier-epic.1",
            "title": "First changeset",
            "labels": ["at:changeset", "cs:ready"],
        }
    ]
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

    def fake_run_bd_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict]:
        post_session = _post_session_payload(args, changeset_id="atelier-epic.1")
        if post_session is not None:
            return post_session
        if args[0] == "list" and "at:epic" in args:
            return epics
        return changesets

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
        patch("atelier.commands.work.beads.list_inbox_messages", return_value=[]),
        patch("atelier.commands.work.beads.list_queue_messages", return_value=queued),
        patch("atelier.commands.work.beads.claim_queue_message") as claim_queue,
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
        ) as claim_epic,
        patch("atelier.commands.work.beads.update_worktree_path"),
        patch("atelier.commands.work.beads.set_agent_hook"),
        patch(
            "atelier.commands.work.agent_home.resolve_agent_home", return_value=agent
        ),
        patch("atelier.commands.work.prompt", return_value=""),
        patch("atelier.commands.work.say"),
    ):
        work_cmd.start_worker(
            SimpleNamespace(epic_id=None, mode="auto", run_mode="once")
        )

    claim_queue.assert_not_called()
    claim_epic.assert_called_once()


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
            "atelier.commands.work.reconcile_blocked_merged_changesets",
            return_value=work_cmd.ReconcileResult(
                scanned=0, actionable=0, reconciled=0, failed=0
            ),
        ),
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
                epic_id=None,
                changeset_id=None,
                should_exit=True,
                reason="no_eligible_epics",
            ),
        ) as startup_contract,
        patch(
            "atelier.commands.work.reconcile_blocked_merged_changesets",
            return_value=work_cmd.ReconcileResult(
                scanned=0, actionable=0, reconciled=0, failed=0
            ),
        ) as reconcile,
        patch("atelier.commands.work.say"),
    ):
        work_cmd.start_worker(
            SimpleNamespace(epic_id=None, mode="auto", run_mode="once")
        )

    startup_contract.assert_called_once()
    reconcile.assert_not_called()
    assert startup_contract.call_args.kwargs["agent_id"] == "atelier/worker/agent"
    assert startup_contract.call_args.kwargs["explicit_epic_id"] is None


def test_work_runs_reconcile_when_flag_enabled() -> None:
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
                epic_id=None,
                changeset_id=None,
                should_exit=True,
                reason="no_eligible_epics",
            ),
        ),
        patch(
            "atelier.commands.work.reconcile_blocked_merged_changesets",
            return_value=work_cmd.ReconcileResult(
                scanned=1, actionable=1, reconciled=1, failed=0
            ),
        ) as reconcile,
        patch("atelier.commands.work.say"),
    ):
        work_cmd.start_worker(
            SimpleNamespace(epic_id=None, mode="auto", run_mode="once", reconcile=True)
        )

    reconcile.assert_called_once()


def test_work_cleans_up_session_agent_home_on_exit(tmp_path: Path) -> None:
    project_root = Path("/project")
    repo_root = Path("/repo")
    agent = AgentHome(
        name="worker",
        agent_id="atelier/worker/agent/p100-t200",
        role="worker",
        path=tmp_path / "agents" / "worker" / "agent" / "p100-t200",
        session_key="p100-t200",
    )

    with (
        patch(
            "atelier.commands.work.resolve_current_project_with_repo_root",
            return_value=(
                project_root,
                _fake_project_payload(),
                "/repo",
                repo_root,
            ),
        ),
        patch(
            "atelier.commands.work.config.resolve_project_data_dir",
            return_value=tmp_path,
        ),
        patch(
            "atelier.commands.work.agent_home.preview_agent_home",
            return_value=agent,
        ),
        patch(
            "atelier.commands.work._run_worker_once",
            return_value=work_cmd.WorkerRunSummary(
                started=False, reason="no_eligible_epics"
            ),
        ),
        patch("atelier.commands.work._report_worker_summary"),
        patch("atelier.commands.work.agent_home.cleanup_agent_home") as cleanup_home,
    ):
        work_cmd.start_worker(
            SimpleNamespace(epic_id=None, mode="auto", run_mode="once", dry_run=False)
        )

    cleanup_home.assert_called_once_with(agent, project_dir=tmp_path)


def test_work_once_retries_after_no_ready_changesets() -> None:
    with (
        patch(
            "atelier.commands.work._run_worker_once",
            side_effect=[
                work_cmd.WorkerRunSummary(
                    started=False,
                    reason="no_ready_changesets",
                    epic_id="atelier-epic",
                ),
                work_cmd.WorkerRunSummary(
                    started=False,
                    reason="no_eligible_epics",
                ),
            ],
        ) as run_once,
        patch("atelier.commands.work._report_worker_summary"),
    ):
        work_cmd.start_worker(
            SimpleNamespace(
                epic_id=None, mode="auto", run_mode="once", dry_run=True, queue=False
            )
        )

    assert run_once.call_count == 2


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
    assert any(call and call[0] == "ready" for call in calls)
    send_message.assert_called_once()
    clear_hook.assert_not_called()
    assert not any(
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
    changesets = [
        {"id": "atelier-epic.1", "title": "First changeset", "labels": ["cs:ready"]}
    ]

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
    changesets = [
        {
            "id": "atelier-epic.1",
            "title": "First changeset",
            "labels": ["at:changeset", "cs:ready"],
        }
    ]
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

    assert any(call and call[0] == "ready" for call in calls)


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
    changesets = [
        {"id": "atelier-epic.1", "title": "First changeset", "labels": ["cs:ready"]}
    ]

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
        "main",
        beads_root=Path("/beads"),
        cwd=Path("/repo"),
        allow_override=False,
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
    changesets = [
        {"id": "atelier-epic.1", "title": "First changeset", "labels": ["cs:ready"]}
    ]
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
    assert any(
        "--status" in call.args[0] and "blocked" in call.args[0]
        for call in run_bd_command.call_args_list
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
    changesets = [
        {"id": "atelier-epic.1", "title": "First changeset", "labels": ["cs:ready"]}
    ]

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
    assert any(
        "--status" in call.args[0] and "blocked" in call.args[0]
        for call in run_bd_command.call_args_list
    )


def test_finalize_blocks_merged_without_integration_signal() -> None:
    run_commands: list[list[str]] = []
    sent_messages: list[dict[str, object]] = []

    with (
        patch(
            "atelier.commands.work.beads.run_bd_json",
            return_value=[
                {
                    "id": "atelier-epic.1",
                    "labels": ["at:changeset", "cs:merged"],
                    "description": "changeset.work_branch: feat/root-atelier-epic.1\n",
                }
            ],
        ),
        patch(
            "atelier.commands.work.beads.list_descendant_changesets", return_value=[]
        ),
        patch(
            "atelier.commands.work.beads.run_bd_command",
            side_effect=lambda args, **kwargs: run_commands.append(list(args)),
        ),
        patch(
            "atelier.commands.work.beads.create_message_bead",
            side_effect=lambda **kwargs: sent_messages.append(kwargs),
        ),
        patch("atelier.commands.work.prs.read_github_pr_status", return_value=None),
        patch("atelier.commands.work.git.git_ref_exists", return_value=False),
    ):
        result = work_cmd._finalize_changeset(
            changeset_id="atelier-epic.1",
            epic_id="atelier-epic",
            agent_id="atelier/worker/agent",
            agent_bead_id="atelier-agent",
            started_at=work_cmd.dt.datetime.now(tz=work_cmd.dt.timezone.utc),
            repo_slug="org/repo",
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
        )

    assert result.continue_running is False
    assert result.reason == "changeset_blocked_missing_integration"
    assert any(
        args[:2] == ["update", "atelier-epic.1"] and "cs:blocked" in args
        for args in run_commands
    )
    assert len(sent_messages) == 1


def test_finalize_merged_without_integration_recovers_to_pr_creation() -> None:
    with (
        patch(
            "atelier.commands.work.beads.run_bd_json",
            return_value=[
                {
                    "id": "atelier-epic.1",
                    "title": "My changeset",
                    "labels": ["at:changeset", "cs:merged"],
                    "description": "changeset.work_branch: feat/root-atelier-epic.1\n",
                    "status": "closed",
                }
            ],
        ),
        patch(
            "atelier.commands.work.beads.list_descendant_changesets", return_value=[]
        ),
        patch("atelier.commands.work._find_invalid_changeset_labels", return_value=[]),
        patch("atelier.commands.work._has_blocking_messages", return_value=False),
        patch("atelier.commands.work.git.git_ref_exists", return_value=True),
        patch("atelier.commands.work.prs.read_github_pr_status", return_value=None),
        patch(
            "atelier.commands.work._attempt_create_draft_pr",
            return_value=(True, "created"),
        ),
        patch("atelier.commands.work._mark_changeset_in_progress") as mark_in_progress,
        patch("atelier.commands.work.beads.update_changeset_review") as update_review,
    ):
        result = work_cmd._finalize_changeset(
            changeset_id="atelier-epic.1",
            epic_id="atelier-epic",
            agent_id="atelier/worker/agent",
            agent_bead_id="atelier-agent",
            started_at=work_cmd.dt.datetime.now(tz=work_cmd.dt.timezone.utc),
            repo_slug="org/repo",
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            branch_pr=True,
            branch_pr_strategy="sequential",
        )

    assert result.continue_running is True
    assert result.reason == "changeset_review_pending"
    mark_in_progress.assert_called_once()
    update_review.assert_called_once()


def test_finalize_merged_without_integration_recovers_to_review_pending() -> None:
    with (
        patch(
            "atelier.commands.work.beads.run_bd_json",
            return_value=[
                {
                    "id": "atelier-epic.1",
                    "title": "My changeset",
                    "labels": ["at:changeset", "cs:merged"],
                    "description": "changeset.work_branch: feat/root-atelier-epic.1\n",
                    "status": "closed",
                }
            ],
        ),
        patch(
            "atelier.commands.work.beads.list_descendant_changesets", return_value=[]
        ),
        patch("atelier.commands.work._find_invalid_changeset_labels", return_value=[]),
        patch("atelier.commands.work._has_blocking_messages", return_value=False),
        patch("atelier.commands.work.git.git_ref_exists", return_value=True),
        patch(
            "atelier.commands.work.prs.read_github_pr_status",
            return_value={
                "number": 42,
                "url": "https://github.com/org/repo/pull/42",
                "state": "OPEN",
                "isDraft": False,
                "reviewDecision": None,
                "reviewRequests": [{"requestedReviewer": {"login": "alice"}}],
            },
        ),
        patch("atelier.commands.work._mark_changeset_in_progress") as mark_in_progress,
        patch("atelier.commands.work.beads.update_changeset_review") as update_review,
    ):
        result = work_cmd._finalize_changeset(
            changeset_id="atelier-epic.1",
            epic_id="atelier-epic",
            agent_id="atelier/worker/agent",
            agent_bead_id="atelier-agent",
            started_at=work_cmd.dt.datetime.now(tz=work_cmd.dt.timezone.utc),
            repo_slug="org/repo",
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            branch_pr=True,
            branch_pr_strategy="sequential",
        )

    assert result.continue_running is True
    assert result.reason == "changeset_review_pending"
    mark_in_progress.assert_called_once()
    update_review.assert_called_once()


def test_finalize_accepts_merged_with_graph_integration_signal() -> None:
    run_commands: list[list[str]] = []

    with (
        patch(
            "atelier.commands.work.beads.run_bd_json",
            return_value=[
                {
                    "id": "atelier-epic.1",
                    "labels": ["at:changeset", "cs:merged"],
                    "description": (
                        "changeset.root_branch: feat/root\n"
                        "changeset.work_branch: feat/root-atelier-epic.1\n"
                    ),
                }
            ],
        ),
        patch(
            "atelier.commands.work.beads.list_descendant_changesets", return_value=[]
        ),
        patch(
            "atelier.commands.work.beads.run_bd_command",
            side_effect=lambda args, **kwargs: run_commands.append(list(args)),
        ),
        patch("atelier.commands.work.beads.close_epic_if_complete") as close_epic,
        patch(
            "atelier.commands.work.git.git_ref_exists",
            side_effect=lambda repo, ref: (
                ref
                in {
                    "refs/heads/feat/root",
                    "refs/heads/feat/root-atelier-epic.1",
                }
            ),
        ),
        patch("atelier.commands.work.git.git_is_ancestor", return_value=True),
        patch("atelier.commands.work.git.git_rev_parse", return_value="abc123"),
        patch("atelier.commands.work.prs.read_github_pr_status", return_value=None),
    ):
        result = work_cmd._finalize_changeset(
            changeset_id="atelier-epic.1",
            epic_id="atelier-epic",
            agent_id="atelier/worker/agent",
            agent_bead_id="atelier-agent",
            started_at=work_cmd.dt.datetime.now(tz=work_cmd.dt.timezone.utc),
            repo_slug=None,
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
        )

    assert result.continue_running is True
    assert result.reason == "changeset_complete"
    assert any(
        args[:2] == ["update", "atelier-epic.1"] and "--body-file" in args
        for args in run_commands
    )
    close_epic.assert_called_once()


def test_finalize_accepts_merged_with_integrated_sha_in_notes() -> None:
    run_commands: list[list[str]] = []

    with (
        patch(
            "atelier.commands.work.beads.run_bd_json",
            return_value=[
                {
                    "id": "atelier-epic.1",
                    "labels": ["at:changeset", "cs:merged"],
                    "description": (
                        "notes:\n"
                        "- `changeset.integrated_sha`: "
                        "67c7ca10898839106bbb9377e0ed0709fc7c0fbf\n"
                    ),
                }
            ],
        ),
        patch(
            "atelier.commands.work.beads.list_descendant_changesets", return_value=[]
        ),
        patch(
            "atelier.commands.work.beads.run_bd_command",
            side_effect=lambda args, **kwargs: run_commands.append(list(args)),
        ),
        patch("atelier.commands.work.beads.close_epic_if_complete") as close_epic,
        patch("atelier.commands.work.prs.read_github_pr_status", return_value=None),
    ):
        result = work_cmd._finalize_changeset(
            changeset_id="atelier-epic.1",
            epic_id="atelier-epic",
            agent_id="atelier/worker/agent",
            agent_bead_id="atelier-agent",
            started_at=work_cmd.dt.datetime.now(tz=work_cmd.dt.timezone.utc),
            repo_slug=None,
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
        )

    assert result.continue_running is True
    assert result.reason == "changeset_complete"
    assert any(
        args[:2] == ["update", "atelier-epic.1"] and "--body-file" in args
        for args in run_commands
    )
    close_epic.assert_called_once()


def test_integration_signal_reads_sha_from_realistic_notes_payload() -> None:
    issue = {
        "id": "at-wjj.4.2",
        "labels": ["at:changeset", "cs:blocked", "cs:merged"],
        "description": (
            "scope: For each detected stuck item, assign disposition.\n"
            "changeset.root_branch: gh-194-data-taking-a-long-time\n"
            "changeset.parent_branch: gh-194-data-taking-a-long-time\n"
            "changeset.work_branch: gh-194-data-taking-a-long-time-at-wjj.4.2\n"
            "changeset.root_base: b5763f124f206c413b89a333dc02bf656b95481a\n"
            "changeset.parent_base: b5763f124f206c413b89a333dc02bf656b95481a\n"
            "notes:\n"
            "planner_relabel_2026-02-16: corrected child classification.\n"
            "implementation_2026-02-16:\n"
            "- publish/integration: pushed work branch + root branch to origin at "
            "67c7ca10898839106bbb9377e0ed0709fc7c0fbf.\n"
            "changeset.integrated_sha: "
            "67c7ca10898839106bbb9377e0ed0709fc7c0fbf\n"
            "blocked_at: 2026-02-16T20:51:57.364115+00:00 reason: missing integration signal "
            "for cs:merged\n"
        ),
    }

    with patch("atelier.commands.work.prs.read_github_pr_status", return_value=None):
        proven, sha = work_cmd._changeset_integration_signal(
            issue, repo_slug=None, repo_root=Path("/repo")
        )

    assert proven is True
    assert sha == "67c7ca10898839106bbb9377e0ed0709fc7c0fbf"


def test_integration_signal_reads_sha_from_issue_notes_field() -> None:
    issue = {
        "id": "at-wjj.4.3",
        "labels": ["at:changeset", "cs:merged"],
        "description": (
            "scope: Verify resolved items reached valid next-step states.\n"
            "changeset.root_branch: gh-194-data-taking-a-long-time\n"
            "changeset.parent_branch: gh-194-data-taking-a-long-time\n"
            "changeset.work_branch: gh-194-data-taking-a-long-time-at-wjj.4.3\n"
        ),
        "notes": (
            "implementation_2026-02-16:\n"
            "- publish/integration: pushed commit dd9fe6e403b7156bc1fa59eb0aaa14f036151e2a.\n"
            "changeset.integrated_sha: dd9fe6e403b7156bc1fa59eb0aaa14f036151e2a\n"
        ),
    }

    with patch("atelier.commands.work.prs.read_github_pr_status", return_value=None):
        proven, sha = work_cmd._changeset_integration_signal(
            issue, repo_slug=None, repo_root=Path("/repo")
        )

    assert proven is True
    assert sha == "dd9fe6e403b7156bc1fa59eb0aaa14f036151e2a"


def test_integration_signal_prefers_last_integrated_sha_entry() -> None:
    issue = {
        "id": "at-wjj.4.3",
        "labels": ["at:changeset", "cs:merged"],
        "description": (
            "changeset.root_branch: gh-194-data-taking-a-long-time\n"
            "changeset.parent_branch: gh-194-data-taking-a-long-time\n"
            "changeset.work_branch: gh-194-data-taking-a-long-time-at-wjj.4.3\n"
        ),
        "notes": (
            "changeset.integrated_sha: dd9fe6ec497565dbf2d4d6a8df8d76af7cb6f8d7\n"
            "correction_2026-02-16: canonical changeset.integrated_sha: "
            "dd9fe6e403b7156bc1fa59eb0aaa14f036151e2a\n"
        ),
    }

    with patch("atelier.commands.work.prs.read_github_pr_status", return_value=None):
        proven, sha = work_cmd._changeset_integration_signal(
            issue, repo_slug=None, repo_root=Path("/repo")
        )

    assert proven is True
    assert sha == "dd9fe6e403b7156bc1fa59eb0aaa14f036151e2a"


def test_resolve_epic_id_refreshes_issue_when_parent_missing_in_list_payload() -> None:
    listed = {"id": "at-wjj.4.3", "labels": ["at:changeset", "cs:merged"]}
    loaded_changeset = {
        "id": "at-wjj.4.3",
        "labels": ["at:changeset", "cs:merged"],
        "parent": "at-wjj",
    }
    loaded_epic = {"id": "at-wjj", "labels": ["at:epic"]}

    def fake_run_bd_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict]:
        if args[:2] == ["show", "at-wjj.4.3"]:
            return [loaded_changeset]
        if args[:2] == ["show", "at-wjj"]:
            return [loaded_epic]
        return []

    with patch("atelier.commands.work.beads.run_bd_json", side_effect=fake_run_bd_json):
        epic_id = work_cmd._resolve_epic_id_for_changeset(
            listed, beads_root=Path("/beads"), repo_root=Path("/repo")
        )

    assert epic_id == "at-wjj"


def test_list_reconcile_epic_candidates_groups_by_epic() -> None:
    merged_closed = {
        "id": "at-wjj.1",
        "status": "closed",
        "labels": ["at:changeset", "cs:merged"],
        "parent": "at-wjj",
    }
    merged_blocked = {
        "id": "at-wjj.2",
        "status": "blocked",
        "labels": ["at:changeset", "cs:blocked", "cs:merged"],
        "parent": "at-wjj",
    }

    def fake_run_bd_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict]:
        if args and args[0] == "list":
            return [merged_blocked, merged_closed]
        if args[:2] == ["show", "at-wjj"]:
            return [{"id": "at-wjj", "labels": ["at:epic"]}]
        return []

    with (
        patch("atelier.commands.work.beads.run_bd_json", side_effect=fake_run_bd_json),
        patch(
            "atelier.commands.work._changeset_integration_signal",
            return_value=(True, "dd9fe6e403b7156bc1fa59eb0aaa14f036151e2a"),
        ),
    ):
        candidates = work_cmd.list_reconcile_epic_candidates(
            project_config=_fake_project_payload(),
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
        )

    assert candidates == {"at-wjj": ["at-wjj.1", "at-wjj.2"]}


def test_list_reconcile_epic_candidates_skips_closed_epic_with_integrated_sha() -> None:
    merged_closed = {
        "id": "at-irs",
        "status": "closed",
        "labels": ["at:changeset", "cs:merged"],
        "description": "changeset.integrated_sha: 46628ab7c578d56b7003eb80fd13e44f151676d9\n",
    }
    closed_epic = {"id": "at-irs", "labels": ["at:epic"], "status": "closed"}

    def fake_run_bd_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict]:
        if args and args[0] == "list":
            return [merged_closed]
        if args[:2] == ["show", "at-irs"]:
            return [closed_epic]
        return []

    with (
        patch("atelier.commands.work.beads.run_bd_json", side_effect=fake_run_bd_json),
        patch(
            "atelier.commands.work._changeset_integration_signal",
            return_value=(True, "46628ab7c578d56b7003eb80fd13e44f151676d9"),
        ),
        patch(
            "atelier.commands.work._epic_root_integrated_into_parent",
            return_value=True,
        ),
    ):
        candidates = work_cmd.list_reconcile_epic_candidates(
            project_config=_fake_project_payload(),
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
        )

    assert candidates == {}


def test_list_reconcile_epic_candidates_keeps_closed_epic_when_not_finalized() -> None:
    merged_closed = {
        "id": "at-ati",
        "status": "closed",
        "labels": ["at:changeset", "cs:merged"],
        "description": "changeset.integrated_sha: cc013f53e9abf6e62a163d287364f87a66cf780f\n",
    }
    closed_epic = {"id": "at-ati", "labels": ["at:epic"], "status": "closed"}

    def fake_run_bd_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict]:
        if args and args[0] == "list":
            return [merged_closed]
        if args[:2] == ["show", "at-ati"]:
            return [closed_epic]
        return []

    with (
        patch("atelier.commands.work.beads.run_bd_json", side_effect=fake_run_bd_json),
        patch(
            "atelier.commands.work._changeset_integration_signal",
            return_value=(True, "cc013f53e9abf6e62a163d287364f87a66cf780f"),
        ),
        patch(
            "atelier.commands.work._epic_root_integrated_into_parent",
            return_value=False,
        ),
    ):
        candidates = work_cmd.list_reconcile_epic_candidates(
            project_config=_fake_project_payload(),
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
        )

    assert candidates == {"at-ati": ["at-ati"]}


def test_reconcile_blocked_merged_changesets_finalizes_actionable_issue() -> None:
    changeset = {
        "id": "at-wjj.4.3",
        "status": "blocked",
        "labels": ["at:changeset", "cs:blocked", "cs:merged"],
        "parent": "at-wjj",
    }
    epic = {
        "id": "at-wjj",
        "labels": ["at:epic"],
        "assignee": "atelier/worker/codex/p123-t456",
    }

    def fake_run_bd_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict]:
        if args and args[0] == "list":
            return [changeset]
        if args[:2] == ["show", "at-wjj"]:
            return [epic]
        return [changeset]

    with (
        patch("atelier.commands.work.beads.run_bd_json", side_effect=fake_run_bd_json),
        patch(
            "atelier.commands.work._changeset_integration_signal",
            return_value=(True, "dd9fe6e403b7156bc1fa59eb0aaa14f036151e2a"),
        ),
        patch(
            "atelier.commands.work.beads.find_agent_bead",
            return_value={"id": "agent-worker"},
        ),
        patch(
            "atelier.commands.work._finalize_changeset",
            return_value=work_cmd.FinalizeResult(
                continue_running=True, reason="changeset_complete"
            ),
        ) as finalize,
        patch(
            "atelier.commands.work.beads.update_changeset_integrated_sha"
        ) as update_sha,
    ):
        result = work_cmd.reconcile_blocked_merged_changesets(
            agent_id="atelier/worker/codex/p999-t111",
            agent_bead_id="agent-fallback",
            project_config=_fake_project_payload(),
            project_data_dir=Path("/project"),
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            git_path="git",
            dry_run=False,
        )

    assert result.scanned == 1
    assert result.actionable == 1
    assert result.reconciled == 1
    assert result.failed == 0
    finalize.assert_called_once()
    assert finalize.call_args.kwargs["epic_id"] == "at-wjj"
    assert finalize.call_args.kwargs["agent_bead_id"] == "agent-worker"
    update_sha.assert_called_once_with(
        "at-wjj.4.3",
        "dd9fe6e403b7156bc1fa59eb0aaa14f036151e2a",
        beads_root=Path("/beads"),
        cwd=Path("/repo"),
    )


def test_reconcile_blocked_merged_changesets_dry_run_skips_finalize() -> None:
    changeset = {
        "id": "at-wjj.4.3",
        "status": "blocked",
        "labels": ["at:changeset", "cs:blocked", "cs:merged"],
        "parent": "at-wjj",
    }

    def fake_run_bd_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict]:
        if args and args[0] == "list":
            return [changeset]
        if args[:2] == ["show", "at-wjj"]:
            return [{"id": "at-wjj", "labels": ["at:epic"], "assignee": None}]
        return [changeset]

    with (
        patch("atelier.commands.work.beads.run_bd_json", side_effect=fake_run_bd_json),
        patch(
            "atelier.commands.work._changeset_integration_signal",
            return_value=(True, "dd9fe6e403b7156bc1fa59eb0aaa14f036151e2a"),
        ),
        patch("atelier.commands.work._finalize_changeset") as finalize,
    ):
        result = work_cmd.reconcile_blocked_merged_changesets(
            agent_id="atelier/worker/codex/p999-t111",
            agent_bead_id="agent-fallback",
            project_config=_fake_project_payload(),
            project_data_dir=Path("/project"),
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            git_path="git",
            dry_run=True,
        )

    assert result.scanned == 1
    assert result.actionable == 1
    assert result.reconciled == 1
    assert result.failed == 0
    finalize.assert_not_called()


def test_reconcile_blocked_merged_changesets_logs_scan_and_result() -> None:
    changeset = {
        "id": "at-wjj.4.3",
        "status": "blocked",
        "labels": ["at:changeset", "cs:blocked", "cs:merged"],
        "parent": "at-wjj",
    }
    epic = {
        "id": "at-wjj",
        "labels": ["at:epic"],
        "assignee": None,
    }
    logs: list[str] = []

    def fake_run_bd_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict]:
        if args and args[0] == "list":
            return [changeset]
        if args[:2] == ["show", "at-wjj"]:
            return [epic]
        return [changeset]

    with (
        patch("atelier.commands.work.beads.run_bd_json", side_effect=fake_run_bd_json),
        patch(
            "atelier.commands.work._changeset_integration_signal",
            return_value=(True, "dd9fe6e403b7156bc1fa59eb0aaa14f036151e2a"),
        ),
        patch(
            "atelier.commands.work._finalize_changeset",
            return_value=work_cmd.FinalizeResult(
                continue_running=True, reason="changeset_complete"
            ),
        ),
        patch("atelier.commands.work.beads.update_changeset_integrated_sha"),
    ):
        work_cmd.reconcile_blocked_merged_changesets(
            agent_id="atelier/worker/codex/p999-t111",
            agent_bead_id="agent-fallback",
            project_config=_fake_project_payload(),
            project_data_dir=Path("/project"),
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            git_path="git",
            dry_run=False,
            log=logs.append,
        )

    assert any("reconcile scan: at-wjj.4.3" in line for line in logs)
    assert any("reconcile ok: at-wjj.4.3" in line for line in logs)


def test_reconcile_blocked_merged_changesets_treats_epic_blocked_finalization_as_error() -> (
    None
):
    changeset = {
        "id": "at-wjj.4.3",
        "status": "blocked",
        "labels": ["at:changeset", "cs:blocked", "cs:merged"],
        "parent": "at-wjj",
    }
    epic = {"id": "at-wjj", "labels": ["at:epic"], "assignee": None}
    logs: list[str] = []

    def fake_run_bd_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict]:
        if args and args[0] == "list":
            return [changeset]
        if args[:2] == ["show", "at-wjj"]:
            return [epic]
        return [changeset]

    with (
        patch("atelier.commands.work.beads.run_bd_json", side_effect=fake_run_bd_json),
        patch(
            "atelier.commands.work._changeset_integration_signal",
            return_value=(True, "dd9fe6e403b7156bc1fa59eb0aaa14f036151e2a"),
        ),
        patch(
            "atelier.commands.work._finalize_changeset",
            return_value=work_cmd.FinalizeResult(
                continue_running=False, reason="epic_blocked_finalization"
            ),
        ),
        patch("atelier.commands.work.beads.update_changeset_integrated_sha"),
    ):
        result = work_cmd.reconcile_blocked_merged_changesets(
            agent_id="atelier/worker/codex/p999-t111",
            agent_bead_id="agent-fallback",
            project_config=_fake_project_payload(),
            project_data_dir=Path("/project"),
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            git_path="git",
            dry_run=False,
            log=logs.append,
        )

    assert result.reconciled == 0
    assert result.failed == 1
    assert any("finalize reason=epic_blocked_finalization" in line for line in logs)


def test_reconcile_blocked_merged_changesets_honors_dependency_order() -> None:
    first = {
        "id": "at-a.1",
        "status": "blocked",
        "labels": ["at:changeset", "cs:blocked", "cs:merged"],
        "parent": "at-epic",
        "dependencies": [],
    }
    second = {
        "id": "at-a.2",
        "status": "blocked",
        "labels": ["at:changeset", "cs:blocked", "cs:merged"],
        "parent": "at-epic",
        "dependencies": ["at-a.1 (closed, cs:merged)"],
    }
    epic = {"id": "at-epic", "labels": ["at:epic"], "assignee": None}

    def fake_run_bd_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict]:
        if args and args[0] == "list":
            return [second, first]
        if args[:2] == ["show", "at-epic"]:
            return [epic]
        return []

    with (
        patch("atelier.commands.work.beads.run_bd_json", side_effect=fake_run_bd_json),
        patch(
            "atelier.commands.work._changeset_integration_signal",
            return_value=(True, "dd9fe6e403b7156bc1fa59eb0aaa14f036151e2a"),
        ),
        patch(
            "atelier.commands.work._finalize_changeset",
            return_value=work_cmd.FinalizeResult(
                continue_running=True, reason="changeset_complete"
            ),
        ) as finalize,
        patch("atelier.commands.work.beads.update_changeset_integrated_sha"),
    ):
        result = work_cmd.reconcile_blocked_merged_changesets(
            agent_id="atelier/worker/codex/p999-t111",
            agent_bead_id="agent-fallback",
            project_config=_fake_project_payload(),
            project_data_dir=Path("/project"),
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            git_path="git",
            dry_run=False,
        )

    assert result.actionable == 2
    assert result.reconciled == 2
    assert result.failed == 0
    assert [call.kwargs["changeset_id"] for call in finalize.call_args_list] == [
        "at-a.1",
        "at-a.2",
    ]


def test_reconcile_blocked_merged_changesets_changeset_filter_limits_scan_logs() -> (
    None
):
    included = {
        "id": "at-a.1",
        "status": "blocked",
        "labels": ["at:changeset", "cs:blocked", "cs:merged"],
        "parent": "at-epic",
        "dependencies": [],
    }
    excluded = {
        "id": "at-b.1",
        "status": "blocked",
        "labels": ["at:changeset", "cs:blocked", "cs:merged"],
        "parent": "at-epic",
        "dependencies": [],
    }
    epic = {"id": "at-epic", "labels": ["at:epic"], "assignee": None}
    logs: list[str] = []

    def fake_run_bd_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict]:
        if args and args[0] == "list":
            return [included, excluded]
        if args[:2] == ["show", "at-epic"]:
            return [epic]
        return []

    with (
        patch("atelier.commands.work.beads.run_bd_json", side_effect=fake_run_bd_json),
        patch(
            "atelier.commands.work._changeset_integration_signal",
            return_value=(True, "dd9fe6e403b7156bc1fa59eb0aaa14f036151e2a"),
        ),
        patch(
            "atelier.commands.work._finalize_changeset",
            return_value=work_cmd.FinalizeResult(
                continue_running=True, reason="changeset_complete"
            ),
        ) as finalize,
        patch("atelier.commands.work.beads.update_changeset_integrated_sha"),
    ):
        result = work_cmd.reconcile_blocked_merged_changesets(
            agent_id="atelier/worker/codex/p999-t111",
            agent_bead_id="agent-fallback",
            project_config=_fake_project_payload(),
            project_data_dir=Path("/project"),
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            git_path="git",
            changeset_filter={"at-a.1"},
            dry_run=False,
            log=logs.append,
        )

    assert result.scanned == 1
    assert result.actionable == 1
    assert result.reconciled == 1
    assert finalize.call_count == 1
    assert finalize.call_args.kwargs["changeset_id"] == "at-a.1"
    assert all("at-b.1" not in line for line in logs)


def test_reconcile_blocked_merged_changesets_blocks_on_unfinalized_dependency() -> None:
    candidate = {
        "id": "at-a.2",
        "status": "closed",
        "labels": ["at:changeset", "cs:merged"],
        "parent": "at-epic",
        "dependencies": ["at-z.1 (open, cs:in_progress)"],
    }
    epic = {"id": "at-epic", "labels": ["at:epic"], "assignee": None}
    dependency = {
        "id": "at-z.1",
        "status": "open",
        "labels": ["at:changeset", "cs:in_progress"],
    }

    def fake_run_bd_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict]:
        if args and args[0] == "list":
            return [candidate]
        if args[:2] == ["show", "at-epic"]:
            return [epic]
        if args[:2] == ["show", "at-z.1"]:
            return [dependency]
        return []

    logs: list[str] = []
    with (
        patch("atelier.commands.work.beads.run_bd_json", side_effect=fake_run_bd_json),
        patch(
            "atelier.commands.work._changeset_integration_signal",
            return_value=(True, "dd9fe6e403b7156bc1fa59eb0aaa14f036151e2a"),
        ),
        patch("atelier.commands.work._finalize_changeset") as finalize,
    ):
        result = work_cmd.reconcile_blocked_merged_changesets(
            agent_id="atelier/worker/codex/p999-t111",
            agent_bead_id="agent-fallback",
            project_config=_fake_project_payload(),
            project_data_dir=Path("/project"),
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            git_path="git",
            dry_run=False,
            log=logs.append,
        )

    assert result.actionable == 1
    assert result.reconciled == 0
    assert result.failed == 1
    finalize.assert_not_called()
    assert any("blocked by dependencies: at-z.1" in line for line in logs)


def test_finalize_epic_if_complete_closes_in_pr_mode() -> None:
    with (
        patch("atelier.commands.work._epic_ready_to_finalize", return_value=True),
        patch("atelier.commands.work.beads.close_epic_if_complete") as close_epic,
    ):
        result = work_cmd._finalize_epic_if_complete(
            epic_id="atelier-epic",
            agent_id="atelier/worker/agent",
            agent_bead_id="atelier-agent",
            branch_pr=True,
            branch_history="manual",
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
        )

    assert result.continue_running is True
    assert result.reason == "changeset_complete"
    close_epic.assert_called_once_with(
        "atelier-epic",
        "atelier-agent",
        beads_root=Path("/beads"),
        cwd=Path("/repo"),
    )


def test_finalize_epic_if_complete_integrates_non_pr() -> None:
    with (
        patch("atelier.commands.work._epic_ready_to_finalize", return_value=True),
        patch(
            "atelier.commands.work.beads.run_bd_json",
            return_value=[
                {
                    "id": "atelier-epic",
                    "labels": ["at:epic"],
                    "description": (
                        "workspace.root_branch: feat/root\n"
                        "workspace.parent_branch: main\n"
                    ),
                }
            ],
        ),
        patch(
            "atelier.commands.work.beads.update_workspace_parent_branch"
        ) as update_parent,
        patch(
            "atelier.commands.work._integrate_epic_root_to_parent",
            return_value=(True, "deadbeef", None),
        ) as integrate,
        patch("atelier.commands.work.beads.close_epic_if_complete") as close_epic,
    ):
        result = work_cmd._finalize_epic_if_complete(
            epic_id="atelier-epic",
            agent_id="atelier/worker/agent",
            agent_bead_id="atelier-agent",
            branch_pr=False,
            branch_history="rebase",
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            git_path="git",
        )

    assert result.continue_running is True
    assert result.reason == "changeset_complete"
    update_parent.assert_called_once_with(
        "atelier-epic",
        "main",
        beads_root=Path("/beads"),
        cwd=Path("/repo"),
        allow_override=True,
    )
    integrate.assert_called_once_with(
        epic_issue={
            "id": "atelier-epic",
            "labels": ["at:epic"],
            "description": (
                "workspace.root_branch: feat/root\nworkspace.parent_branch: main\n"
            ),
        },
        epic_id="atelier-epic",
        root_branch="feat/root",
        parent_branch="main",
        history="rebase",
        squash_message_mode="deterministic",
        squash_message_agent_spec=None,
        squash_message_agent_options=None,
        squash_message_agent_home=None,
        squash_message_agent_env=None,
        integration_cwd=Path("/repo"),
        repo_root=Path("/repo"),
        git_path="git",
    )
    close_epic.assert_called_once()


def test_resolve_epic_integration_cwd_prefers_epic_worktree_for_root_branch(
    tmp_path: Path,
) -> None:
    project_data_dir = tmp_path / "data"
    project_data_dir.mkdir(parents=True, exist_ok=True)
    epic_id = "atelier-epic"
    mapping_path = worktrees.mapping_path(project_data_dir, epic_id)
    mapping_path.parent.mkdir(parents=True, exist_ok=True)
    worktrees.write_mapping(
        mapping_path,
        worktrees.WorktreeMapping(
            epic_id=epic_id,
            worktree_path=f"worktrees/{epic_id}",
            root_branch="feat/root",
            changesets={},
            changeset_worktrees={},
        ),
    )
    epic_worktree = project_data_dir / "worktrees" / epic_id
    epic_worktree.mkdir(parents=True, exist_ok=True)
    (epic_worktree / ".git").write_text("gitdir: /tmp/epic", encoding="utf-8")

    with patch(
        "atelier.commands.work.git.git_current_branch", return_value="feat/root"
    ):
        selected = work_cmd._resolve_epic_integration_cwd(
            project_data_dir=project_data_dir,
            repo_root=Path("/repo"),
            epic_id=epic_id,
            root_branch="feat/root",
            git_path="git",
        )

    assert selected == epic_worktree


def test_integrate_epic_root_to_parent_rebase_uses_integration_worktree_branch() -> (
    None
):
    run_calls: list[tuple[list[str], Path]] = []

    def fake_is_ancestor(
        repo_root: Path, ancestor: str, descendant: str, *, git_path: str | None = None
    ) -> bool | None:
        if ancestor == "feat/root" and descendant == "main":
            return False
        if ancestor == "main" and descendant == "feat/root":
            return False
        return None

    def fake_rev_parse(
        repo_root: Path, ref: str, *, git_path: str | None = None
    ) -> str | None:
        if ref == "main":
            return "aaa111"
        if ref == "feat/root":
            return "bbb222"
        return None

    def fake_run_git_status(
        args: list[str],
        *,
        repo_root: Path,
        git_path: str | None = None,
        cwd: Path | None = None,
    ) -> tuple[bool, str]:
        run_calls.append((list(args), cwd or repo_root))
        return True, ""

    with (
        patch("atelier.commands.work._ensure_local_branch", return_value=True),
        patch("atelier.commands.work.git.git_is_clean", return_value=True),
        patch(
            "atelier.commands.work.git.git_is_ancestor", side_effect=fake_is_ancestor
        ),
        patch("atelier.commands.work.git.git_branch_fully_applied", return_value=False),
        patch("atelier.commands.work.git.git_rev_parse", side_effect=fake_rev_parse),
        patch("atelier.commands.work.git.git_current_branch", return_value="feat/root"),
        patch("atelier.commands.work._run_git_status", side_effect=fake_run_git_status),
    ):
        ok, sha, error = work_cmd._integrate_epic_root_to_parent(
            epic_issue={"id": "at-epic", "title": "Epic"},
            epic_id="at-epic",
            root_branch="feat/root",
            parent_branch="main",
            history="rebase",
            integration_cwd=Path("/worktrees/at-epic"),
            repo_root=Path("/repo"),
            git_path="git",
        )

    assert ok is True
    assert sha == "bbb222"
    assert error is None
    assert (["rebase", "main"], Path("/worktrees/at-epic")) in run_calls


def test_squash_subject_prefers_external_ticket_id() -> None:
    issue = {
        "id": "at-epic",
        "title": "Fix widget pipeline",
        "description": (
            'external_tickets: [{"provider":"github","ticket_id":"GH-194","relation":"primary"}]\n'
        ),
    }

    subject = work_cmd._squash_subject(issue, epic_id="at-epic")

    assert subject == "GH-194: Fix widget pipeline"


def test_parse_squash_subject_output_ignores_preamble_lines() -> None:
    output = "\n".join(
        [
            "OpenAI Codex v0.101.0",
            "thinking",
            "tokens used",
            "GH-194: tighten stuck-run ownership checks",
        ]
    )

    parsed = work_cmd._parse_squash_subject_output(output)

    assert parsed == "GH-194: tighten stuck-run ownership checks"


def test_integrate_epic_root_to_parent_merge_prefers_ff() -> None:
    run_calls: list[list[str]] = []

    def fake_is_ancestor(
        repo_root: Path, ancestor: str, descendant: str, *, git_path: str | None = None
    ) -> bool | None:
        if ancestor == "feat/root" and descendant == "main":
            return False
        if ancestor == "main" and descendant == "feat/root":
            return True
        return None

    def fake_rev_parse(
        repo_root: Path, ref: str, *, git_path: str | None = None
    ) -> str | None:
        if ref == "main":
            return "aaa111"
        if ref == "feat/root":
            return "bbb222"
        return None

    def fake_run_git_status(
        args: list[str],
        *,
        repo_root: Path,
        git_path: str | None = None,
        cwd: Path | None = None,
    ) -> tuple[bool, str]:
        run_calls.append(args)
        return True, ""

    with (
        patch("atelier.commands.work._ensure_local_branch", return_value=True),
        patch("atelier.commands.work.git.git_is_clean", return_value=True),
        patch(
            "atelier.commands.work.git.git_is_ancestor", side_effect=fake_is_ancestor
        ),
        patch("atelier.commands.work.git.git_branch_fully_applied", return_value=False),
        patch("atelier.commands.work.git.git_rev_parse", side_effect=fake_rev_parse),
        patch("atelier.commands.work._run_git_status", side_effect=fake_run_git_status),
    ):
        ok, sha, error = work_cmd._integrate_epic_root_to_parent(
            epic_issue={"id": "at-epic", "title": "Epic"},
            epic_id="at-epic",
            root_branch="feat/root",
            parent_branch="main",
            history="merge",
            repo_root=Path("/repo"),
            git_path="git",
        )

    assert ok is True
    assert sha == "aaa111"
    assert error is None
    assert ["update-ref", "refs/heads/main", "bbb222", "aaa111"] in run_calls
    assert ["push", "origin", "main"] in run_calls


def test_integrate_epic_root_to_parent_squash_uses_ticket_subject() -> None:
    run_calls: list[list[str]] = []

    def fake_is_ancestor(
        repo_root: Path, ancestor: str, descendant: str, *, git_path: str | None = None
    ) -> bool | None:
        return False

    def fake_rev_parse(
        repo_root: Path, ref: str, *, git_path: str | None = None
    ) -> str | None:
        if ref == "main":
            return "aaa111"
        if ref == "feat/root":
            return "bbb222"
        return "ccc333"

    def fake_run_git_status(
        args: list[str],
        *,
        repo_root: Path,
        git_path: str | None = None,
        cwd: Path | None = None,
    ) -> tuple[bool, str]:
        run_calls.append(args)
        return True, ""

    issue = {
        "id": "at-epic",
        "title": "Fix widget pipeline",
        "description": (
            'external_tickets: [{"provider":"github","ticket_id":"GH-194","relation":"primary"}]\n'
        ),
    }

    with (
        patch("atelier.commands.work._ensure_local_branch", return_value=True),
        patch("atelier.commands.work.git.git_is_clean", return_value=True),
        patch(
            "atelier.commands.work.git.git_is_ancestor", side_effect=fake_is_ancestor
        ),
        patch("atelier.commands.work.git.git_branch_fully_applied", return_value=False),
        patch("atelier.commands.work.git.git_current_branch", return_value="feat/root"),
        patch("atelier.commands.work.git.git_rev_parse", side_effect=fake_rev_parse),
        patch("atelier.commands.work._run_git_status", side_effect=fake_run_git_status),
    ):
        ok, _sha, error = work_cmd._integrate_epic_root_to_parent(
            epic_issue=issue,
            epic_id="at-epic",
            root_branch="feat/root",
            parent_branch="main",
            history="squash",
            repo_root=Path("/repo"),
            git_path="git",
        )

    assert ok is True
    assert error is None
    assert ["commit", "-m", "GH-194: Fix widget pipeline"] in run_calls


def test_integrate_epic_root_to_parent_squash_uses_agent_subject_when_enabled() -> None:
    run_calls: list[list[str]] = []

    def fake_is_ancestor(
        repo_root: Path, ancestor: str, descendant: str, *, git_path: str | None = None
    ) -> bool | None:
        return False

    def fake_rev_parse(
        repo_root: Path, ref: str, *, git_path: str | None = None
    ) -> str | None:
        if ref == "main":
            return "aaa111"
        if ref == "feat/root":
            return "bbb222"
        return "ccc333"

    def fake_run_git_status(
        args: list[str],
        *,
        repo_root: Path,
        git_path: str | None = None,
        cwd: Path | None = None,
    ) -> tuple[bool, str]:
        run_calls.append(args)
        return True, ""

    issue = {
        "id": "at-epic",
        "title": "Fix widget pipeline",
    }

    with (
        patch("atelier.commands.work._ensure_local_branch", return_value=True),
        patch("atelier.commands.work.git.git_is_clean", return_value=True),
        patch(
            "atelier.commands.work.git.git_is_ancestor", side_effect=fake_is_ancestor
        ),
        patch("atelier.commands.work.git.git_branch_fully_applied", return_value=False),
        patch("atelier.commands.work.git.git_current_branch", return_value="feat/root"),
        patch("atelier.commands.work.git.git_rev_parse", side_effect=fake_rev_parse),
        patch("atelier.commands.work._run_git_status", side_effect=fake_run_git_status),
        patch(
            "atelier.commands.work._agent_generated_squash_subject",
            return_value="Agent drafted squash subject",
        ) as draft_subject,
    ):
        ok, _sha, error = work_cmd._integrate_epic_root_to_parent(
            epic_issue=issue,
            epic_id="at-epic",
            root_branch="feat/root",
            parent_branch="main",
            history="squash",
            squash_message_mode="agent",
            repo_root=Path("/repo"),
            git_path="git",
        )

    assert ok is True
    assert error is None
    draft_subject.assert_called_once()
    assert ["commit", "-m", "Agent drafted squash subject"] in run_calls


def test_work_does_not_mark_in_progress_before_worktree_prepared() -> None:
    epics = [
        {
            "id": "atelier-epic",
            "title": "Epic",
            "status": "open",
            "labels": ["at:epic"],
        }
    ]
    changesets = [
        {
            "id": "atelier-epic.1",
            "title": "First changeset",
            "labels": ["at:changeset", "cs:ready"],
        }
    ]

    def fake_run_bd_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict]:
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
            patch(
                "atelier.commands.work.worktrees.ensure_git_worktree",
                side_effect=SystemExit(1),
            )
        )
        stack.enter_context(
            patch("atelier.commands.work.worktrees.ensure_changeset_checkout")
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
        stack.enter_context(patch("atelier.commands.work.say"))

        with pytest.raises(SystemExit):
            work_cmd.start_worker(
                SimpleNamespace(epic_id=None, mode="auto", run_mode="once")
            )

    assert not any(
        args[:2] == ["update", "atelier-epic.1"] and "cs:in_progress" in args
        for call in run_bd_command.call_args_list
        for args in [call.args[0]]
    )


def test_run_worker_once_stops_when_changeset_not_updated() -> None:
    epics = [
        {
            "id": "atelier-epic",
            "title": "Epic",
            "status": "open",
            "labels": ["at:epic"],
        }
    ]
    changesets = [
        {"id": "atelier-epic.1", "title": "First changeset", "labels": ["cs:ready"]}
    ]

    def fake_run_bd_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict]:
        if args[:2] == ["list", "--label"] and "at:message" in args:
            return []
        if args[:2] == ["show", "atelier-epic.1"]:
            return [
                {
                    "id": "atelier-epic.1",
                    "labels": ["at:changeset", "cs:in_progress"],
                }
            ]
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
        patch("atelier.commands.work.beads.create_message_bead"),
        patch(
            "atelier.commands.work.agent_home.resolve_agent_home", return_value=agent
        ),
        patch("atelier.commands.work.say"),
    ):
        summary = work_cmd._run_worker_once(
            SimpleNamespace(epic_id=None, mode="auto", run_mode="default"),
            mode="auto",
            dry_run=False,
            session_key="p1-t1",
        )

    assert summary.started is False
    assert summary.reason == "changeset_blocked_missing_metadata"


def test_finalize_keeps_parent_open_when_children_pending() -> None:
    run_commands: list[list[str]] = []

    with (
        patch(
            "atelier.commands.work.beads.run_bd_json",
            return_value=[
                {
                    "id": "atelier-epic.4",
                    "labels": ["at:changeset", "cs:merged"],
                    "status": "closed",
                }
            ],
        ),
        patch(
            "atelier.commands.work.beads.list_descendant_changesets",
            side_effect=lambda issue_id, **kwargs: (
                [{"id": "atelier-epic.4.1"}] if issue_id == "atelier-epic.4" else []
            ),
        ),
        patch(
            "atelier.commands.work.beads.run_bd_command",
            side_effect=lambda args, **kwargs: run_commands.append(list(args)),
        ),
        patch("atelier.commands.work.beads.close_epic_if_complete") as close_epic,
    ):
        result = work_cmd._finalize_changeset(
            changeset_id="atelier-epic.4",
            epic_id="atelier-epic",
            agent_id="atelier/worker/agent",
            agent_bead_id="atelier-agent",
            started_at=work_cmd.dt.datetime.now(tz=work_cmd.dt.timezone.utc),
            repo_slug=None,
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
        )

    assert result.continue_running is True
    assert result.reason == "changeset_children_pending"
    assert any(
        args[:2] == ["update", "atelier-epic.4"] and "--status" in args
        for args in run_commands
    )
    close_epic.assert_not_called()


def test_finalize_allows_in_progress_changeset_waiting_on_review() -> None:
    with (
        patch(
            "atelier.commands.work.beads.run_bd_json",
            return_value=[
                {
                    "id": "atelier-epic.1",
                    "labels": ["at:changeset", "cs:in_progress"],
                    "description": "pr_state: in-review\n",
                    "status": "in_progress",
                }
            ],
        ),
        patch("atelier.commands.work._find_invalid_changeset_labels", return_value=[]),
        patch("atelier.commands.work._has_blocking_messages", return_value=False),
    ):
        result = work_cmd._finalize_changeset(
            changeset_id="atelier-epic.1",
            epic_id="atelier-epic",
            agent_id="atelier/worker/agent",
            agent_bead_id="atelier-agent",
            started_at=work_cmd.dt.datetime.now(tz=work_cmd.dt.timezone.utc),
            repo_slug=None,
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
        )

    assert result.continue_running is True
    assert result.reason == "changeset_review_pending"


def test_finalize_prefers_live_merged_state_over_stale_review_metadata() -> None:
    run_commands: list[list[str]] = []

    with (
        patch(
            "atelier.commands.work.beads.run_bd_json",
            return_value=[
                {
                    "id": "atelier-epic.1",
                    "labels": ["at:changeset", "cs:in_progress"],
                    "description": (
                        "changeset.work_branch: feat/root-atelier-epic.1\n"
                        "pr_state: in-review\n"
                    ),
                    "status": "in_progress",
                }
            ],
        ),
        patch("atelier.commands.work._find_invalid_changeset_labels", return_value=[]),
        patch("atelier.commands.work._has_blocking_messages", return_value=False),
        patch("atelier.commands.work.git.git_ref_exists", return_value=True),
        patch(
            "atelier.commands.work.prs.read_github_pr_status",
            return_value={
                "number": 42,
                "url": "https://github.com/org/repo/pull/42",
                "state": "MERGED",
                "isDraft": False,
                "mergedAt": "2026-01-01T00:00:00Z",
            },
        ),
        patch(
            "atelier.commands.work.beads.run_bd_command",
            side_effect=lambda args, **kwargs: run_commands.append(list(args)),
        ),
        patch(
            "atelier.commands.work._finalize_epic_if_complete",
            return_value=work_cmd.FinalizeResult(
                continue_running=True, reason="changeset_complete"
            ),
        ),
    ):
        result = work_cmd._finalize_changeset(
            changeset_id="atelier-epic.1",
            epic_id="atelier-epic",
            agent_id="atelier/worker/agent",
            agent_bead_id="atelier-agent",
            started_at=work_cmd.dt.datetime.now(tz=work_cmd.dt.timezone.utc),
            repo_slug="org/repo",
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
        )

    assert result.continue_running is True
    assert result.reason == "changeset_complete"
    assert any(
        args[:2] == ["update", "atelier-epic.1"] and "cs:merged" in args
        for args in run_commands
    )


def test_finalize_prefers_live_closed_state_over_stale_review_metadata() -> None:
    run_commands: list[list[str]] = []

    with (
        patch(
            "atelier.commands.work.beads.run_bd_json",
            return_value=[
                {
                    "id": "atelier-epic.1",
                    "labels": ["at:changeset", "cs:in_progress"],
                    "description": (
                        "changeset.work_branch: feat/root-atelier-epic.1\n"
                        "pr_state: in-review\n"
                    ),
                    "status": "in_progress",
                }
            ],
        ),
        patch("atelier.commands.work._find_invalid_changeset_labels", return_value=[]),
        patch("atelier.commands.work._has_blocking_messages", return_value=False),
        patch("atelier.commands.work.git.git_ref_exists", return_value=True),
        patch(
            "atelier.commands.work.prs.read_github_pr_status",
            return_value={
                "number": 42,
                "url": "https://github.com/org/repo/pull/42",
                "state": "CLOSED",
                "isDraft": False,
                "mergedAt": None,
                "closedAt": "2026-01-01T00:00:00Z",
            },
        ),
        patch(
            "atelier.commands.work.beads.run_bd_command",
            side_effect=lambda args, **kwargs: run_commands.append(list(args)),
        ),
        patch(
            "atelier.commands.work._finalize_epic_if_complete",
            return_value=work_cmd.FinalizeResult(
                continue_running=True, reason="changeset_complete"
            ),
        ),
    ):
        result = work_cmd._finalize_changeset(
            changeset_id="atelier-epic.1",
            epic_id="atelier-epic",
            agent_id="atelier/worker/agent",
            agent_bead_id="atelier-agent",
            started_at=work_cmd.dt.datetime.now(tz=work_cmd.dt.timezone.utc),
            repo_slug="org/repo",
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
        )

    assert result.continue_running is True
    assert result.reason == "changeset_complete"
    assert any(
        args[:2] == ["update", "atelier-epic.1"] and "cs:abandoned" in args
        for args in run_commands
    )


def test_finalize_infers_review_pending_from_publish_signals() -> None:
    with (
        patch(
            "atelier.commands.work.beads.run_bd_json",
            return_value=[
                {
                    "id": "atelier-epic.1",
                    "labels": ["at:changeset", "cs:in_progress"],
                    "description": (
                        "changeset.work_branch: feat/root-atelier-epic.1\n"
                        "changeset.parent_branch: feat/root-atelier-epic.0\n"
                    ),
                    "status": "in_progress",
                }
            ],
        ),
        patch("atelier.commands.work._find_invalid_changeset_labels", return_value=[]),
        patch("atelier.commands.work._has_blocking_messages", return_value=False),
        patch("atelier.commands.work.git.git_ref_exists", return_value=True),
        patch("atelier.commands.work.prs.read_github_pr_status", return_value=None),
    ):
        result = work_cmd._finalize_changeset(
            changeset_id="atelier-epic.1",
            epic_id="atelier-epic",
            agent_id="atelier/worker/agent",
            agent_bead_id="atelier-agent",
            started_at=work_cmd.dt.datetime.now(tz=work_cmd.dt.timezone.utc),
            repo_slug="org/repo",
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            branch_pr=True,
            branch_pr_strategy="on-parent-approved",
        )

    assert result.continue_running is True
    assert result.reason == "changeset_review_pending"


def test_pr_creation_decision_treats_root_parent_as_no_parent() -> None:
    issue = {
        "id": "atelier-epic.1",
        "description": (
            "changeset.root_branch: feat/root\nchangeset.parent_branch: feat/root\n"
        ),
    }
    with (
        patch("atelier.commands.work.git.git_ref_exists", return_value=True),
        patch("atelier.commands.work.prs.read_github_pr_status", return_value=None),
    ):
        decision = work_cmd._changeset_pr_creation_decision(
            issue,
            repo_slug="org/repo",
            repo_root=Path("/repo"),
            git_path=None,
            branch_pr_strategy="sequential",
        )
    assert decision.allow_pr is True
    assert decision.reason == "no-parent"


def test_pr_creation_decision_uses_parent_when_distinct_from_root() -> None:
    issue = {
        "id": "atelier-epic.2",
        "description": (
            "changeset.root_branch: feat/root\nchangeset.parent_branch: feat/root-1\n"
        ),
    }
    with (
        patch("atelier.commands.work.git.git_ref_exists", return_value=True),
        patch("atelier.commands.work.prs.read_github_pr_status", return_value=None),
    ):
        decision = work_cmd._changeset_pr_creation_decision(
            issue,
            repo_slug="org/repo",
            repo_root=Path("/repo"),
            git_path=None,
            branch_pr_strategy="sequential",
        )
    assert decision.allow_pr is False
    assert decision.reason == "blocked:pushed"


def test_finalize_flags_missing_pr_when_strategy_allows_creation() -> None:
    with (
        patch(
            "atelier.commands.work.beads.run_bd_json",
            return_value=[
                {
                    "id": "atelier-epic.1",
                    "labels": ["at:changeset", "cs:ready"],
                    "description": "changeset.work_branch: feat/root-atelier-epic.1\n",
                    "status": "open",
                }
            ],
        ),
        patch("atelier.commands.work._find_invalid_changeset_labels", return_value=[]),
        patch("atelier.commands.work._has_blocking_messages", return_value=False),
        patch("atelier.commands.work.git.git_ref_exists", return_value=True),
        patch("atelier.commands.work.prs.read_github_pr_status", return_value=None),
        patch(
            "atelier.commands.work._attempt_create_draft_pr",
            return_value=(False, "gh auth failed"),
        ),
        patch("atelier.commands.work._mark_changeset_in_progress") as mark_in_progress,
        patch("atelier.commands.work._send_planner_notification") as notify,
        patch("atelier.commands.work.beads.run_bd_command") as run_bd_command,
    ):
        result = work_cmd._finalize_changeset(
            changeset_id="atelier-epic.1",
            epic_id="atelier-epic",
            agent_id="atelier/worker/agent",
            agent_bead_id="atelier-agent",
            started_at=work_cmd.dt.datetime.now(tz=work_cmd.dt.timezone.utc),
            repo_slug="org/repo",
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            branch_pr=True,
            branch_pr_strategy="sequential",
        )

    assert result.continue_running is False
    assert result.reason == "changeset_pr_create_failed"
    mark_in_progress.assert_called_once()
    notify.assert_called_once()
    assert "pr creation failed" in notify.call_args.kwargs["subject"].lower()
    assert "resolve `gh pr create` failure" in notify.call_args.kwargs["body"].lower()
    assert any(
        args[:2] == ["update", "atelier-epic.1"] and "--append-notes" in args
        for call in run_bd_command.call_args_list
        for args in [call.args[0]]
    )


def test_finalize_recovers_when_pr_appears_after_create_failure() -> None:
    with (
        patch(
            "atelier.commands.work.beads.run_bd_json",
            return_value=[
                {
                    "id": "atelier-epic.1",
                    "labels": ["at:changeset", "cs:ready"],
                    "description": "changeset.work_branch: feat/root-atelier-epic.1\n",
                    "status": "open",
                }
            ],
        ),
        patch("atelier.commands.work._find_invalid_changeset_labels", return_value=[]),
        patch("atelier.commands.work._has_blocking_messages", return_value=False),
        patch("atelier.commands.work.git.git_ref_exists", return_value=True),
        patch(
            "atelier.commands.work.prs.read_github_pr_status",
            side_effect=[
                None,
                None,
                {
                    "number": 42,
                    "url": "https://github.com/org/repo/pull/42",
                    "state": "OPEN",
                    "isDraft": True,
                    "reviewDecision": None,
                },
            ],
        ),
        patch(
            "atelier.commands.work._attempt_create_draft_pr",
            return_value=(False, "a pull request already exists"),
        ),
        patch("atelier.commands.work._mark_changeset_in_progress") as mark_in_progress,
        patch("atelier.commands.work._send_planner_notification") as notify,
        patch("atelier.commands.work.beads.update_changeset_review") as update_review,
    ):
        result = work_cmd._finalize_changeset(
            changeset_id="atelier-epic.1",
            epic_id="atelier-epic",
            agent_id="atelier/worker/agent",
            agent_bead_id="atelier-agent",
            started_at=work_cmd.dt.datetime.now(tz=work_cmd.dt.timezone.utc),
            repo_slug="org/repo",
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            branch_pr=True,
            branch_pr_strategy="sequential",
        )

    assert result.continue_running is True
    assert result.reason == "changeset_review_pending"
    update_review.assert_called_once()
    mark_in_progress.assert_not_called()
    notify.assert_not_called()


def test_finalize_in_progress_changeset_attempts_pr_creation_when_pushed() -> None:
    with (
        patch(
            "atelier.commands.work.beads.run_bd_json",
            return_value=[
                {
                    "id": "atelier-epic.1",
                    "title": "My changeset",
                    "labels": ["at:changeset", "cs:in_progress"],
                    "description": (
                        "changeset.work_branch: feat/root-atelier-epic.1\n"
                        "pr_state: pushed\n"
                    ),
                    "status": "open",
                }
            ],
        ),
        patch("atelier.commands.work._find_invalid_changeset_labels", return_value=[]),
        patch("atelier.commands.work._has_blocking_messages", return_value=False),
        patch(
            "atelier.commands.work._attempt_create_draft_pr",
            return_value=(False, "gh auth failed"),
        ) as create_pr,
        patch("atelier.commands.work.beads.run_bd_command"),
        patch("atelier.commands.work.git.git_ref_exists", return_value=True),
        patch("atelier.commands.work.prs.read_github_pr_status", return_value=None),
        patch("atelier.commands.work._mark_changeset_in_progress") as mark_in_progress,
        patch("atelier.commands.work._send_planner_notification") as notify,
    ):
        result = work_cmd._finalize_changeset(
            changeset_id="atelier-epic.1",
            epic_id="atelier-epic",
            agent_id="atelier/worker/agent",
            agent_bead_id="atelier-agent",
            started_at=work_cmd.dt.datetime.now(tz=work_cmd.dt.timezone.utc),
            repo_slug="org/repo",
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            branch_pr=True,
            branch_pr_strategy="sequential",
        )

    assert result.continue_running is False
    assert result.reason == "changeset_pr_create_failed"
    create_pr.assert_called_once()
    mark_in_progress.assert_called_once()
    notify.assert_called_once()


def test_finalize_flags_missing_pr_when_repo_slug_unavailable() -> None:
    with (
        patch(
            "atelier.commands.work.beads.run_bd_json",
            return_value=[
                {
                    "id": "atelier-epic.1",
                    "labels": ["at:changeset", "cs:ready"],
                    "description": (
                        "changeset.work_branch: feat/root-atelier-epic.1\n"
                        "changeset.parent_branch: main\n"
                    ),
                    "status": "open",
                }
            ],
        ),
        patch("atelier.commands.work._find_invalid_changeset_labels", return_value=[]),
        patch("atelier.commands.work._has_blocking_messages", return_value=False),
        patch("atelier.commands.work.git.git_ref_exists", return_value=True),
        patch("atelier.commands.work.beads.run_bd_command"),
        patch("atelier.commands.work._mark_changeset_in_progress") as mark_in_progress,
        patch("atelier.commands.work._send_planner_notification") as notify,
    ):
        result = work_cmd._finalize_changeset(
            changeset_id="atelier-epic.1",
            epic_id="atelier-epic",
            agent_id="atelier/worker/agent",
            agent_bead_id="atelier-agent",
            started_at=work_cmd.dt.datetime.now(tz=work_cmd.dt.timezone.utc),
            repo_slug=None,
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            branch_pr=True,
            branch_pr_strategy="sequential",
        )

    assert result.continue_running is False
    assert result.reason == "changeset_pr_missing_repo_slug"
    mark_in_progress.assert_called_once()
    notify.assert_called_once()
    assert "provider config missing" in notify.call_args.kwargs["subject"].lower()
    assert (
        "configure github provider metadata" in notify.call_args.kwargs["body"].lower()
    )


def test_finalize_creates_pr_when_missing_and_strategy_allows() -> None:
    with (
        patch(
            "atelier.commands.work.beads.run_bd_json",
            return_value=[
                {
                    "id": "atelier-epic.1",
                    "title": "My changeset",
                    "labels": ["at:changeset", "cs:ready"],
                    "description": (
                        "changeset.work_branch: feat/root-atelier-epic.1\n"
                        "changeset.parent_branch: main\n"
                    ),
                    "status": "open",
                }
            ],
        ),
        patch("atelier.commands.work._find_invalid_changeset_labels", return_value=[]),
        patch("atelier.commands.work._has_blocking_messages", return_value=False),
        patch("atelier.commands.work.git.git_ref_exists", return_value=True),
        patch(
            "atelier.commands.work.prs.read_github_pr_status",
            side_effect=[
                None,
                None,
                {
                    "number": 42,
                    "url": "https://github.com/org/repo/pull/42",
                    "state": "OPEN",
                    "isDraft": True,
                    "reviewDecision": None,
                },
            ],
        ),
        patch(
            "atelier.commands.work._attempt_create_draft_pr",
            return_value=(True, "created"),
        ),
        patch("atelier.commands.work.beads.update_changeset_review") as update_review,
    ):
        result = work_cmd._finalize_changeset(
            changeset_id="atelier-epic.1",
            epic_id="atelier-epic",
            agent_id="atelier/worker/agent",
            agent_bead_id="atelier-agent",
            started_at=work_cmd.dt.datetime.now(tz=work_cmd.dt.timezone.utc),
            repo_slug="org/repo",
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            branch_pr=True,
            branch_pr_strategy="sequential",
        )

    assert result.continue_running is True
    assert result.reason == "changeset_review_pending"
    update_review.assert_called_once()


@pytest.mark.parametrize(
    "strategy",
    ["sequential", "on-ready", "on-parent-approved", "parallel"],
)
def test_finalize_top_level_missing_pr_all_strategies_attempt_create(
    strategy: str,
) -> None:
    with (
        patch(
            "atelier.commands.work.beads.run_bd_json",
            return_value=[
                {
                    "id": "atelier-epic.1",
                    "title": "My changeset",
                    "labels": ["at:changeset", "cs:ready"],
                    "description": (
                        "changeset.work_branch: feat/root-atelier-epic.1\n"
                        "changeset.root_branch: feat/root\n"
                        "changeset.parent_branch: feat/root\n"
                    ),
                    "status": "open",
                }
            ],
        ),
        patch("atelier.commands.work._find_invalid_changeset_labels", return_value=[]),
        patch("atelier.commands.work._has_blocking_messages", return_value=False),
        patch("atelier.commands.work.git.git_ref_exists", return_value=True),
        patch("atelier.commands.work.prs.read_github_pr_status", return_value=None),
        patch(
            "atelier.commands.work._attempt_create_draft_pr",
            return_value=(False, "gh auth failed"),
        ) as create_pr,
        patch("atelier.commands.work._mark_changeset_in_progress"),
        patch("atelier.commands.work._send_planner_notification"),
        patch("atelier.commands.work.beads.run_bd_command"),
    ):
        result = work_cmd._finalize_changeset(
            changeset_id="atelier-epic.1",
            epic_id="atelier-epic",
            agent_id="atelier/worker/agent",
            agent_bead_id="atelier-agent",
            started_at=work_cmd.dt.datetime.now(tz=work_cmd.dt.timezone.utc),
            repo_slug="org/repo",
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            branch_pr=True,
            branch_pr_strategy=strategy,
        )

    assert result.continue_running is False
    assert result.reason == "changeset_pr_create_failed"
    create_pr.assert_called_once()


@pytest.mark.parametrize(
    ("strategy", "parent_payload", "expected_reason", "expects_create"),
    [
        (
            "sequential",
            {
                "state": "OPEN",
                "isDraft": False,
                "reviewDecision": None,
                "reviewRequests": [{"requestedReviewer": {"login": "alice"}}],
            },
            "changeset_review_pending",
            False,
        ),
        ("on-ready", None, "changeset_review_pending", False),
        (
            "on-parent-approved",
            {
                "state": "OPEN",
                "isDraft": False,
                "reviewDecision": "APPROVED",
            },
            "changeset_pr_create_failed",
            True,
        ),
        ("parallel", None, "changeset_pr_create_failed", True),
    ],
)
def test_finalize_child_pr_creation_respects_strategy_matrix(
    strategy: str,
    parent_payload: dict[str, object] | None,
    expected_reason: str,
    expects_create: bool,
) -> None:
    work_branch = "feat/root-atelier-epic.2"
    parent_branch = "feat/root-atelier-epic.1"

    def fake_read_github_pr_status(repo: str, head: str) -> dict[str, object] | None:
        if head == work_branch:
            return None
        if head == parent_branch:
            return parent_payload
        return None

    with (
        patch(
            "atelier.commands.work.beads.run_bd_json",
            return_value=[
                {
                    "id": "atelier-epic.2",
                    "title": "Child changeset",
                    "labels": ["at:changeset", "cs:ready"],
                    "description": (
                        f"changeset.work_branch: {work_branch}\n"
                        "changeset.root_branch: feat/root\n"
                        f"changeset.parent_branch: {parent_branch}\n"
                    ),
                    "status": "open",
                }
            ],
        ),
        patch("atelier.commands.work._find_invalid_changeset_labels", return_value=[]),
        patch("atelier.commands.work._has_blocking_messages", return_value=False),
        patch("atelier.commands.work.git.git_ref_exists", return_value=True),
        patch(
            "atelier.commands.work.prs.read_github_pr_status",
            side_effect=fake_read_github_pr_status,
        ),
        patch(
            "atelier.commands.work._attempt_create_draft_pr",
            return_value=(False, "gh auth failed"),
        ) as create_pr,
        patch("atelier.commands.work._mark_changeset_in_progress"),
        patch("atelier.commands.work._send_planner_notification"),
        patch("atelier.commands.work.beads.run_bd_command"),
    ):
        result = work_cmd._finalize_changeset(
            changeset_id="atelier-epic.2",
            epic_id="atelier-epic",
            agent_id="atelier/worker/agent",
            agent_bead_id="atelier-agent",
            started_at=work_cmd.dt.datetime.now(tz=work_cmd.dt.timezone.utc),
            repo_slug="org/repo",
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            branch_pr=True,
            branch_pr_strategy=strategy,
        )

    assert result.reason == expected_reason
    if expects_create:
        create_pr.assert_called_once()
    else:
        create_pr.assert_not_called()


def test_finalize_terminalizes_when_pr_is_merged() -> None:
    run_commands: list[list[str]] = []

    with (
        patch(
            "atelier.commands.work.beads.run_bd_json",
            return_value=[
                {
                    "id": "atelier-epic.1",
                    "labels": ["at:changeset", "cs:in_progress"],
                    "description": "changeset.work_branch: feat/root-atelier-epic.1\n",
                    "status": "in_progress",
                }
            ],
        ),
        patch("atelier.commands.work._find_invalid_changeset_labels", return_value=[]),
        patch("atelier.commands.work._has_blocking_messages", return_value=False),
        patch("atelier.commands.work.git.git_ref_exists", return_value=True),
        patch(
            "atelier.commands.work.prs.read_github_pr_status",
            return_value={
                "number": 42,
                "url": "https://github.com/org/repo/pull/42",
                "state": "MERGED",
                "isDraft": False,
                "mergedAt": "2026-01-01T00:00:00Z",
            },
        ),
        patch(
            "atelier.commands.work.beads.run_bd_command",
            side_effect=lambda args, **kwargs: run_commands.append(list(args)),
        ),
        patch(
            "atelier.commands.work._finalize_epic_if_complete",
            return_value=work_cmd.FinalizeResult(
                continue_running=True, reason="changeset_complete"
            ),
        ),
    ):
        result = work_cmd._finalize_changeset(
            changeset_id="atelier-epic.1",
            epic_id="atelier-epic",
            agent_id="atelier/worker/agent",
            agent_bead_id="atelier-agent",
            started_at=work_cmd.dt.datetime.now(tz=work_cmd.dt.timezone.utc),
            repo_slug="org/repo",
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            branch_pr=True,
        )

    assert result.continue_running is True
    assert result.reason == "changeset_complete"
    assert any(
        args[:2] == ["update", "atelier-epic.1"] and "cs:merged" in args
        for args in run_commands
    )


def test_finalize_terminalizes_closed_unmerged_pr_as_abandoned() -> None:
    run_commands: list[list[str]] = []

    with (
        patch(
            "atelier.commands.work.beads.run_bd_json",
            return_value=[
                {
                    "id": "atelier-epic.1",
                    "labels": ["at:changeset", "cs:in_progress"],
                    "description": "changeset.work_branch: feat/root-atelier-epic.1\n",
                    "status": "in_progress",
                }
            ],
        ),
        patch("atelier.commands.work._find_invalid_changeset_labels", return_value=[]),
        patch("atelier.commands.work._has_blocking_messages", return_value=False),
        patch("atelier.commands.work.git.git_ref_exists", return_value=True),
        patch(
            "atelier.commands.work.prs.read_github_pr_status",
            return_value={
                "number": 42,
                "url": "https://github.com/org/repo/pull/42",
                "state": "CLOSED",
                "isDraft": False,
                "mergedAt": None,
                "closedAt": "2026-01-01T00:00:00Z",
            },
        ),
        patch(
            "atelier.commands.work.beads.run_bd_command",
            side_effect=lambda args, **kwargs: run_commands.append(list(args)),
        ),
        patch(
            "atelier.commands.work._finalize_epic_if_complete",
            return_value=work_cmd.FinalizeResult(
                continue_running=True, reason="changeset_complete"
            ),
        ),
    ):
        result = work_cmd._finalize_changeset(
            changeset_id="atelier-epic.1",
            epic_id="atelier-epic",
            agent_id="atelier/worker/agent",
            agent_bead_id="atelier-agent",
            started_at=work_cmd.dt.datetime.now(tz=work_cmd.dt.timezone.utc),
            repo_slug="org/repo",
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            branch_pr=True,
        )

    assert result.continue_running is True
    assert result.reason == "changeset_complete"
    assert any(
        args[:2] == ["update", "atelier-epic.1"] and "cs:abandoned" in args
        for args in run_commands
    )


@pytest.mark.parametrize(
    "pr_payload",
    [
        {"state": "OPEN", "isDraft": True, "reviewDecision": None},
        {"state": "OPEN", "isDraft": False, "reviewDecision": None},
        {
            "state": "OPEN",
            "isDraft": False,
            "reviewDecision": None,
            "reviewRequests": [{"requestedReviewer": {"login": "alice"}}],
        },
        {"state": "OPEN", "isDraft": False, "reviewDecision": "APPROVED"},
    ],
)
def test_finalize_keeps_review_pending_for_non_terminal_pr_states(
    pr_payload: dict[str, object],
) -> None:
    with (
        patch(
            "atelier.commands.work.beads.run_bd_json",
            return_value=[
                {
                    "id": "atelier-epic.1",
                    "labels": ["at:changeset", "cs:in_progress"],
                    "description": "changeset.work_branch: feat/root-atelier-epic.1\n",
                    "status": "in_progress",
                }
            ],
        ),
        patch("atelier.commands.work._find_invalid_changeset_labels", return_value=[]),
        patch("atelier.commands.work._has_blocking_messages", return_value=False),
        patch("atelier.commands.work.git.git_ref_exists", return_value=True),
        patch(
            "atelier.commands.work.prs.read_github_pr_status",
            return_value=pr_payload,
        ),
    ):
        result = work_cmd._finalize_changeset(
            changeset_id="atelier-epic.1",
            epic_id="atelier-epic",
            agent_id="atelier/worker/agent",
            agent_bead_id="atelier-agent",
            started_at=work_cmd.dt.datetime.now(tz=work_cmd.dt.timezone.utc),
            repo_slug="org/repo",
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            branch_pr=True,
        )

    assert result.continue_running is True
    assert result.reason == "changeset_review_pending"


def test_finalize_accepts_pushed_without_pr_when_integration_is_proven() -> None:
    with (
        patch(
            "atelier.commands.work.beads.run_bd_json",
            return_value=[
                {
                    "id": "atelier-epic.1",
                    "labels": ["at:changeset", "cs:in_progress"],
                    "description": "changeset.work_branch: feat/root-atelier-epic.1\n",
                    "status": "in_progress",
                }
            ],
        ),
        patch("atelier.commands.work._find_invalid_changeset_labels", return_value=[]),
        patch("atelier.commands.work._has_blocking_messages", return_value=False),
        patch("atelier.commands.work.git.git_ref_exists", return_value=True),
        patch("atelier.commands.work.prs.read_github_pr_status", return_value=None),
        patch(
            "atelier.commands.work._changeset_integration_signal",
            return_value=(True, "abc123"),
        ),
        patch(
            "atelier.commands.work._finalize_epic_if_complete",
            return_value=work_cmd.FinalizeResult(
                continue_running=True, reason="changeset_complete"
            ),
        ),
        patch("atelier.commands.work.beads.run_bd_command"),
        patch(
            "atelier.commands.work.beads.update_changeset_integrated_sha"
        ) as update_sha,
        patch("atelier.commands.work._handle_pushed_without_pr") as handle_pushed,
    ):
        result = work_cmd._finalize_changeset(
            changeset_id="atelier-epic.1",
            epic_id="atelier-epic",
            agent_id="atelier/worker/agent",
            agent_bead_id="atelier-agent",
            started_at=work_cmd.dt.datetime.now(tz=work_cmd.dt.timezone.utc),
            repo_slug="org/repo",
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            branch_pr=True,
            branch_pr_strategy="sequential",
        )

    assert result.continue_running is True
    assert result.reason == "changeset_complete"
    update_sha.assert_called_once_with(
        "atelier-epic.1",
        "abc123",
        beads_root=Path("/beads"),
        cwd=Path("/repo"),
        allow_override=True,
    )
    handle_pushed.assert_not_called()


def test_finalize_requeues_publish_pending_when_local_state_exists() -> None:
    with (
        patch(
            "atelier.commands.work.beads.run_bd_json",
            return_value=[
                {
                    "id": "atelier-epic.1",
                    "labels": ["at:changeset"],
                    "description": "changeset.work_branch: feat/root-atelier-epic.1\n",
                    "status": "closed",
                }
            ],
        ),
        patch("atelier.commands.work._find_invalid_changeset_labels", return_value=[]),
        patch("atelier.commands.work._has_blocking_messages", return_value=False),
        patch("atelier.commands.work.git.git_ref_exists", return_value=False),
        patch("atelier.commands.work.prs.read_github_pr_status", return_value=None),
        patch(
            "atelier.commands.work._attempt_push_work_branch",
            return_value=(False, "push rejected by remote"),
        ),
        patch(
            "atelier.commands.work._collect_publish_signal_diagnostics",
            return_value=work_cmd._PublishSignalDiagnostics(
                local_branch_exists=True,
                remote_branch_exists=False,
                worktree_path=Path("/repo/worktrees/atelier-epic.1"),
                dirty_entries=(" M src/module.py",),
            ),
        ),
        patch("atelier.commands.work._mark_changeset_in_progress") as mark_in_progress,
        patch("atelier.commands.work._mark_changeset_blocked") as mark_blocked,
        patch("atelier.commands.work._send_planner_notification") as send_notification,
        patch("atelier.commands.work.beads.run_bd_command") as run_bd_command,
    ):
        result = work_cmd._finalize_changeset(
            changeset_id="atelier-epic.1",
            epic_id="atelier-epic",
            agent_id="atelier/worker/agent",
            agent_bead_id="atelier-agent",
            started_at=work_cmd.dt.datetime.now(tz=work_cmd.dt.timezone.utc),
            repo_slug="org/repo",
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            project_data_dir=Path("/project"),
            branch_pr=True,
        )

    assert result.continue_running is False
    assert result.reason == "changeset_publish_pending"
    mark_in_progress.assert_called_once()
    mark_blocked.assert_not_called()
    send_notification.assert_called_once()
    assert any(
        args[:2] == ["update", "atelier-epic.1"] and "--append-notes" in args
        for call in run_bd_command.call_args_list
        for args in [call.args[0]]
    )


def test_finalize_blocks_publish_missing_without_recoverable_state() -> None:
    with (
        patch(
            "atelier.commands.work.beads.run_bd_json",
            return_value=[
                {
                    "id": "atelier-epic.1",
                    "labels": ["at:changeset"],
                    "description": "changeset.work_branch: feat/root-atelier-epic.1\n",
                    "status": "in_progress",
                }
            ],
        ),
        patch("atelier.commands.work._find_invalid_changeset_labels", return_value=[]),
        patch("atelier.commands.work._has_blocking_messages", return_value=False),
        patch("atelier.commands.work.git.git_ref_exists", return_value=False),
        patch("atelier.commands.work.prs.read_github_pr_status", return_value=None),
        patch(
            "atelier.commands.work._attempt_push_work_branch",
            return_value=(False, "local branch missing: feat/root-atelier-epic.1"),
        ),
        patch(
            "atelier.commands.work._collect_publish_signal_diagnostics",
            return_value=work_cmd._PublishSignalDiagnostics(
                local_branch_exists=False,
                remote_branch_exists=False,
                worktree_path=None,
                dirty_entries=(),
            ),
        ),
        patch("atelier.commands.work._mark_changeset_in_progress") as mark_in_progress,
        patch("atelier.commands.work._mark_changeset_blocked") as mark_blocked,
        patch("atelier.commands.work._send_planner_notification") as send_notification,
    ):
        result = work_cmd._finalize_changeset(
            changeset_id="atelier-epic.1",
            epic_id="atelier-epic",
            agent_id="atelier/worker/agent",
            agent_bead_id="atelier-agent",
            started_at=work_cmd.dt.datetime.now(tz=work_cmd.dt.timezone.utc),
            repo_slug="org/repo",
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
            project_data_dir=Path("/project"),
            branch_pr=True,
        )

    assert result.continue_running is False
    assert result.reason == "changeset_blocked_publish_missing"
    mark_in_progress.assert_not_called()
    mark_blocked.assert_called_once()
    send_notification.assert_called_once()


def test_finalize_promotes_planned_descendants_when_unblocked() -> None:
    run_commands: list[list[str]] = []

    def fake_descendants(
        issue_id: str, *, beads_root: Path, cwd: Path, include_closed: bool = False
    ) -> list[dict[str, object]]:
        if issue_id == "atelier-epic.4":
            return [
                {
                    "id": "atelier-epic.4.1",
                    "labels": ["at:changeset", "cs:planned"],
                    "status": "open",
                }
            ]
        if issue_id == "atelier-epic":
            return [
                {
                    "id": "atelier-epic.4",
                    "labels": ["at:changeset", "cs:merged"],
                    "status": "open",
                },
                {
                    "id": "atelier-epic.4.1",
                    "labels": ["at:changeset", "cs:planned"],
                    "status": "open",
                },
            ]
        return []

    with (
        patch(
            "atelier.commands.work.beads.run_bd_json",
            side_effect=lambda args, **kwargs: (
                [{"id": "atelier-epic.4", "labels": ["at:changeset", "cs:merged"]}]
                if args[:2] == ["show", "atelier-epic.4"]
                else []
            ),
        ),
        patch(
            "atelier.commands.work.beads.list_descendant_changesets",
            side_effect=fake_descendants,
        ),
        patch(
            "atelier.commands.work.beads.run_bd_command",
            side_effect=lambda args, **kwargs: run_commands.append(list(args)),
        ),
    ):
        result = work_cmd._finalize_changeset(
            changeset_id="atelier-epic.4",
            epic_id="atelier-epic",
            agent_id="atelier/worker/agent",
            agent_bead_id="atelier-agent",
            started_at=work_cmd.dt.datetime.now(tz=work_cmd.dt.timezone.utc),
            repo_slug=None,
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
        )

    assert result.continue_running is True
    assert result.reason == "changeset_children_pending"
    assert any(
        args[:2] == ["update", "atelier-epic.4.1"] and "cs:ready" in args
        for args in run_commands
    )
    assert any(
        args[:2] == ["update", "atelier-epic.4"] and "--status" in args
        for args in run_commands
    )


def test_finalize_blocks_when_planned_descendants_need_planning() -> None:
    run_commands: list[list[str]] = []
    message_description = messages.render_message(
        {"thread": "atelier-epic.4.1"}, "Need planning details for subtask."
    )

    with (
        patch(
            "atelier.commands.work.beads.run_bd_json",
            side_effect=lambda args, **kwargs: (
                [{"id": "atelier-epic.4", "labels": ["at:changeset", "cs:merged"]}]
                if args[:2] == ["show", "atelier-epic.4"]
                else (
                    [
                        {
                            "id": "msg-1",
                            "description": message_description,
                            "created_at": "2999-01-01T00:00:00+00:00",
                        }
                    ]
                    if args[:2] == ["list", "--label"] and "at:message" in args
                    else []
                )
            ),
        ),
        patch(
            "atelier.commands.work.beads.list_descendant_changesets",
            side_effect=lambda issue_id, **kwargs: (
                [
                    {
                        "id": "atelier-epic.4.1",
                        "labels": ["at:changeset", "cs:planned"],
                        "status": "open",
                    }
                ]
                if issue_id == "atelier-epic.4"
                else []
            ),
        ),
        patch(
            "atelier.commands.work.beads.run_bd_command",
            side_effect=lambda args, **kwargs: run_commands.append(list(args)),
        ),
    ):
        result = work_cmd._finalize_changeset(
            changeset_id="atelier-epic.4",
            epic_id="atelier-epic",
            agent_id="atelier/worker/agent",
            agent_bead_id="atelier-agent",
            started_at=work_cmd.dt.datetime.now(tz=work_cmd.dt.timezone.utc),
            repo_slug=None,
            beads_root=Path("/beads"),
            repo_root=Path("/repo"),
        )

    assert result.continue_running is False
    assert result.reason == "changeset_children_planning_blocked"
    assert any(
        args[:2] == ["update", "atelier-epic.4"] and "--status" in args
        for args in run_commands
    )
    assert not any(
        args[:2] == ["update", "atelier-epic.4.1"] and "cs:ready" in args
        for args in run_commands
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
    changesets = [
        {
            "id": "atelier-epic.1",
            "title": "First changeset",
            "labels": ["at:changeset", "cs:ready"],
        }
    ]

    def fake_run_bd_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict]:
        if args[:3] == ["list", "--label", "at:message"]:
            return []
        if args[:2] == ["show", "atelier-epic"]:
            return [
                {
                    "id": "atelier-epic",
                    "labels": ["at:epic"],
                    "description": (
                        "workspace.root_branch: feat/root\n"
                        "workspace.parent_branch: main\n"
                    ),
                }
            ]
        if args[:2] == ["show", "atelier-epic.1"]:
            return [
                {
                    "id": "atelier-epic.1",
                    "labels": ["at:changeset", "cs:merged"],
                    "description": "changeset.integrated_sha: abc123\n",
                }
            ]
        if args[:3] == ["list", "--parent", "atelier-epic"]:
            return [{"id": "atelier-epic.1", "labels": ["at:changeset", "cs:merged"]}]
        if args[:3] == ["list", "--parent", "atelier-epic.1"]:
            return []
        if args[0] == "list" and "--parent" in args:
            parent_id = args[args.index("--parent") + 1]
            if parent_id == "atelier-epic":
                return [
                    {"id": "atelier-epic.1", "labels": ["at:changeset", "cs:merged"]}
                ]
            if parent_id == "atelier-epic.1":
                return []
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
            "atelier.commands.work._finalize_epic_if_complete",
            return_value=work_cmd.FinalizeResult(
                continue_running=True, reason="changeset_complete"
            ),
        ) as finalize_epic,
        patch(
            "atelier.commands.work.agent_home.resolve_agent_home", return_value=agent
        ),
        patch("atelier.commands.work.say"),
    ):
        work_cmd.start_worker(
            SimpleNamespace(epic_id=None, mode="auto", run_mode="once")
        )

    finalize_epic.assert_called_once()

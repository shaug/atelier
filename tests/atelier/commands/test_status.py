import io
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import atelier.config as config
from atelier.commands import status as status_cmd
from atelier.worktrees import WorktreeMapping
from tests.atelier.helpers import NORMALIZED_ORIGIN, RAW_ORIGIN, DummyResult


def test_status_json_summary() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        project_root = root / "project"
        repo_root = root / "repo"
        project_root.mkdir(parents=True, exist_ok=True)
        repo_root.mkdir(parents=True, exist_ok=True)

        config_payload = {
            "project": {
                "enlistment": str(repo_root),
                "origin": NORMALIZED_ORIGIN,
                "repo_url": RAW_ORIGIN,
            },
            "branch": {"prefix": "scott/", "pr": True, "history": "manual"},
        }
        project_config = config.ProjectConfig.model_validate(config_payload)

        epic_one = {
            "id": "epic-1",
            "title": "First epic",
            "status": "open",
            "assignee": "agent-1",
            "labels": ["at:epic", "workspace:alpha", "at:hooked"],
            "description": "workspace.root_branch: alpha\nworkspace.pr_strategy: sequential\n",
        }
        epic_two = {
            "id": "epic-2",
            "title": "Second epic",
            "status": "ready",
            "assignee": None,
            "labels": ["at:epic", "workspace:beta"],
        }
        agent_one = {
            "id": "agent-1",
            "title": "agent-1",
            "labels": ["at:agent"],
            "description": (
                "agent_id: agent-1\n"
                "hook_bead: epic-1\n"
                "heartbeat_at: 2026-02-01T00:00:00Z\n"
                "role: worker\n"
            ),
        }
        changesets = [
            {"id": "cs-1", "labels": ["at:changeset", "cs:merged"]},
            {"id": "cs-2", "labels": ["at:changeset"]},
            {"id": "cs-3", "labels": ["at:changeset", "cs:abandoned"]},
        ]

        def fake_run_bd_json(
            args: list[str], *, beads_root: Path, cwd: Path
        ) -> list[dict[str, object]]:
            if args[:3] == ["list", "--label", "at:epic"]:
                return [epic_one, epic_two]
            if args[:3] == ["list", "--label", "at:agent"]:
                return [agent_one]
            if args[:3] == ["list", "--label", "at:message"]:
                return []
            if args and args[0] == "list" and "--parent" in args:
                epic_id = args[args.index("--parent") + 1]
                if epic_id == "epic-1":
                    return list(changesets)
                return []
            if args and args[0] == "ready" and "--parent" in args:
                epic_id = args[args.index("--parent") + 1]
                if epic_id == "epic-1":
                    return [changesets[1]]
                return []
            return []

        def fake_load_mapping(path: Path) -> WorktreeMapping | None:
            if path.name == "epic-1.json":
                return WorktreeMapping(
                    epic_id="epic-1",
                    worktree_path="worktrees/epic-1",
                    root_branch="alpha",
                    changesets={},
                    changeset_worktrees={},
                )
            return None

        with (
            patch(
                "atelier.commands.status.resolve_current_project_with_repo_root",
                return_value=(project_root, project_config, str(repo_root), repo_root),
            ),
            patch(
                "atelier.commands.status.beads.run_bd_command",
                return_value=DummyResult(),
            ),
            patch(
                "atelier.commands.status.beads.run_bd_json",
                side_effect=fake_run_bd_json,
            ),
            patch(
                "atelier.commands.status.beads.get_agent_hook",
                return_value="epic-1",
            ),
            patch(
                "atelier.commands.status.worktrees.load_mapping",
                side_effect=fake_load_mapping,
            ),
        ):
            buffer = io.StringIO()
            with patch("sys.stdout", buffer):
                status_cmd(SimpleNamespace(format="json"))

        payload = json.loads(buffer.getvalue())
        assert payload["counts"]["epics"] == 2
        assert payload["counts"]["agents"] == 1
        assert payload["counts"]["ownership_policy_violations"] == 0
        assert payload["counts"]["queues"] == 0
        epic_payloads = {item["id"]: item for item in payload["epics"]}
        epic = epic_payloads["epic-1"]
        assert epic["root_branch"] == "alpha"
        assert epic["pr_strategy"] == "sequential"
        assert epic["hooked_by"] == ["agent-1"]
        assert epic["changesets"]["total"] == 3
        assert epic["changesets"]["ready"] == 1
        assert epic["changesets"]["merged"] == 1
        assert epic["changesets"]["abandoned"] == 1
        assert epic["worktree_relpath"] == "worktrees/epic-1"
        assert epic["ownership_policy_violation"] is False


def test_status_includes_changeset_signals() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        project_root = root / "project"
        repo_root = root / "repo"
        project_root.mkdir(parents=True, exist_ok=True)
        repo_root.mkdir(parents=True, exist_ok=True)

        config_payload = {
            "project": {
                "enlistment": str(repo_root),
                "origin": "github.com/org/repo",
            }
        }
        project_config = config.ProjectConfig.model_validate(config_payload)

        epic = {
            "id": "epic-1",
            "title": "Epic",
            "status": "open",
            "labels": ["at:epic"],
        }
        changesets = [{"id": "cs-1", "title": "Changeset", "labels": ["at:changeset"]}]

        def fake_run_bd_json(
            args: list[str], *, beads_root: Path, cwd: Path
        ) -> list[dict[str, object]]:
            if args[:3] == ["list", "--label", "at:epic"]:
                return [epic]
            if args[:3] == ["list", "--label", "at:agent"]:
                return []
            if args[:3] == ["list", "--label", "at:message"]:
                return []
            if args and args[0] == "list" and "--parent" in args:
                return list(changesets)
            if args and args[0] == "ready" and "--parent" in args:
                return []
            return []

        def fake_load_mapping(path: Path) -> WorktreeMapping | None:
            if path.name == "epic-1.json":
                return WorktreeMapping(
                    epic_id="epic-1",
                    worktree_path="worktrees/epic-1",
                    root_branch="alpha",
                    changesets={"cs-1": "alpha-cs-1"},
                    changeset_worktrees={},
                )
            return None

        pr_payload = {"state": "OPEN", "isDraft": True, "mergeStateStatus": "DIRTY"}

        with (
            patch(
                "atelier.commands.status.resolve_current_project_with_repo_root",
                return_value=(project_root, project_config, str(repo_root), repo_root),
            ),
            patch(
                "atelier.commands.status.beads.run_bd_command",
                return_value=DummyResult(),
            ),
            patch(
                "atelier.commands.status.beads.run_bd_json",
                side_effect=fake_run_bd_json,
            ),
            patch(
                "atelier.commands.status.worktrees.load_mapping",
                side_effect=fake_load_mapping,
            ),
            patch(
                "atelier.commands.status.git.git_ref_exists",
                return_value=True,
            ),
            patch(
                "atelier.commands.status.prs.read_github_pr_status",
                return_value=pr_payload,
            ),
        ):
            buffer = io.StringIO()
            with patch("sys.stdout", buffer):
                status_cmd(SimpleNamespace(format="json"))

        payload = json.loads(buffer.getvalue())
        epic_payload = payload["epics"][0]
        details = epic_payload["changeset_details"]
        assert details[0]["branch"] == "alpha-cs-1"
        assert details[0]["lifecycle_state"] == "draft-pr"
        assert details[0]["merge_conflict"] is True
        assert details[0]["pr_allowed"] is True
        assert details[0]["pr_gate_reason"] == "no-parent"
        assert details[0]["pr"]["merge_state_status"] == "DIRTY"


def test_status_resolves_dependency_lineage_for_sequential_gate() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        project_root = root / "project"
        repo_root = root / "repo"
        project_root.mkdir(parents=True, exist_ok=True)
        repo_root.mkdir(parents=True, exist_ok=True)

        project_config = config.ProjectConfig.model_validate(
            {"project": {"enlistment": str(repo_root), "origin": "github.com/org/repo"}}
        )
        epic = {
            "id": "epic-1",
            "title": "Epic",
            "status": "open",
            "labels": ["at:epic"],
            "description": "workspace.pr_strategy: sequential\n",
        }
        changesets = [
            {
                "id": "cs-1",
                "title": "Parent",
                "labels": ["at:changeset"],
                "description": "changeset.work_branch: alpha-cs-1\n",
            },
            {
                "id": "cs-2",
                "title": "Child",
                "labels": ["at:changeset"],
                "description": (
                    "changeset.root_branch: alpha\n"
                    "changeset.parent_branch: alpha\n"
                    "changeset.work_branch: alpha-cs-2\n"
                ),
                "dependencies": ["cs-1"],
            },
        ]

        def fake_run_bd_json(
            args: list[str], *, beads_root: Path, cwd: Path
        ) -> list[dict[str, object]]:
            if args[:3] == ["list", "--label", "at:epic"]:
                return [epic]
            if args[:3] == ["list", "--label", "at:agent"]:
                return []
            if args[:3] == ["list", "--label", "at:message"]:
                return []
            if args and args[0] == "list" and "--parent" in args:
                return list(changesets)
            if args and args[0] == "ready" and "--parent" in args:
                return []
            return []

        def fake_load_mapping(path: Path) -> WorktreeMapping | None:
            if path.name == "epic-1.json":
                return WorktreeMapping(
                    epic_id="epic-1",
                    worktree_path="worktrees/epic-1",
                    root_branch="alpha",
                    changesets={"cs-1": "alpha-cs-1", "cs-2": "alpha-cs-2"},
                    changeset_worktrees={},
                )
            return None

        def fake_pr_payload(_repo_slug: str, branch: str) -> dict[str, object] | None:
            if branch == "alpha-cs-1":
                return {"state": "OPEN", "isDraft": False}
            if branch == "alpha-cs-2":
                return {"state": "OPEN", "isDraft": True}
            return None

        with (
            patch(
                "atelier.commands.status.resolve_current_project_with_repo_root",
                return_value=(project_root, project_config, str(repo_root), repo_root),
            ),
            patch(
                "atelier.commands.status.beads.run_bd_command",
                return_value=DummyResult(),
            ),
            patch(
                "atelier.commands.status.beads.run_bd_json",
                side_effect=fake_run_bd_json,
            ),
            patch(
                "atelier.commands.status.worktrees.load_mapping",
                side_effect=fake_load_mapping,
            ),
            patch(
                "atelier.commands.status.git.git_ref_exists",
                return_value=True,
            ),
            patch(
                "atelier.commands.status.prs.read_github_pr_status",
                side_effect=fake_pr_payload,
            ),
        ):
            buffer = io.StringIO()
            with patch("sys.stdout", buffer):
                status_cmd(SimpleNamespace(format="json"))

        payload = json.loads(buffer.getvalue())
        details = payload["epics"][0]["changeset_details"]
        by_id = {detail["id"]: detail for detail in details}
        assert by_id["cs-2"]["pr_allowed"] is False
        assert by_id["cs-2"]["pr_gate_reason"] == "blocked:pr-open"


def test_status_marks_stale_sessions_and_reclaimable_epics() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        project_root = root / "project"
        repo_root = root / "repo"
        project_root.mkdir(parents=True, exist_ok=True)
        repo_root.mkdir(parents=True, exist_ok=True)

        project_config = config.ProjectConfig.model_validate(
            {
                "project": {
                    "enlistment": str(repo_root),
                    "origin": NORMALIZED_ORIGIN,
                    "repo_url": RAW_ORIGIN,
                }
            }
        )
        epic = {
            "id": "epic-stale",
            "title": "Stale epic",
            "status": "hooked",
            "assignee": "atelier/worker/codex/p424242-t1",
            "labels": ["at:epic", "at:hooked"],
        }
        agent = {
            "id": "agent-stale",
            "title": "atelier/worker/codex/p424242-t1",
            "labels": ["at:agent"],
            "description": (
                "agent_id: atelier/worker/codex/p424242-t1\nhook_bead: epic-stale\nrole: worker\n"
            ),
        }

        def fake_run_bd_json(
            args: list[str], *, beads_root: Path, cwd: Path
        ) -> list[dict[str, object]]:
            if args[:3] == ["list", "--label", "at:epic"]:
                return [epic]
            if args[:3] == ["list", "--label", "at:agent"]:
                return [agent]
            if args[:3] == ["list", "--label", "at:message"]:
                return []
            if args and args[0] == "list" and "--parent" in args:
                return []
            if args and args[0] == "ready" and "--parent" in args:
                return []
            return []

        with (
            patch(
                "atelier.commands.status.resolve_current_project_with_repo_root",
                return_value=(project_root, project_config, str(repo_root), repo_root),
            ),
            patch(
                "atelier.commands.status.beads.run_bd_command",
                return_value=DummyResult(),
            ),
            patch(
                "atelier.commands.status.beads.run_bd_json",
                side_effect=fake_run_bd_json,
            ),
            patch(
                "atelier.commands.status.beads.get_agent_hook",
                return_value="epic-stale",
            ),
            patch("atelier.commands.status.os.kill", side_effect=ProcessLookupError),
        ):
            buffer = io.StringIO()
            with patch("sys.stdout", buffer):
                status_cmd(SimpleNamespace(format="json"))

        payload = json.loads(buffer.getvalue())
        assert payload["counts"]["agents_stale"] == 1
        assert payload["counts"]["epics_reclaimable"] == 1
        agent_payload = payload["agents"][0]
        assert agent_payload["session_pid"] == 424242
        assert agent_payload["session_state"] == "stale"
        assert agent_payload["reclaimable"] is True
        epic_payload = payload["epics"][0]
        assert epic_payload["assignee_session_state"] == "stale"
        assert epic_payload["reclaimable"] is True


def test_status_flags_planner_owned_executable_epic() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        project_root = root / "project"
        repo_root = root / "repo"
        project_root.mkdir(parents=True, exist_ok=True)
        repo_root.mkdir(parents=True, exist_ok=True)

        project_config = config.ProjectConfig.model_validate(
            {"project": {"enlistment": str(repo_root), "origin": NORMALIZED_ORIGIN}}
        )
        epic = {
            "id": "epic-violation",
            "title": "Planner-owned",
            "status": "in_progress",
            "assignee": "atelier/planner/codex/p8",
            "labels": ["at:epic", "at:changeset"],
        }

        def fake_run_bd_json(
            args: list[str], *, beads_root: Path, cwd: Path
        ) -> list[dict[str, object]]:
            if args[:3] == ["list", "--label", "at:epic"]:
                return [epic]
            if args[:3] == ["list", "--label", "at:agent"]:
                return []
            if args[:3] == ["list", "--label", "at:message"]:
                return []
            if args and args[0] in {"list", "ready"} and "--parent" in args:
                return []
            return []

        with (
            patch(
                "atelier.commands.status.resolve_current_project_with_repo_root",
                return_value=(project_root, project_config, str(repo_root), repo_root),
            ),
            patch(
                "atelier.commands.status.beads.run_bd_command",
                return_value=DummyResult(),
            ),
            patch(
                "atelier.commands.status.beads.run_bd_json",
                side_effect=fake_run_bd_json,
            ),
        ):
            buffer = io.StringIO()
            with patch("sys.stdout", buffer):
                status_cmd(SimpleNamespace(format="json"))

        payload = json.loads(buffer.getvalue())
        assert payload["counts"]["ownership_policy_violations"] == 1
        epic_payload = payload["epics"][0]
        assert epic_payload["ownership_policy_violation"] is True
        assert epic_payload["ownership_policy_reason"] == "planner-owned executable work"

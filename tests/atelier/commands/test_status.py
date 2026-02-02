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
            "description": "workspace.root_branch: alpha\n",
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
        assert payload["counts"]["queues"] == 0
        epic_payloads = {item["id"]: item for item in payload["epics"]}
        epic = epic_payloads["epic-1"]
        assert epic["root_branch"] == "alpha"
        assert epic["hooked_by"] == ["agent-1"]
        assert epic["changesets"]["total"] == 3
        assert epic["changesets"]["ready"] == 1
        assert epic["changesets"]["merged"] == 1
        assert epic["changesets"]["abandoned"] == 1
        assert epic["worktree_relpath"] == "worktrees/epic-1"

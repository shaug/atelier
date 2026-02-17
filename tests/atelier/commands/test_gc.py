import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import atelier.commands.gc as gc_cmd
import atelier.config as config
from atelier.messages import render_message


def test_gc_closes_expired_channel_messages() -> None:
    project_root = Path("/project")
    repo_root = Path("/repo")
    project_config = config.ProjectConfig()
    description = render_message(
        {"channel": "ops", "retention_days": 1},
        "hello",
    )
    issue = {
        "id": "msg-1",
        "description": description,
        "created_at": "2026-01-01T00:00:00Z",
    }

    calls: list[list[str]] = []

    def fake_run_bd_json(
        args: list[str], *, beads_root: Path, cwd: Path
    ) -> list[dict[str, object]]:
        if args[:3] == ["list", "--label", "at:message"]:
            return [issue]
        return []

    def fake_run_bd_command(
        args: list[str], *, beads_root: Path, cwd: Path, allow_failure: bool = False
    ) -> object:
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    with (
        patch(
            "atelier.commands.gc.resolve_current_project_with_repo_root",
            return_value=(project_root, project_config, "/repo", repo_root),
        ),
        patch(
            "atelier.commands.gc.config.resolve_project_data_dir",
            return_value=Path("/data"),
        ),
        patch(
            "atelier.commands.gc.config.resolve_beads_root",
            return_value=Path("/beads"),
        ),
        patch("atelier.commands.gc.beads.run_bd_json", side_effect=fake_run_bd_json),
        patch(
            "atelier.commands.gc.beads.run_bd_command", side_effect=fake_run_bd_command
        ),
        patch("atelier.commands.gc.say"),
    ):
        gc_cmd.gc(SimpleNamespace(stale_hours=24.0, dry_run=False, yes=True))

    assert any(cmd[:2] == ["close", "msg-1"] for cmd in calls)


def test_gc_removes_stale_session_agent_home() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        project_root = root / "project"
        repo_root = root / "repo"
        data_dir = root / "data"
        project_root.mkdir(parents=True, exist_ok=True)
        repo_root.mkdir(parents=True, exist_ok=True)
        stale_home = data_dir / "agents" / "worker" / "codex" / "p4242-t1"
        stale_home.mkdir(parents=True, exist_ok=True)
        (stale_home / "AGENTS.md").write_text("x", encoding="utf-8")
        project_config = config.ProjectConfig()
        agent_issue = {
            "id": "agent-1",
            "title": "atelier/worker/codex/p4242-t1",
            "labels": ["at:agent"],
            "description": "agent_id: atelier/worker/codex/p4242-t1\nrole_type: worker\n",
        }

        def fake_run_bd_json(
            args: list[str], *, beads_root: Path, cwd: Path
        ) -> list[dict[str, object]]:
            if args[:3] == ["list", "--label", "at:agent"]:
                return [agent_issue]
            if args[:3] == ["list", "--label", "at:epic"]:
                return []
            if args[:3] == ["list", "--label", "at:message"]:
                return []
            return []

        with (
            patch(
                "atelier.commands.gc.resolve_current_project_with_repo_root",
                return_value=(project_root, project_config, "/repo", repo_root),
            ),
            patch(
                "atelier.commands.gc.config.resolve_project_data_dir",
                return_value=data_dir,
            ),
            patch(
                "atelier.commands.gc.config.resolve_beads_root",
                return_value=Path("/beads"),
            ),
            patch(
                "atelier.commands.gc.beads.run_bd_json", side_effect=fake_run_bd_json
            ),
            patch("atelier.commands.gc.beads.run_bd_command"),
            patch("atelier.commands.gc.beads.get_agent_hook", return_value=None),
            patch(
                "atelier.commands.gc.agent_home.is_session_agent_active",
                return_value=False,
            ),
            patch("atelier.commands.gc.say"),
        ):
            gc_cmd.gc(SimpleNamespace(stale_hours=24.0, dry_run=False, yes=True))

        assert not stale_home.exists()


def test_gc_reconcile_flag_runs_changeset_reconciliation() -> None:
    project_root = Path("/project")
    repo_root = Path("/repo")
    project_config = config.ProjectConfig()

    with (
        patch(
            "atelier.commands.gc.resolve_current_project_with_repo_root",
            return_value=(project_root, project_config, "/repo", repo_root),
        ),
        patch(
            "atelier.commands.gc.config.resolve_project_data_dir",
            return_value=Path("/data"),
        ),
        patch(
            "atelier.commands.gc.config.resolve_beads_root",
            return_value=Path("/beads"),
        ),
        patch("atelier.commands.gc.beads.run_bd_json", return_value=[]),
        patch(
            "atelier.commands.gc.work_cmd.reconcile_blocked_merged_changesets",
            return_value=gc_cmd.work_cmd.ReconcileResult(
                scanned=2, actionable=1, reconciled=1, failed=0
            ),
        ) as reconcile,
        patch("atelier.commands.gc.say") as say,
    ):
        gc_cmd.gc(
            SimpleNamespace(
                stale_hours=24.0,
                stale_if_missing_heartbeat=False,
                dry_run=False,
                reconcile=True,
                yes=True,
            )
        )

    reconcile.assert_called_once()
    assert any(
        "Reconcile blocked changesets: scanned=2, actionable=1, reconciled=1, failed=0"
        in str(call.args[0])
        for call in say.call_args_list
    )

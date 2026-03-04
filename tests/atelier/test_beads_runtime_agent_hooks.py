"""Tests for beads_runtime.agent_hooks via beads facade with exec patching."""

from __future__ import annotations

from pathlib import Path

import pytest

from atelier import beads

from . import bd_mock


def test_get_agent_hook_backfills_slot_from_description(tmp_path: Path) -> None:
    beads_root = tmp_path / ".beads"
    beads_root.mkdir()
    cwd = tmp_path / "repo"
    cwd.mkdir()

    mock = bd_mock.mock_bd_run_with_runner(
        show_responses={
            "agent-1": {"id": "agent-1", "description": "hook_bead: epic-2\n"},
        },
        slot_hooks={},
    )

    with pytest.MonkeyPatch.context() as m:
        m.setattr("atelier.beads.exec.run_with_runner", mock)

        hook = beads.get_agent_hook(
            "agent-1",
            beads_root=beads_root,
            cwd=cwd,
        )

    assert hook == "epic-2"


def test_claim_epic_backfills_epic_label_for_standalone_changeset(tmp_path: Path) -> None:
    beads_root = tmp_path / ".beads"
    beads_root.mkdir()
    cwd = tmp_path / "repo"
    cwd.mkdir()

    epic = {
        "id": "epic-1",
        "status": "open",
        "labels": [],
        "assignee": None,
        "type": "task",
    }
    claimed = {
        "id": "epic-1",
        "status": "in_progress",
        "labels": ["at:epic", "at:hooked"],
        "assignee": "agent",
        "type": "task",
    }

    show_calls: list[str] = []

    def mock_with_retries(request: object, **kwargs: object) -> object:
        from atelier import exec as exec_util

        argv = list(getattr(request, "argv", ()))
        if not argv or argv[0] != "bd":
            return None

        if len(argv) >= 4 and argv[1:4] == ["dolt", "show", "--json"]:
            return bd_mock.bd_dolt_show_result(connection_ok=True)

        if len(argv) >= 3 and argv[1] == "show" and "--json" in argv:
            issue_id = argv[2] if argv[2] != "--json" else (argv[3] if len(argv) > 3 else "")
            show_calls.append(issue_id)
            if len(show_calls) == 1:
                return bd_mock.bd_show_result(epic)
            return bd_mock.bd_show_result(claimed)

        if len(argv) >= 4 and argv[1:3] == ["list", "--parent"]:
            return bd_mock.bd_list_parent_result([])

        if len(argv) >= 2 and argv[1] in ("slot", "update"):
            return exec_util.CommandResult(
                argv=tuple(argv),
                returncode=0,
                stdout="",
                stderr="",
            )

        return exec_util.CommandResult(argv=tuple(argv), returncode=0, stdout="[]\n", stderr="")

    with pytest.MonkeyPatch.context() as m:
        m.setattr("atelier.beads.exec.run_with_runner", mock_with_retries)

        result = beads.claim_epic(
            "epic-1",
            "agent",
            beads_root=beads_root,
            cwd=cwd,
        )

    assert result is not None
    labels = list(result.get("labels") or [])
    assert "at:hooked" in labels
    assert "at:epic" in labels


def test_claim_epic_rejects_planner_owned_executable_work(tmp_path: Path) -> None:
    beads_root = tmp_path / ".beads"
    beads_root.mkdir()
    cwd = tmp_path / "repo"
    cwd.mkdir()

    epic = {
        "id": "epic-1",
        "status": "open",
        "labels": ["at:epic"],
        "assignee": "atelier/planner/codex/p111",
    }

    mock = bd_mock.mock_bd_run_with_runner(
        show_responses={"epic-1": epic},
        list_parent_responses={"epic-1": []},
    )

    with pytest.MonkeyPatch.context() as m:
        m.setattr("atelier.beads.exec.run_with_runner", mock)
        m.setattr("atelier.beads.die", lambda msg, code=1: (_ for _ in ()).throw(RuntimeError(msg)))

        with pytest.raises(RuntimeError, match="planner agents cannot own executable work"):
            beads.claim_epic(
                "epic-1",
                "atelier/worker/codex/p222",
                beads_root=beads_root,
                cwd=cwd,
            )


def test_set_agent_hook_updates_slot_and_description(tmp_path: Path) -> None:
    beads_root = tmp_path / ".beads"
    beads_root.mkdir()
    cwd = tmp_path / "repo"
    cwd.mkdir()

    # Stateful mock: show returns current state; update mutates it for next show
    issues: dict[str, dict] = {
        "agent-1": {"id": "agent-1", "description": "role: worker\n"},
    }

    def mock_stateful(request: object, **kwargs: object) -> object:
        from atelier import exec as exec_util

        if not hasattr(request, "argv"):
            return None
        argv = list(request.argv)
        if not argv or argv[0] != "bd":
            return None

        if len(argv) >= 4 and argv[1:4] == ["dolt", "show", "--json"]:
            return bd_mock.bd_dolt_show_result(connection_ok=True)

        if len(argv) >= 3 and argv[1] == "show" and "--json" in argv:
            issue_id = argv[2] if argv[2] != "--json" else (argv[3] if len(argv) > 3 else "")
            issue = issues.get(issue_id)
            return bd_mock.bd_show_result(issue)

        if len(argv) >= 2 and argv[1] in ("slot", "update"):
            if argv[1] == "update" and "--body-file" in argv:
                idx = argv.index("--body-file")
                if idx + 1 < len(argv):
                    path = Path(argv[idx + 1])
                    issue_id = argv[2]
                    if path.exists() and issue_id in issues:
                        issues[issue_id] = {
                            **issues[issue_id],
                            "description": path.read_text(encoding="utf-8"),
                        }
            return exec_util.CommandResult(
                argv=tuple(argv),
                returncode=0,
                stdout="",
                stderr="",
            )

        return exec_util.CommandResult(argv=tuple(argv), returncode=0, stdout="[]\n", stderr="")

    with pytest.MonkeyPatch.context() as m:
        m.setattr("atelier.beads.exec.run_with_runner", mock_stateful)

        beads.set_agent_hook(
            "agent-1",
            "epic-9",
            beads_root=beads_root,
            cwd=cwd,
        )

    assert "hook_bead: epic-9" in str(issues["agent-1"].get("description") or "")

"""Tests for beads_runtime.queue_messages via beads facade with exec patching."""

from __future__ import annotations

from pathlib import Path

import pytest

from atelier import beads, messages

from . import bd_mock


def test_create_message_bead_uses_client_and_returns_created_issue(tmp_path: Path) -> None:
    beads_root = tmp_path / ".beads"
    beads_root.mkdir()
    cwd = tmp_path / "repo"
    cwd.mkdir()

    create_body_captured: list[str] = []
    create_args_captured: list[list[str]] = []

    def mock_capture_create(request: object, **kwargs: object) -> object:
        if hasattr(request, "argv"):
            argv = list(request.argv)
            if "bd" in argv and "create" in argv and "--body-file" in argv:
                idx = argv.index("--body-file")
                if idx + 1 < len(argv):
                    path = Path(argv[idx + 1])
                    if path.exists():
                        create_body_captured.append(path.read_text(encoding="utf-8"))
                    create_args_captured.append(argv.copy())
        return bd_mock.mock_bd_run_with_runner(
            create_issue_id="msg-created",
            show_responses={
                "msg-created": {"id": "msg-created", "title": "Hello", "description": ""},
            },
        )(request, **kwargs)

    with pytest.MonkeyPatch.context() as m:
        m.setattr("atelier.beads.exec.run_with_runner", mock_capture_create)

        created = beads.create_message_bead(
            subject="Hello",
            body="Body",
            metadata={"from": "alice"},
            assignee="bob",
            beads_root=beads_root,
            cwd=cwd,
        )

    assert created["id"] == "msg-created"
    assert create_args_captured
    args_flat = " ".join(create_args_captured[0])
    assert "at:message" in args_flat
    assert "at:unread" in args_flat
    assert create_body_captured
    assert "from: alice" in create_body_captured[0]


def test_claim_queue_message_sets_claim_metadata(tmp_path: Path) -> None:
    beads_root = tmp_path / ".beads"
    beads_root.mkdir()
    cwd = tmp_path / "repo"
    cwd.mkdir()

    msg = {
        "id": "msg-1",
        "description": messages.render_message({"queue": "triage"}, "Body"),
        "assignee": None,
    }
    issues: dict[str, dict] = {"msg-1": dict(msg)}

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
            return bd_mock.bd_show_result(issues.get(issue_id))

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
            if argv[2:4] == ["msg-1", "--claim"]:
                issues["msg-1"]["assignee"] = "agent-1"
            return exec_util.CommandResult(
                argv=tuple(argv),
                returncode=0,
                stdout="",
                stderr="",
            )

        return exec_util.CommandResult(argv=tuple(argv), returncode=0, stdout="[]\n", stderr="")

    with pytest.MonkeyPatch.context() as m:
        m.setattr("atelier.beads.exec.run_with_runner", mock_stateful)
        m.setattr("atelier.beads.die", lambda msg, code=1: (_ for _ in ()).throw(RuntimeError(msg)))

        claimed = beads.claim_queue_message(
            "msg-1",
            "agent-1",
            beads_root=beads_root,
            cwd=cwd,
            queue="triage",
        )

    description = str(claimed.get("description") or "")
    assert "claimed_by: agent-1" in description
    assert "claimed_at:" in description


def test_claim_queue_message_fails_closed_when_queue_mismatch(tmp_path: Path) -> None:
    beads_root = tmp_path / ".beads"
    beads_root.mkdir()
    cwd = tmp_path / "repo"
    cwd.mkdir()

    # Stateful: update --claim sets assignee; show returns current state
    issues: dict[str, dict] = {
        "msg-1": {
            "id": "msg-1",
            "description": messages.render_message({"queue": "triage"}, "Body"),
            "assignee": None,
        },
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
            return bd_mock.bd_show_result(issues.get(issue_id))

        if len(argv) >= 2 and argv[1] == "update":
            if argv[2:4] == ["msg-1", "--claim"]:
                issues["msg-1"]["assignee"] = "agent-1"
            elif "--body-file" in argv and argv[2] in issues:
                idx = argv.index("--body-file")
                if idx + 1 < len(argv):
                    path = Path(argv[idx + 1])
                    if path.exists():
                        issues[argv[2]]["description"] = path.read_text(encoding="utf-8")
            return exec_util.CommandResult(
                argv=tuple(argv),
                returncode=0,
                stdout="",
                stderr="",
            )

        return exec_util.CommandResult(argv=tuple(argv), returncode=0, stdout="[]\n", stderr="")

    with pytest.MonkeyPatch.context() as m:
        m.setattr("atelier.beads.exec.run_with_runner", mock_stateful)
        m.setattr("atelier.beads.die", lambda msg, code=1: (_ for _ in ()).throw(RuntimeError(msg)))

        with pytest.raises(RuntimeError, match="message msg-1 is not in queue 'ops'"):
            beads.claim_queue_message(
                "msg-1",
                "agent-1",
                beads_root=beads_root,
                cwd=cwd,
                queue="ops",
            )

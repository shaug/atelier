"""Tests for beads_runtime.issue_mutations via beads facade with exec patching."""

from __future__ import annotations

from pathlib import Path

import pytest

from atelier import beads
from atelier.beads_runtime import issue_mutations

from . import bd_mock


def test_parse_description_fields_reads_key_values() -> None:
    parsed = issue_mutations.parse_description_fields("a: one\nb: two\n")

    assert parsed == {"a": "one", "b": "two"}


def test_update_issue_description_fields_retries_after_interleaved_overwrite(
    tmp_path: Path,
) -> None:
    beads_root = tmp_path / ".beads"
    beads_root.mkdir()
    cwd = tmp_path / "repo"
    cwd.mkdir()

    # Stateful mock: first show returns original; after update, interleaved overwrite;
    # second show returns interleaved; retry succeeds
    issues: dict[str, dict] = {
        "agent-1": {
            "id": "agent-1",
            "description": "hook_bead: epic-1\npr_state: draft-pr\n",
        },
    }
    interleaved = ["pr_state: in-review\n"]

    def mock_interleaved(request: object, **kwargs: object) -> object:
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

        if len(argv) >= 2 and argv[1] == "update" and "--body-file" in argv:
            idx = argv.index("--body-file")
            if idx + 1 < len(argv):
                path = Path(argv[idx + 1])
                issue_id = argv[2]
                if path.exists() and issue_id in issues:
                    if interleaved:
                        issues[issue_id] = {
                            "id": issue_id,
                            "description": interleaved.pop(0),
                        }
                    else:
                        issues[issue_id] = {
                            "id": issue_id,
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
        m.setattr("atelier.beads.exec.run_with_runner", mock_interleaved)
        m.setattr("atelier.beads.die", lambda msg, code=1: (_ for _ in ()).throw(RuntimeError(msg)))

        updated = beads.update_issue_description_fields(
            "agent-1",
            {"hook_bead": "epic-2"},
            beads_root=beads_root,
            cwd=cwd,
        )

    description = str(updated.get("description") or "")
    assert "hook_bead: epic-2" in description
    assert "pr_state: in-review" in description


def test_update_issue_description_fields_fails_closed_after_retry_exhaustion(
    tmp_path: Path,
) -> None:
    beads_root = tmp_path / ".beads"
    beads_root.mkdir()
    cwd = tmp_path / "repo"
    cwd.mkdir()

    # Mock that always overwrites with stale content (simulates concurrent writer)
    issues: dict[str, dict] = {
        "agent-1": {"id": "agent-1", "description": "hook_bead: epic-1\n"},
    }

    def mock_always_stale(request: object, **kwargs: object) -> object:
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

        if len(argv) >= 2 and argv[1] == "update" and "--body-file" in argv:
            issue_id = argv[2]
            if issue_id in issues:
                issues[issue_id] = {"id": issue_id, "description": "hook_bead: epic-1\n"}
            return exec_util.CommandResult(
                argv=tuple(argv),
                returncode=0,
                stdout="",
                stderr="",
            )

        return exec_util.CommandResult(argv=tuple(argv), returncode=0, stdout="[]\n", stderr="")

    with pytest.MonkeyPatch.context() as m:
        m.setattr("atelier.beads.exec.run_with_runner", mock_always_stale)
        m.setattr("atelier.beads.die", lambda msg, code=1: (_ for _ in ()).throw(RuntimeError(msg)))

        with pytest.raises(
            RuntimeError, match="concurrent description update conflict for agent-1"
        ):
            beads.update_issue_description_fields(
                "agent-1",
                {"hook_bead": "epic-2"},
                beads_root=beads_root,
                cwd=cwd,
            )


def test_issue_description_fields_returns_empty_for_missing_issue(tmp_path: Path) -> None:
    beads_root = tmp_path / ".beads"
    beads_root.mkdir()
    cwd = tmp_path / "repo"
    cwd.mkdir()

    mock = bd_mock.mock_bd_run_with_runner(show_responses={})

    with pytest.MonkeyPatch.context() as m:
        m.setattr("atelier.beads.exec.run_with_runner", mock)

        result = beads.issue_description_fields(
            "missing",
            beads_root=beads_root,
            cwd=cwd,
        )

    assert result == {}

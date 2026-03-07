"""Helpers for mocking bd interactions via exec.run_with_runner patching.

Use these helpers instead of protocol-based client fakes. Patch at the exec
boundary so tests exercise real code paths with canned bd responses.
"""

from __future__ import annotations

import json
from typing import Any

from atelier import exec as exec_util


def bd_show_result(issue: dict[str, Any] | None) -> exec_util.CommandResult:
    """Build a CommandResult for ``bd show <id> --json``."""
    payload = [issue] if issue else []
    return exec_util.CommandResult(
        argv=("bd", "show", "--json"),
        returncode=0,
        stdout=json.dumps(payload) + "\n",
        stderr="",
    )


def bd_stats_result(total_issues: int) -> exec_util.CommandResult:
    """Build a CommandResult for ``bd stats --json``."""
    payload = {"summary": {"total_issues": total_issues}}
    return exec_util.CommandResult(
        argv=("bd", "stats", "--json"),
        returncode=0,
        stdout=json.dumps(payload) + "\n",
        stderr="",
    )


def bd_dolt_show_result(connection_ok: bool = True) -> exec_util.CommandResult:
    """Build a CommandResult for ``bd dolt show --json`` (preflight health check)."""
    payload = {"connection_ok": connection_ok, "database": "beads"}
    return exec_util.CommandResult(
        argv=("bd", "dolt", "show", "--json"),
        returncode=0,
        stdout=json.dumps(payload) + "\n",
        stderr="",
    )


def bd_list_parent_result(children: list[dict[str, Any]]) -> exec_util.CommandResult:
    """Build a CommandResult for ``bd list --parent <id>``."""
    return exec_util.CommandResult(
        argv=("bd", "list", "--parent"),
        returncode=0,
        stdout=json.dumps(children) + "\n",
        stderr="",
    )


def mock_bd_run_with_runner(
    *,
    show_responses: dict[str, dict[str, Any]] | None = None,
    stats_total: int = 0,
    dolt_stats_total: int | None = None,
    legacy_stats_total: int | None = None,
    dolt_stats_fail: bool = False,
    dolt_show_ok: bool = True,
    list_parent_responses: dict[str, list[dict[str, Any]]] | None = None,
    slot_hooks: dict[str, str] | None = None,
    default_json: dict[str, Any] | list[Any] | None = None,
    create_issue_id: str = "at-1",
):
    """Build a side_effect for patching exec.run_with_runner with canned bd responses.

    Use with: patch("atelier.beads.exec.run_with_runner", side_effect=mock_bd_run_with_runner(...))

    Args:
        show_responses: Map issue_id -> issue payload for bd show.
        stats_total: Issue total for bd stats --json (used when dolt/legacy not set).
        dolt_stats_total: Override for bd stats (no --db). None = use stats_total.
        legacy_stats_total: Override for bd --db <path> stats. None = use stats_total.
        dolt_stats_fail: If True, bd stats (no --db) returns non-zero (simulates missing dolt).
        dolt_show_ok: connection_ok for bd dolt show (preflight).
        list_parent_responses: Map parent_id -> list of child issues.
        slot_hooks: Map agent_id -> epic_id for bd slot show.
        default_json: Default JSON for unmatched bd commands (e.g. [] or {}).
        create_issue_id: Issue id returned for bd create (stdout).

    Returns:
        A callable (request) -> CommandResult | None for use as patch side_effect.
    """
    show_responses = dict(show_responses or {})
    list_parent_responses = dict(list_parent_responses or {})
    slot_hooks = dict(slot_hooks or {})
    default_payload = default_json if default_json is not None else []
    create_id = create_issue_id
    dolt_total = dolt_stats_total if dolt_stats_total is not None else stats_total
    legacy_total = legacy_stats_total if legacy_stats_total is not None else stats_total
    dolt_fail = dolt_stats_fail

    def _run(request: exec_util.CommandRequest, **kwargs: object) -> exec_util.CommandResult | None:
        argv = list(request.argv)
        if not argv or argv[0] != "bd":
            return None

        # bd dolt show --json (preflight)
        if len(argv) >= 4 and argv[1:4] == ["dolt", "show", "--json"]:
            return bd_dolt_show_result(connection_ok=dolt_show_ok)

        # bd stats --json or bd --db <path> stats --json
        if "stats" in argv and "--json" in argv:
            if "--db" in argv:
                return bd_stats_result(total_issues=legacy_total)
            if dolt_fail:
                return exec_util.CommandResult(
                    argv=tuple(argv),
                    returncode=1,
                    stdout="",
                    stderr="dolt unavailable",
                )
            return bd_stats_result(total_issues=dolt_total)

        # bd show <id> --json
        if len(argv) >= 3 and argv[1] == "show" and "--json" in argv:
            issue_id = argv[2] if argv[2] != "--json" else (argv[3] if len(argv) > 3 else "")
            issue = show_responses.get(issue_id)
            return bd_show_result(issue)

        # bd list --parent <id>
        if len(argv) >= 4 and argv[1:3] == ["list", "--parent"]:
            parent_id = argv[3]
            children = list_parent_responses.get(parent_id, [])
            return bd_list_parent_result(children)

        # bd slot show <id> --json
        if len(argv) >= 4 and argv[1:3] == ["slot", "show"]:
            agent_id = argv[3]
            hook = slot_hooks.get(agent_id)
            if hook is None and agent_id in show_responses:
                desc = show_responses[agent_id].get("description") or ""
                for line in str(desc).splitlines():
                    if line.strip().startswith("hook_bead:"):
                        hook = line.split(":", 1)[1].strip()
                        break
            payload = {"hook": hook} if hook else {}
            return exec_util.CommandResult(
                argv=tuple(argv),
                returncode=0,
                stdout=json.dumps(payload) + "\n",
                stderr="",
            )

        # bd slot set, slot clear, update - return success
        if len(argv) >= 2 and argv[1] in ("slot", "update"):
            return exec_util.CommandResult(
                argv=tuple(argv),
                returncode=0,
                stdout="",
                stderr="",
            )

        # create - return issue id on stdout (bd create --silent)
        if len(argv) >= 2 and argv[1] == "create":
            return exec_util.CommandResult(
                argv=tuple(argv),
                returncode=0,
                stdout=create_id + "\n",
                stderr="",
            )

        # Default for other bd commands
        return exec_util.CommandResult(
            argv=tuple(argv),
            returncode=0,
            stdout=json.dumps(default_payload) + "\n" if default_payload else "",
            stderr="",
        )

    return _run

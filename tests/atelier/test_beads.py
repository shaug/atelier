import json
import sqlite3
from pathlib import Path
from subprocess import CompletedProcess
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest

import atelier.beads as beads
from atelier import exec as exec_util


def test_beads_env_sets_beads_db() -> None:
    env = beads.beads_env(Path("/tmp/project/.beads"))

    assert env["BEADS_DIR"] == "/tmp/project/.beads"
    assert env["BEADS_DB"] == "/tmp/project/.beads/beads.db"


def test_normalize_dolt_runtime_metadata_once_updates_legacy_fields(
    tmp_path: Path,
) -> None:
    beads_root = tmp_path / ".beads"
    beads_root.mkdir()
    (beads_root / "dolt" / "beads_at" / ".dolt").mkdir(parents=True)
    metadata_path = beads_root / "metadata.json"
    metadata_path.write_text(
        json.dumps(
            {
                "database": "dolt",
                "backend": "dolt",
                "dolt_mode": "embedded",
                "dolt_server_host": "",
                "dolt_server_port": 0,
                "dolt_database": "",
            }
        ),
        encoding="utf-8",
    )

    beads._DOLT_RUNTIME_NORMALIZED.clear()  # pyright: ignore[reportPrivateUsage]
    beads._normalize_dolt_runtime_metadata_once(  # pyright: ignore[reportPrivateUsage]
        beads_root=beads_root
    )
    beads._normalize_dolt_runtime_metadata_once(  # pyright: ignore[reportPrivateUsage]
        beads_root=beads_root
    )

    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert payload["backend"] == "dolt"
    assert payload["dolt_mode"] == "server"
    assert payload["dolt_server_host"] == "127.0.0.1"
    assert payload["dolt_server_port"] == 3307
    assert payload["dolt_server_user"] == "root"
    assert payload["dolt_database"] == "beads_at"


def test_normalize_dolt_runtime_metadata_once_skips_invalid_json(
    tmp_path: Path,
) -> None:
    beads_root = tmp_path / ".beads"
    beads_root.mkdir()
    metadata_path = beads_root / "metadata.json"
    metadata_path.write_text("{not-json", encoding="utf-8")

    beads._DOLT_RUNTIME_NORMALIZED.clear()  # pyright: ignore[reportPrivateUsage]
    beads._normalize_dolt_runtime_metadata_once(  # pyright: ignore[reportPrivateUsage]
        beads_root=beads_root
    )

    assert metadata_path.read_text(encoding="utf-8") == "{not-json"


def test_run_bd_issue_records_validates_issues() -> None:
    with patch(
        "atelier.beads.run_bd_json",
        return_value=[{"id": "at-1", "labels": [], "status": "open"}],
    ):
        records = beads.run_bd_issue_records(
            ["list"], beads_root=Path("/beads"), cwd=Path("/repo"), source="test"
        )
    assert len(records) == 1
    assert records[0].issue.id == "at-1"
    assert records[0].raw["id"] == "at-1"


def test_run_bd_issue_records_rejects_invalid_payload() -> None:
    with patch(
        "atelier.beads.run_bd_json",
        return_value=[{"labels": [], "status": "open"}],
    ):
        with pytest.raises(ValueError, match="invalid beads issue payload"):
            beads.run_bd_issue_records(
                ["list"], beads_root=Path("/beads"), cwd=Path("/repo"), source="test"
            )


def test_run_bd_command_repairs_missing_store_and_retries(tmp_path: Path) -> None:
    beads_root = tmp_path / "project" / ".beads"
    beads_root.mkdir(parents=True)
    (beads_root / "issues.jsonl").write_text("{}", encoding="utf-8")
    cwd = tmp_path / "repo"
    cwd.mkdir(parents=True)
    calls: list[list[str]] = []

    def fake_run_with_runner(
        request: exec_util.CommandRequest,
    ) -> exec_util.CommandResult | None:
        argv = list(request.argv)
        calls.append(argv)
        if argv[:2] == ["bd", "prime"] and len(calls) == 1:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=1,
                stdout="",
                stderr="Error: no beads database found",
            )
        if argv[:3] == ["bd", "doctor", "--fix"]:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout="fixed",
                stderr="",
            )
        if argv[:4] == ["bd", "init", "--prefix", "at"] and "--from-jsonl" in argv:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout="initialized",
                stderr="",
            )
        if argv[:5] == ["bd", "config", "set", "issue_prefix", "at"]:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout="ok",
                stderr="",
            )
        if argv[:5] == ["bd", "config", "set", "beads.role", "maintainer"]:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout="ok",
                stderr="",
            )
        if argv[:5] == ["bd", "config", "get", "issue_prefix", "--json"]:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout='{"value":"at"}',
                stderr="",
            )
        if argv[:2] == ["bd", "prime"] and len(calls) > 1:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout="primed",
                stderr="",
            )
        raise AssertionError(f"unexpected command: {argv}")

    with (
        patch("atelier.beads.bd_invocation.ensure_supported_bd_version"),
        patch("atelier.beads.exec.run_with_runner", side_effect=fake_run_with_runner),
    ):
        result = beads.run_bd_command(["prime"], beads_root=beads_root, cwd=cwd)

    assert result.returncode == 0
    assert calls[0] == ["bd", "prime"]
    assert ["bd", "doctor", "--fix", "--yes"] in calls
    assert ["bd", "init", "--prefix", "at", "--from-jsonl"] in calls
    assert ["bd", "config", "set", "issue_prefix", "at"] in calls
    assert calls[-1] == ["bd", "prime"]


def test_run_bd_command_repairs_issue_prefix_without_jsonl_init(tmp_path: Path) -> None:
    beads_root = tmp_path / "project" / ".beads"
    beads_root.mkdir(parents=True)
    cwd = tmp_path / "repo"
    cwd.mkdir(parents=True)
    calls: list[list[str]] = []

    def fake_run_with_runner(
        request: exec_util.CommandRequest,
    ) -> exec_util.CommandResult | None:
        argv = list(request.argv)
        calls.append(argv)
        if argv[:2] == ["bd", "list"] and len(calls) == 1:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=1,
                stdout="",
                stderr="Error: database not initialized: issue_prefix config is missing",
            )
        if argv[:3] == ["bd", "doctor", "--fix"]:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=1,
                stdout="",
                stderr="manual fix required",
            )
        if argv[:4] == ["bd", "init", "--prefix", "at"]:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=1,
                stdout="",
                stderr="already initialized",
            )
        if argv[:5] == ["bd", "config", "set", "issue_prefix", "at"]:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout="ok",
                stderr="",
            )
        if argv[:5] == ["bd", "config", "set", "beads.role", "maintainer"]:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout="ok",
                stderr="",
            )
        if argv[:5] == ["bd", "config", "get", "issue_prefix", "--json"]:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout='{"value":"at"}',
                stderr="",
            )
        if argv[:2] == ["bd", "list"] and len(calls) > 1:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout="[]",
                stderr="",
            )
        raise AssertionError(f"unexpected command: {argv}")

    with (
        patch("atelier.beads.bd_invocation.ensure_supported_bd_version"),
        patch("atelier.beads.exec.run_with_runner", side_effect=fake_run_with_runner),
    ):
        result = beads.run_bd_command(["list", "--json"], beads_root=beads_root, cwd=cwd)

    assert result.returncode == 0
    init_calls = [call for call in calls if call[:4] == ["bd", "init", "--prefix", "at"]]
    assert init_calls == [["bd", "init", "--prefix", "at"]]
    assert calls[-1] == ["bd", "list", "--json"]


def test_run_bd_json_retries_embedded_backend_panic_with_explicit_db(
    tmp_path: Path,
) -> None:
    beads_root = tmp_path / ".beads"
    beads_root.mkdir()
    cwd = tmp_path / "repo"
    cwd.mkdir()
    calls: list[list[str]] = []

    def fake_run_with_runner(
        request: exec_util.CommandRequest,
    ) -> exec_util.CommandResult | None:
        argv = list(request.argv)
        calls.append(argv)
        if argv == ["bd", "show", "at-1", "--json"]:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=2,
                stdout="",
                stderr=(
                    "panic: runtime error: invalid memory address or nil pointer dereference\n"
                    "doltdb.(*DoltDB).SetCrashOnFatalError"
                ),
            )
        if argv == [
            "bd",
            "--db",
            str(beads_root / "beads.db"),
            "show",
            "at-1",
            "--json",
        ]:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout='[{"id":"at-1","status":"open","labels":[]}]',
                stderr="",
            )
        raise AssertionError(f"unexpected command: {argv}")

    with (
        patch("atelier.beads.bd_invocation.ensure_supported_bd_version"),
        patch("atelier.beads.exec.run_with_runner", side_effect=fake_run_with_runner),
    ):
        payload = beads.run_bd_json(["show", "at-1"], beads_root=beads_root, cwd=cwd)

    assert payload == [{"id": "at-1", "status": "open", "labels": []}]
    assert calls == [
        ["bd", "show", "at-1", "--json"],
        ["bd", "--db", str(beads_root / "beads.db"), "show", "at-1", "--json"],
    ]


def test_run_bd_json_attempts_doctor_fix_after_repeated_embedded_panic(
    tmp_path: Path,
) -> None:
    beads_root = tmp_path / ".beads"
    beads_root.mkdir()
    cwd = tmp_path / "repo"
    cwd.mkdir()
    calls: list[list[str]] = []
    fallback = ["bd", "--db", str(beads_root / "beads.db"), "show", "at-1", "--json"]
    fallback_count = 0

    def fake_run_with_runner(
        request: exec_util.CommandRequest,
    ) -> exec_util.CommandResult | None:
        nonlocal fallback_count
        argv = list(request.argv)
        calls.append(argv)
        if argv == ["bd", "show", "at-1", "--json"]:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=2,
                stdout="",
                stderr=(
                    "panic: runtime error: invalid memory address or nil pointer dereference\n"
                    "doltdb.(*DoltDB).SetCrashOnFatalError"
                ),
            )
        if argv == fallback:
            fallback_count += 1
            if fallback_count == 1:
                return exec_util.CommandResult(
                    argv=request.argv,
                    returncode=2,
                    stdout="",
                    stderr=(
                        "panic: runtime error: invalid memory address or nil pointer dereference\n"
                        "doltdb.(*DoltDB).SetCrashOnFatalError"
                    ),
                )
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout='[{"id":"at-1"}]',
                stderr="",
            )
        if argv == ["bd", "doctor", "--fix", "--yes"]:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=1,
                stdout="",
                stderr="repair attempted",
            )
        raise AssertionError(f"unexpected command: {argv}")

    with (
        patch("atelier.beads.bd_invocation.ensure_supported_bd_version"),
        patch("atelier.beads.exec.run_with_runner", side_effect=fake_run_with_runner),
    ):
        payload = beads.run_bd_json(["show", "at-1"], beads_root=beads_root, cwd=cwd)

    assert payload == [{"id": "at-1"}]
    assert calls == [
        ["bd", "show", "at-1", "--json"],
        fallback,
        ["bd", "doctor", "--fix", "--yes"],
        fallback,
    ]


def test_run_bd_command_embedded_panic_guidance_mentions_doctor_retry(
    tmp_path: Path,
) -> None:
    beads_root = tmp_path / ".beads"
    beads_root.mkdir()
    cwd = tmp_path / "repo"
    cwd.mkdir()
    fallback = ["bd", "--db", str(beads_root / "beads.db"), "show", "at-1", "--json"]

    def fake_run_with_runner(
        request: exec_util.CommandRequest,
    ) -> exec_util.CommandResult | None:
        argv = list(request.argv)
        if argv in (["bd", "show", "at-1", "--json"], fallback):
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=2,
                stdout="",
                stderr=(
                    "panic: runtime error: invalid memory address or nil pointer dereference\n"
                    "doltdb.(*DoltDB).SetCrashOnFatalError"
                ),
            )
        if argv == ["bd", "doctor", "--fix", "--yes"]:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=1,
                stdout="",
                stderr="repair failed",
            )
        raise AssertionError(f"unexpected command: {argv}")

    def fake_die(message: str, code: int = 1) -> None:
        del code
        raise RuntimeError(message)

    with (
        patch("atelier.beads.bd_invocation.ensure_supported_bd_version"),
        patch("atelier.beads.exec.run_with_runner", side_effect=fake_run_with_runner),
        patch("atelier.beads._startup_state_diagnostics", return_value="startup-diag"),
        patch("atelier.beads.die", side_effect=fake_die),
    ):
        with pytest.raises(RuntimeError, match="embedded storage panic from bd"):
            beads.run_bd_command(["show", "at-1", "--json"], beads_root=beads_root, cwd=cwd)


def test_run_bd_command_missing_store_guidance_mentions_beads_dir(
    tmp_path: Path,
) -> None:
    beads_root = tmp_path / ".beads"
    beads_root.mkdir()
    cwd = tmp_path / "repo"
    cwd.mkdir()

    def fake_run_with_runner(
        request: exec_util.CommandRequest,
    ) -> exec_util.CommandResult | None:
        return exec_util.CommandResult(
            argv=request.argv,
            returncode=1,
            stdout="",
            stderr="Error: database not initialized: issue_prefix config is missing",
        )

    def fake_die(message: str, code: int = 1) -> None:
        del code
        raise RuntimeError(message)

    with (
        patch("atelier.beads.bd_invocation.ensure_supported_bd_version"),
        patch("atelier.beads.exec.run_with_runner", side_effect=fake_run_with_runner),
        patch("atelier.beads._repair_beads_store", return_value=False),
        patch("atelier.beads._startup_state_diagnostics", return_value="startup-diag"),
        patch("atelier.beads.die", side_effect=fake_die),
    ):
        with pytest.raises(RuntimeError, match="missing or uninitialized Beads store"):
            beads.run_bd_command(["list", "--json"], beads_root=beads_root, cwd=cwd)


def test_run_bd_command_preflight_recovers_dolt_server_before_command(
    tmp_path: Path,
) -> None:
    beads_root = tmp_path / ".beads"
    (beads_root / "dolt").mkdir(parents=True)
    cwd = tmp_path / "repo"
    cwd.mkdir()
    calls: list[list[str]] = []

    def fake_run_with_runner(
        request: exec_util.CommandRequest,
    ) -> exec_util.CommandResult | None:
        argv = list(request.argv)
        calls.append(argv)
        if argv == ["bd", "list", "--json"]:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout="[]",
                stderr="",
            )
        raise AssertionError(f"unexpected command: {argv}")

    with (
        patch("atelier.beads.bd_invocation.ensure_supported_bd_version"),
        patch(
            "atelier.beads._probe_dolt_server_health",
            side_effect=[(False, "connection refused"), (True, None)],
        ) as probe_health,
        patch(
            "atelier.beads._restart_dolt_server_with_recovery",
            return_value=(True, "recovered"),
        ) as restart,
        patch("atelier.beads.exec.run_with_runner", side_effect=fake_run_with_runner),
    ):
        result = beads.run_bd_command(["list", "--json"], beads_root=beads_root, cwd=cwd)

    assert result.returncode == 0
    assert calls == [["bd", "list", "--json"]]
    assert probe_health.call_count == 2
    assert restart.call_count == 1


def test_run_bd_command_retries_after_dolt_server_recovery(tmp_path: Path) -> None:
    beads_root = tmp_path / ".beads"
    (beads_root / "dolt").mkdir(parents=True)
    cwd = tmp_path / "repo"
    cwd.mkdir()
    calls: list[list[str]] = []
    attempts = 0

    def fake_run_with_runner(
        request: exec_util.CommandRequest,
    ) -> exec_util.CommandResult | None:
        nonlocal attempts
        argv = list(request.argv)
        calls.append(argv)
        if argv == ["bd", "show", "at-1", "--json"]:
            attempts += 1
            if attempts == 1:
                return exec_util.CommandResult(
                    argv=request.argv,
                    returncode=1,
                    stdout="",
                    stderr="dial tcp 127.0.0.1:3307: connect: connection refused",
                )
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout='[{"id":"at-1"}]',
                stderr="",
            )
        raise AssertionError(f"unexpected command: {argv}")

    with (
        patch("atelier.beads.bd_invocation.ensure_supported_bd_version"),
        patch("atelier.beads._probe_dolt_server_health", return_value=(True, None)),
        patch(
            "atelier.beads._restart_dolt_server_with_recovery",
            return_value=(True, "recovered"),
        ) as restart,
        patch("atelier.beads.exec.run_with_runner", side_effect=fake_run_with_runner),
    ):
        result = beads.run_bd_command(["show", "at-1", "--json"], beads_root=beads_root, cwd=cwd)

    assert result.returncode == 0
    assert calls == [["bd", "show", "at-1", "--json"], ["bd", "show", "at-1", "--json"]]
    assert restart.call_count == 1


def test_run_bd_command_dolt_recovery_is_bounded_and_surfaces_failure(
    tmp_path: Path,
) -> None:
    beads_root = tmp_path / ".beads"
    (beads_root / "dolt").mkdir(parents=True)
    cwd = tmp_path / "repo"
    cwd.mkdir()
    calls: list[list[str]] = []

    def fake_run_with_runner(
        request: exec_util.CommandRequest,
    ) -> exec_util.CommandResult | None:
        argv = list(request.argv)
        calls.append(argv)
        if argv == ["bd", "show", "at-1", "--json"]:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=1,
                stdout="",
                stderr="dial tcp 127.0.0.1:3307: connect: connection refused",
            )
        raise AssertionError(f"unexpected command: {argv}")

    def fake_die(message: str, code: int = 1) -> None:
        del code
        raise RuntimeError(message)

    with (
        patch("atelier.beads.bd_invocation.ensure_supported_bd_version"),
        patch("atelier.beads._probe_dolt_server_health", return_value=(True, None)),
        patch(
            "atelier.beads._restart_dolt_server_with_recovery",
            side_effect=[(True, "first recovery"), (True, "second recovery")],
        ) as restart,
        patch("atelier.beads.exec.run_with_runner", side_effect=fake_run_with_runner),
        patch("atelier.beads._startup_state_diagnostics", return_value="startup-diag"),
        patch("atelier.beads.die", side_effect=fake_die),
    ):
        with pytest.raises(RuntimeError) as excinfo:
            beads.run_bd_command(["show", "at-1", "--json"], beads_root=beads_root, cwd=cwd)

    message = str(excinfo.value)
    assert "bounded Dolt server recovery" in message
    assert "degraded-mode diagnostics" in message
    assert "`bd doctor --fix --yes`" in message
    assert calls == [
        ["bd", "show", "at-1", "--json"],
        ["bd", "show", "at-1", "--json"],
        ["bd", "show", "at-1", "--json"],
    ]
    assert restart.call_count == 2


def test_run_bd_command_covers_dolt_lifecycle_paths_across_projects(
    tmp_path: Path,
) -> None:
    healthy_beads_root = tmp_path / "healthy" / ".beads"
    recovering_beads_root = tmp_path / "recovering" / ".beads"
    failing_beads_root = tmp_path / "failing" / ".beads"
    for beads_root in (healthy_beads_root, recovering_beads_root, failing_beads_root):
        (beads_root / "dolt").mkdir(parents=True)

    healthy_repo = tmp_path / "healthy-repo"
    recovering_repo = tmp_path / "recovering-repo"
    failing_repo = tmp_path / "failing-repo"
    for repo_path in (healthy_repo, recovering_repo, failing_repo):
        repo_path.mkdir()

    command_calls: list[tuple[Path, list[str]]] = []
    probe_counts: dict[Path, int] = {
        healthy_beads_root: 0,
        recovering_beads_root: 0,
        failing_beads_root: 0,
    }
    restart_calls: list[Path] = []

    def fake_run_with_runner(
        request: exec_util.CommandRequest,
    ) -> exec_util.CommandResult | None:
        argv = list(request.argv)
        command_calls.append((request.cwd, argv))
        if argv != ["bd", "show", "at-1", "--json"]:
            raise AssertionError(f"unexpected command: {argv}")
        if request.cwd in {healthy_repo, recovering_repo}:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout='[{"id":"at-1"}]',
                stderr="",
            )
        raise AssertionError("failing project should not run command after preflight failure")

    def fake_probe_dolt_server_health(
        runtime: beads.DoltServerRuntime, *, cwd: Path, env: dict[str, str]
    ) -> tuple[bool, str | None]:
        del cwd, env
        beads_root = runtime.dolt_root.parent
        probe_counts[beads_root] += 1
        if beads_root == healthy_beads_root:
            return True, None
        if beads_root == recovering_beads_root:
            if probe_counts[beads_root] == 1:
                return False, "dial tcp 127.0.0.1:3307: connect: connection refused"
            return True, None
        if beads_root == failing_beads_root:
            return False, "dial tcp 127.0.0.1:3307: connect: connection refused"
        raise AssertionError(f"unexpected beads root: {beads_root}")

    def fake_restart_dolt_server_with_recovery(
        *, beads_root: Path, cwd: Path, env: dict[str, str]
    ) -> tuple[bool, str]:
        del cwd, env
        restart_calls.append(beads_root)
        if beads_root == recovering_beads_root:
            return True, "dolt server recovered for 127.0.0.1:3307"
        if beads_root == failing_beads_root:
            return (
                False,
                "panic: runtime error: invalid memory address or nil pointer dereference",
            )
        raise AssertionError(f"unexpected restart root: {beads_root}")

    def fake_startup_state_diagnostics(*, beads_root: Path, cwd: Path) -> str:
        del cwd
        return f"startup-diag:{beads_root.parent.name}"

    def fake_die(message: str, code: int = 1) -> None:
        del code
        raise RuntimeError(message)

    with (
        patch("atelier.beads.bd_invocation.ensure_supported_bd_version"),
        patch("atelier.beads.exec.run_with_runner", side_effect=fake_run_with_runner),
        patch(
            "atelier.beads._probe_dolt_server_health",
            side_effect=fake_probe_dolt_server_health,
        ),
        patch(
            "atelier.beads._restart_dolt_server_with_recovery",
            side_effect=fake_restart_dolt_server_with_recovery,
        ),
        patch(
            "atelier.beads._startup_state_diagnostics",
            side_effect=fake_startup_state_diagnostics,
        ),
        patch("atelier.beads.die", side_effect=fake_die),
    ):
        healthy = beads.run_bd_command(
            ["show", "at-1", "--json"],
            beads_root=healthy_beads_root,
            cwd=healthy_repo,
        )
        recovering = beads.run_bd_command(
            ["show", "at-1", "--json"],
            beads_root=recovering_beads_root,
            cwd=recovering_repo,
        )
        with pytest.raises(RuntimeError) as excinfo:
            beads.run_bd_command(
                ["show", "at-1", "--json"],
                beads_root=failing_beads_root,
                cwd=failing_repo,
            )

    assert healthy.returncode == 0
    assert recovering.returncode == 0
    failure_message = str(excinfo.value)
    assert "dolt server preflight failed before running bd command" in failure_message
    assert "degraded-mode diagnostics" in failure_message
    assert "`bd dolt show --json`" in failure_message
    assert "`bd doctor --fix --yes`" in failure_message
    assert "panic: runtime error" not in failure_message
    assert "embedded panic while checking Dolt server health" in failure_message
    assert "startup-diag:failing" in failure_message
    assert command_calls == [
        (healthy_repo, ["bd", "show", "at-1", "--json"]),
        (recovering_repo, ["bd", "show", "at-1", "--json"]),
    ]
    assert probe_counts[healthy_beads_root] == 1
    assert probe_counts[recovering_beads_root] == 2
    assert probe_counts[failing_beads_root] == 1
    assert restart_calls == [recovering_beads_root, failing_beads_root]


def test_run_bd_command_rejects_changeset_in_progress_with_open_dependencies(
    tmp_path: Path,
) -> None:
    beads_root = tmp_path / ".beads"
    beads_root.mkdir()
    cwd = tmp_path / "repo"
    cwd.mkdir()
    calls: list[list[str]] = []

    def fake_run_with_runner(
        request: exec_util.CommandRequest,
    ) -> exec_util.CommandResult | None:
        argv = list(request.argv)
        calls.append(argv)
        if argv == ["bd", "show", "at-2", "--json"]:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout=(
                    '[{"id":"at-2","status":"open","labels":[],'
                    '"dependencies":["at-1"],"type":"task"}]'
                ),
                stderr="",
            )
        if argv == ["bd", "show", "at-1", "--json"]:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout='[{"id":"at-1","status":"in_progress","labels":[],"type":"task"}]',
                stderr="",
            )
        if argv == ["bd", "list", "--parent", "at-2", "--json"]:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout="[]",
                stderr="",
            )
        raise AssertionError(f"unexpected command: {argv}")

    def fake_die(message: str, code: int = 1) -> None:
        del code
        raise RuntimeError(message)

    with (
        patch("atelier.beads.bd_invocation.ensure_supported_bd_version"),
        patch("atelier.beads.exec.run_with_runner", side_effect=fake_run_with_runner),
        patch("atelier.beads.die", side_effect=fake_die),
    ):
        with pytest.raises(
            RuntimeError,
            match="cannot set changeset at-2 to in_progress: blocking dependencies",
        ):
            beads.run_bd_command(
                ["update", "at-2", "--status", "in_progress"],
                beads_root=beads_root,
                cwd=cwd,
            )

    assert ["bd", "show", "at-2", "--json"] in calls
    assert ["bd", "list", "--parent", "at-2", "--json"] in calls
    assert ["bd", "show", "at-1", "--json"] in calls


def test_run_bd_command_prime_auto_migrates_recoverable_startup_state(
    tmp_path: Path,
) -> None:
    beads_root = tmp_path / ".beads"
    beads_root.mkdir()
    (beads_root / "beads.db").write_bytes(b"legacy")
    cwd = tmp_path / "repo"
    cwd.mkdir()

    db_stats = ["bd", "--db", str(beads_root / "beads.db"), "stats", "--json"]
    migrate = [
        "bd",
        "--db",
        str(beads_root / "beads.db"),
        "migrate",
        "--to-dolt",
        "--yes",
        "--json",
    ]
    stats_calls = 0
    calls: list[list[str]] = []
    diagnostics: list[str] = []

    def fake_run_with_runner(
        request: exec_util.CommandRequest,
    ) -> exec_util.CommandResult | None:
        nonlocal stats_calls
        argv = list(request.argv)
        calls.append(argv)
        if argv == ["bd", "stats", "--json"]:
            stats_calls += 1
            if stats_calls == 1:
                return exec_util.CommandResult(
                    argv=request.argv,
                    returncode=2,
                    stdout="",
                    stderr=(
                        "panic: runtime error: invalid memory address or nil pointer dereference\n"
                        "doltdb.(*DoltDB).SetCrashOnFatalError"
                    ),
                )
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout='{"summary":{"total_issues":8}}',
                stderr="",
            )
        if argv == db_stats:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout='{"summary":{"total_issues":8}}',
                stderr="",
            )
        if argv == migrate:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout='{"migrated":8}',
                stderr="",
            )
        if argv == ["bd", "prime"]:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout="primed",
                stderr="",
            )
        raise AssertionError(f"unexpected command: {argv}")

    with (
        patch("atelier.beads.bd_invocation.ensure_supported_bd_version"),
        patch("atelier.beads.bd_invocation.detect_bd_version", return_value=(0, 56, 1)),
        patch("atelier.beads.exec.run_with_runner", side_effect=fake_run_with_runner),
        patch("atelier.beads.say", side_effect=diagnostics.append),
    ):
        result = beads.run_bd_command(["prime"], beads_root=beads_root, cwd=cwd)

    assert result.returncode == 0
    assert migrate in calls
    assert calls[-1] == ["bd", "prime"]
    backups = list((beads_root / "backups").glob("beads.db.*.bak"))
    assert len(backups) == 1
    assert diagnostics
    assert "auto-upgrade migrated" in diagnostics[0]
    assert "legacy SQLite data exists but Dolt backend is missing" in diagnostics[0]


def test_run_bd_command_prime_reports_skipped_healthy_dolt_diagnostic(
    tmp_path: Path,
) -> None:
    beads_root = tmp_path / ".beads"
    (beads_root / "dolt" / "beads_at" / ".dolt").mkdir(parents=True)
    (beads_root / "beads.db").write_bytes(b"legacy")
    cwd = tmp_path / "repo"
    cwd.mkdir()

    db_stats = ["bd", "--db", str(beads_root / "beads.db"), "stats", "--json"]
    calls: list[list[str]] = []
    diagnostics: list[str] = []

    def fake_run_with_runner(
        request: exec_util.CommandRequest,
    ) -> exec_util.CommandResult | None:
        argv = list(request.argv)
        calls.append(argv)
        if argv == ["bd", "stats", "--json"] or argv == db_stats:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout='{"summary":{"total_issues":4}}',
                stderr="",
            )
        if argv == ["bd", "prime"]:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout="primed",
                stderr="",
            )
        raise AssertionError(f"unexpected command: {argv}")

    with (
        patch("atelier.beads.bd_invocation.ensure_supported_bd_version"),
        patch("atelier.beads.exec.run_with_runner", side_effect=fake_run_with_runner),
        patch("atelier.beads.say", side_effect=diagnostics.append),
    ):
        result = beads.run_bd_command(["prime"], beads_root=beads_root, cwd=cwd)

    assert result.returncode == 0
    assert not any("migrate" in call for call in calls)
    assert diagnostics
    assert "auto-upgrade skipped" in diagnostics[0]
    assert "active Dolt issue count already covers legacy SQLite issue count" in diagnostics[0]


def test_run_bd_command_prime_auto_migrates_insufficient_dolt_state(
    tmp_path: Path,
) -> None:
    beads_root = tmp_path / ".beads"
    (beads_root / "dolt" / "beads_at" / ".dolt").mkdir(parents=True)
    (beads_root / "beads.db").write_bytes(b"legacy")
    cwd = tmp_path / "repo"
    cwd.mkdir()

    db_stats = ["bd", "--db", str(beads_root / "beads.db"), "stats", "--json"]
    migrate = [
        "bd",
        "--db",
        str(beads_root / "beads.db"),
        "migrate",
        "--to-dolt",
        "--yes",
        "--json",
    ]
    stats_calls = 0
    calls: list[list[str]] = []
    diagnostics: list[str] = []

    def fake_run_with_runner(
        request: exec_util.CommandRequest,
    ) -> exec_util.CommandResult | None:
        nonlocal stats_calls
        argv = list(request.argv)
        calls.append(argv)
        if argv == ["bd", "stats", "--json"]:
            stats_calls += 1
            if stats_calls == 1:
                return exec_util.CommandResult(
                    argv=request.argv,
                    returncode=0,
                    stdout='{"summary":{"total_issues":2}}',
                    stderr="",
                )
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout='{"summary":{"total_issues":4}}',
                stderr="",
            )
        if argv == db_stats:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout='{"summary":{"total_issues":4}}',
                stderr="",
            )
        if argv == migrate:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout='{"migrated":4}',
                stderr="",
            )
        if argv == ["bd", "prime"]:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout="primed",
                stderr="",
            )
        raise AssertionError(f"unexpected command: {argv}")

    with (
        patch("atelier.beads.bd_invocation.ensure_supported_bd_version"),
        patch("atelier.beads.bd_invocation.detect_bd_version", return_value=(0, 56, 1)),
        patch("atelier.beads.exec.run_with_runner", side_effect=fake_run_with_runner),
        patch("atelier.beads.say", side_effect=diagnostics.append),
    ):
        result = beads.run_bd_command(["prime"], beads_root=beads_root, cwd=cwd)

    assert result.returncode == 0
    assert migrate in calls
    assert diagnostics
    assert "auto-upgrade migrated" in diagnostics[0]
    assert "active Dolt issue count (2) is below legacy SQLite issue count (4)" in diagnostics[0]


def test_run_bd_command_prime_blocks_auto_migration_for_old_bd_version(
    tmp_path: Path,
) -> None:
    beads_root = tmp_path / ".beads"
    beads_root.mkdir()
    (beads_root / "beads.db").write_bytes(b"legacy")
    cwd = tmp_path / "repo"
    cwd.mkdir()

    db_stats = ["bd", "--db", str(beads_root / "beads.db"), "stats", "--json"]
    calls: list[list[str]] = []

    def fake_run_with_runner(
        request: exec_util.CommandRequest,
    ) -> exec_util.CommandResult | None:
        argv = list(request.argv)
        calls.append(argv)
        if argv == ["bd", "stats", "--json"]:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=2,
                stdout="",
                stderr=(
                    "panic: runtime error: invalid memory address or nil pointer dereference\n"
                    "doltdb.(*DoltDB).SetCrashOnFatalError"
                ),
            )
        if argv == db_stats:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout='{"summary":{"total_issues":8}}',
                stderr="",
            )
        raise AssertionError(f"unexpected command: {argv}")

    def fake_die(message: str, code: int = 1) -> None:
        del code
        raise RuntimeError(message)

    with (
        patch("atelier.beads.bd_invocation.ensure_supported_bd_version"),
        patch("atelier.beads.bd_invocation.detect_bd_version", return_value=(0, 56, 0)),
        patch("atelier.beads.exec.run_with_runner", side_effect=fake_run_with_runner),
        patch("atelier.beads.die", side_effect=fake_die),
    ):
        with pytest.raises(RuntimeError, match="requires bd >= 0.56.1"):
            beads.run_bd_command(["prime"], beads_root=beads_root, cwd=cwd)

    assert ["bd", "prime"] not in calls
    assert not list((beads_root / "backups").glob("*.bak"))


def test_run_bd_command_prime_blocks_when_migration_parity_fails(
    tmp_path: Path,
) -> None:
    beads_root = tmp_path / ".beads"
    beads_root.mkdir()
    (beads_root / "beads.db").write_bytes(b"legacy")
    cwd = tmp_path / "repo"
    cwd.mkdir()

    db_stats = ["bd", "--db", str(beads_root / "beads.db"), "stats", "--json"]
    migrate = [
        "bd",
        "--db",
        str(beads_root / "beads.db"),
        "migrate",
        "--to-dolt",
        "--yes",
        "--json",
    ]
    stats_calls = 0
    calls: list[list[str]] = []

    def fake_run_with_runner(
        request: exec_util.CommandRequest,
    ) -> exec_util.CommandResult | None:
        nonlocal stats_calls
        argv = list(request.argv)
        calls.append(argv)
        if argv == ["bd", "stats", "--json"]:
            stats_calls += 1
            if stats_calls == 1:
                return exec_util.CommandResult(
                    argv=request.argv,
                    returncode=2,
                    stdout="",
                    stderr=(
                        "panic: runtime error: invalid memory address or nil pointer dereference\n"
                        "doltdb.(*DoltDB).SetCrashOnFatalError"
                    ),
                )
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout='{"summary":{"total_issues":3}}',
                stderr="",
            )
        if argv == db_stats:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout='{"summary":{"total_issues":8}}',
                stderr="",
            )
        if argv == migrate:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout='{"migrated":8}',
                stderr="",
            )
        raise AssertionError(f"unexpected command: {argv}")

    def fake_die(message: str, code: int = 1) -> None:
        del code
        raise RuntimeError(message)

    with (
        patch("atelier.beads.bd_invocation.ensure_supported_bd_version"),
        patch("atelier.beads.bd_invocation.detect_bd_version", return_value=(0, 56, 1)),
        patch("atelier.beads.exec.run_with_runner", side_effect=fake_run_with_runner),
        patch("atelier.beads.die", side_effect=fake_die),
    ):
        with pytest.raises(RuntimeError, match="parity verification failed"):
            beads.run_bd_command(["prime"], beads_root=beads_root, cwd=cwd)

    assert migrate in calls
    assert ["bd", "prime"] not in calls


def test_run_bd_command_prime_reconciles_runtime_agent_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    beads_root = tmp_path / ".beads"
    beads_root.mkdir()
    (beads_root / "beads.db").write_bytes(b"legacy")
    cwd = tmp_path / "repo"
    cwd.mkdir()
    monkeypatch.setenv("ATELIER_AGENT_BEAD_ID", "at-agent-runtime")
    monkeypatch.setenv("ATELIER_AGENT_ID", "atelier/planner/codex/runtime")

    db_stats = ["bd", "--db", str(beads_root / "beads.db"), "stats", "--json"]
    migrate = [
        "bd",
        "--db",
        str(beads_root / "beads.db"),
        "migrate",
        "--to-dolt",
        "--yes",
        "--json",
    ]
    stats_calls = 0
    show_calls = 0
    updated_descriptions: list[str] = []

    def fake_run_with_runner(
        request: exec_util.CommandRequest,
    ) -> exec_util.CommandResult | None:
        nonlocal stats_calls, show_calls
        argv = list(request.argv)
        if argv == ["bd", "stats", "--json"]:
            stats_calls += 1
            if stats_calls == 1:
                return exec_util.CommandResult(
                    argv=request.argv,
                    returncode=2,
                    stdout="",
                    stderr=(
                        "panic: runtime error: invalid memory address or nil pointer dereference\n"
                        "doltdb.(*DoltDB).SetCrashOnFatalError"
                    ),
                )
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout='{"summary":{"total_issues":8}}',
                stderr="",
            )
        if argv == db_stats:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout='{"summary":{"total_issues":8}}',
                stderr="",
            )
        if argv == ["bd", "show", "at-agent-runtime", "--json"]:
            show_calls += 1
            description = (
                "agent_id: atelier/planner/codex/runtime\nplanner_sync.last_synced_sha: fresh\n"
            )
            if show_calls > 1:
                description = (
                    "agent_id: atelier/planner/codex/runtime\nplanner_sync.last_synced_sha: stale\n"
                )
            payload = [
                {
                    "id": "at-agent-runtime",
                    "title": "atelier/planner/codex/runtime",
                    "labels": ["at:agent"],
                    "description": description,
                }
            ]
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout=json.dumps(payload),
                stderr="",
            )
        if argv == migrate:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout='{"migrated":8}',
                stderr="",
            )
        if argv[:3] == ["bd", "update", "at-agent-runtime"] and "--body-file" in argv:
            body_path = Path(argv[argv.index("--body-file") + 1])
            updated_descriptions.append(body_path.read_text(encoding="utf-8"))
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout="updated",
                stderr="",
            )
        if argv == ["bd", "prime"]:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout="primed",
                stderr="",
            )
        raise AssertionError(f"unexpected command: {argv}")

    with (
        patch("atelier.beads.bd_invocation.ensure_supported_bd_version"),
        patch("atelier.beads.bd_invocation.detect_bd_version", return_value=(0, 56, 1)),
        patch("atelier.beads.exec.run_with_runner", side_effect=fake_run_with_runner),
    ):
        result = beads.run_bd_command(["prime"], beads_root=beads_root, cwd=cwd)

    assert result.returncode == 0
    assert updated_descriptions
    assert "planner_sync.last_synced_sha: fresh" in updated_descriptions[0]
    assert "planner_sync.last_synced_sha: stale" not in updated_descriptions[0]


def test_run_bd_command_prime_recreates_missing_runtime_agent_bead(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    beads_root = tmp_path / ".beads"
    beads_root.mkdir()
    (beads_root / "beads.db").write_bytes(b"legacy")
    cwd = tmp_path / "repo"
    cwd.mkdir()
    monkeypatch.setenv("ATELIER_AGENT_BEAD_ID", "at-agent-required")
    monkeypatch.setenv("ATELIER_AGENT_ID", "atelier/planner/codex/runtime")

    db_stats = ["bd", "--db", str(beads_root / "beads.db"), "stats", "--json"]
    migrate = [
        "bd",
        "--db",
        str(beads_root / "beads.db"),
        "migrate",
        "--to-dolt",
        "--yes",
        "--json",
    ]
    stats_calls = 0
    create_calls: list[list[str]] = []

    def fake_run_with_runner(
        request: exec_util.CommandRequest,
    ) -> exec_util.CommandResult | None:
        nonlocal stats_calls
        argv = list(request.argv)
        if argv == ["bd", "stats", "--json"]:
            stats_calls += 1
            if stats_calls == 1:
                return exec_util.CommandResult(
                    argv=request.argv,
                    returncode=2,
                    stdout="",
                    stderr=(
                        "panic: runtime error: invalid memory address or nil pointer dereference\n"
                        "doltdb.(*DoltDB).SetCrashOnFatalError"
                    ),
                )
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout='{"summary":{"total_issues":2}}',
                stderr="",
            )
        if argv == db_stats:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout='{"summary":{"total_issues":2}}',
                stderr="",
            )
        if argv == ["bd", "show", "at-agent-required", "--json"]:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout="[]",
                stderr="",
            )
        if argv == migrate:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout='{"migrated":2}',
                stderr="",
            )
        if argv == ["bd", "types", "--json"]:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout='{"types":[{"name":"task"}]}',
                stderr="",
            )
        if argv[:2] == ["bd", "create"]:
            create_calls.append(argv)
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout="at-agent-required\n",
                stderr="",
            )
        if argv == ["bd", "prime"]:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout="primed",
                stderr="",
            )
        raise AssertionError(f"unexpected command: {argv}")

    with (
        patch("atelier.beads.bd_invocation.ensure_supported_bd_version"),
        patch("atelier.beads.bd_invocation.detect_bd_version", return_value=(0, 56, 1)),
        patch("atelier.beads.exec.run_with_runner", side_effect=fake_run_with_runner),
    ):
        result = beads.run_bd_command(["prime"], beads_root=beads_root, cwd=cwd)

    assert result.returncode == 0
    assert create_calls
    create_call = create_calls[0]
    assert "--id" in create_call
    assert create_call[create_call.index("--id") + 1] == "at-agent-required"
    assert "--description" in create_call
    description = create_call[create_call.index("--description") + 1]
    assert "agent_id: atelier/planner/codex/runtime" in description
    assert "role_type: planner" in description


def test_detect_startup_beads_state_reports_healthy_dolt(tmp_path: Path) -> None:
    beads_root = tmp_path / ".beads"
    (beads_root / "dolt" / "beads_at" / ".dolt").mkdir(parents=True)
    (beads_root / "beads.db").write_bytes(b"")
    cwd = tmp_path / "repo"
    cwd.mkdir()

    legacy_argv = ["bd", "--db", str(beads_root / "beads.db"), "stats", "--json"]

    def fake_run_with_runner(
        request: exec_util.CommandRequest,
    ) -> exec_util.CommandResult | None:
        argv = list(request.argv)
        if argv == ["bd", "stats", "--json"] or argv == legacy_argv:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout='{"summary":{"total_issues":12}}',
                stderr="",
            )
        raise AssertionError(f"unexpected command: {argv}")

    with patch("atelier.beads.exec.run_with_runner", side_effect=fake_run_with_runner):
        state = beads.detect_startup_beads_state(beads_root=beads_root, cwd=cwd)

    assert state.classification == "healthy_dolt"
    assert state.migration_eligible is False
    assert state.dolt_issue_total == 12
    assert state.legacy_issue_total == 12


def test_detect_startup_beads_state_reports_missing_dolt_with_legacy(
    tmp_path: Path,
) -> None:
    beads_root = tmp_path / ".beads"
    beads_root.mkdir()
    (beads_root / "beads.db").write_bytes(b"")
    cwd = tmp_path / "repo"
    cwd.mkdir()

    legacy_argv = ["bd", "--db", str(beads_root / "beads.db"), "stats", "--json"]

    def fake_run_with_runner(
        request: exec_util.CommandRequest,
    ) -> exec_util.CommandResult | None:
        argv = list(request.argv)
        if argv == ["bd", "stats", "--json"]:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=2,
                stdout="",
                stderr=(
                    "panic: runtime error: invalid memory address or nil pointer dereference\n"
                    "doltdb.(*DoltDB).SetCrashOnFatalError"
                ),
            )
        if argv == legacy_argv:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout='{"summary":{"total_issues":8}}',
                stderr="",
            )
        raise AssertionError(f"unexpected command: {argv}")

    with patch("atelier.beads.exec.run_with_runner", side_effect=fake_run_with_runner):
        state = beads.detect_startup_beads_state(beads_root=beads_root, cwd=cwd)

    assert state.classification == "missing_dolt_with_legacy_sqlite"
    assert state.migration_eligible is True
    assert state.dolt_issue_total is None
    assert state.legacy_issue_total == 8


def test_detect_startup_beads_state_reports_insufficient_dolt(tmp_path: Path) -> None:
    beads_root = tmp_path / ".beads"
    (beads_root / "dolt" / "beads_at" / ".dolt").mkdir(parents=True)
    (beads_root / "beads.db").write_bytes(b"")
    cwd = tmp_path / "repo"
    cwd.mkdir()

    legacy_argv = ["bd", "--db", str(beads_root / "beads.db"), "stats", "--json"]

    def fake_run_with_runner(
        request: exec_util.CommandRequest,
    ) -> exec_util.CommandResult | None:
        argv = list(request.argv)
        if argv == ["bd", "stats", "--json"]:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout='{"summary":{"total_issues":3}}',
                stderr="",
            )
        if argv == legacy_argv:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout='{"summary":{"total_issues":11}}',
                stderr="",
            )
        raise AssertionError(f"unexpected command: {argv}")

    with patch("atelier.beads.exec.run_with_runner", side_effect=fake_run_with_runner):
        state = beads.detect_startup_beads_state(beads_root=beads_root, cwd=cwd)

    assert state.classification == "insufficient_dolt_vs_legacy_data"
    assert state.migration_eligible is True
    assert state.dolt_issue_total == 3
    assert state.legacy_issue_total == 11


def test_run_bd_command_allows_changeset_in_progress_when_dependencies_closed(
    tmp_path: Path,
) -> None:
    beads_root = tmp_path / ".beads"
    beads_root.mkdir()
    cwd = tmp_path / "repo"
    cwd.mkdir()
    calls: list[list[str]] = []

    def fake_run_with_runner(
        request: exec_util.CommandRequest,
    ) -> exec_util.CommandResult | None:
        argv = list(request.argv)
        calls.append(argv)
        if argv == ["bd", "show", "at-2", "--json"]:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout=(
                    '[{"id":"at-2","status":"open","labels":[],'
                    '"dependencies":["at-1"],"type":"task"}]'
                ),
                stderr="",
            )
        if argv == ["bd", "show", "at-1", "--json"]:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout='[{"id":"at-1","status":"closed","labels":[],"type":"task"}]',
                stderr="",
            )
        if argv == ["bd", "list", "--parent", "at-2", "--json"]:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout="[]",
                stderr="",
            )
        if argv == ["bd", "update", "at-2", "--status", "in_progress"]:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout="updated\n",
                stderr="",
            )
        raise AssertionError(f"unexpected command: {argv}")

    with (
        patch("atelier.beads.bd_invocation.ensure_supported_bd_version"),
        patch("atelier.beads.exec.run_with_runner", side_effect=fake_run_with_runner),
    ):
        result = beads.run_bd_command(
            ["update", "at-2", "--status", "in_progress"],
            beads_root=beads_root,
            cwd=cwd,
        )

    assert result.returncode == 0
    assert ["bd", "show", "at-2", "--json"] in calls
    assert ["bd", "list", "--parent", "at-2", "--json"] in calls
    assert ["bd", "show", "at-1", "--json"] in calls
    assert ["bd", "update", "at-2", "--status", "in_progress"] in calls


def test_ensure_agent_bead_returns_existing() -> None:
    existing = {"id": "atelier-1", "title": "agent"}
    with patch("atelier.beads.find_agent_bead", return_value=existing):
        result = beads.ensure_agent_bead("agent", beads_root=Path("/beads"), cwd=Path("/repo"))
    assert result == existing


def test_find_agent_bead_uses_title_filter_and_exact_match() -> None:
    seen: dict[str, object] = {}

    def fake_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:
        seen["args"] = args
        return [
            {"id": "atelier-1", "title": "atelier/worker/codex/p123-extra"},
            {"id": "atelier-2", "title": "atelier/worker/codex/p123"},
        ]

    with patch("atelier.beads.run_bd_json", side_effect=fake_json):
        result = beads.find_agent_bead(
            "atelier/worker/codex/p123", beads_root=Path("/beads"), cwd=Path("/repo")
        )

    assert result == {"id": "atelier-2", "title": "atelier/worker/codex/p123"}
    assert seen["args"] == [
        "list",
        "--label",
        "at:agent",
        "--title",
        "atelier/worker/codex/p123",
    ]


def test_find_agent_bead_falls_back_to_description_agent_id() -> None:
    def fake_json(_args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:
        return [
            {
                "id": "atelier-2",
                "title": "planner",
                "description": "agent_id: atelier/planner/codex/p123\nrole_type: planner\n",
            }
        ]

    with patch("atelier.beads.run_bd_json", side_effect=fake_json):
        result = beads.find_agent_bead(
            "atelier/planner/codex/p123", beads_root=Path("/beads"), cwd=Path("/repo")
        )

    assert result == {
        "id": "atelier-2",
        "title": "planner",
        "description": "agent_id: atelier/planner/codex/p123\nrole_type: planner\n",
    }


def test_ensure_agent_bead_creates_when_missing() -> None:
    def fake_command(*_args, **_kwargs) -> CompletedProcess[str]:
        return CompletedProcess(args=["bd"], returncode=0, stdout="atelier-2\n", stderr="")

    def fake_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:
        if args[0] == "show":
            return [{"id": "atelier-2", "title": "agent"}]
        return []

    with (
        patch("atelier.beads.find_agent_bead", return_value=None),
        patch("atelier.beads._agent_issue_type", return_value="task"),
        patch("atelier.beads.run_bd_command", side_effect=fake_command),
        patch("atelier.beads.run_bd_json", side_effect=fake_json),
    ):
        result = beads.ensure_agent_bead(
            "agent", beads_root=Path("/beads"), cwd=Path("/repo"), role="worker"
        )

    assert result["id"] == "atelier-2"


def test_ensure_atelier_store_initializes_missing_root() -> None:
    with TemporaryDirectory() as tmp:
        beads_root = Path(tmp) / ".beads"
        with patch("atelier.beads.run_bd_command") as run_command:
            changed = beads.ensure_atelier_store(beads_root=beads_root, cwd=Path("/repo"))

    assert changed is True
    assert run_command.call_args.args[0] == ["init", "--prefix", "at", "--quiet"]


def test_ensure_atelier_store_skips_existing_root() -> None:
    with TemporaryDirectory() as tmp:
        beads_root = Path(tmp) / ".beads"
        beads_root.mkdir(parents=True)
        with patch("atelier.beads.run_bd_command") as run_command:
            changed = beads.ensure_atelier_store(beads_root=beads_root, cwd=Path("/repo"))

    assert changed is False
    run_command.assert_not_called()


def test_prime_addendum_returns_output() -> None:
    with patch(
        "atelier.beads.subprocess.run",
        return_value=CompletedProcess(
            args=["bd", "prime"], returncode=0, stdout="# Addendum\n", stderr=""
        ),
    ):
        value = beads.prime_addendum(beads_root=Path("/beads"), cwd=Path("/repo"))

    assert value == "# Addendum"


def test_prime_addendum_returns_none_on_error() -> None:
    with patch(
        "atelier.beads.subprocess.run",
        return_value=CompletedProcess(args=["bd", "prime"], returncode=1, stdout="", stderr="boom"),
    ):
        value = beads.prime_addendum(beads_root=Path("/beads"), cwd=Path("/repo"))

    assert value is None


def test_prime_addendum_returns_prime_output_without_rewriting() -> None:
    stdout = (
        "## Beads Workflow Context\n\n"
        "```\n"
        "[ ] bd sync --flush-only\n"
        "```\n"
        "- `bd sync` exports JSONL.\n"
    )
    with patch(
        "atelier.beads.subprocess.run",
        return_value=CompletedProcess(args=["bd", "prime"], returncode=0, stdout=stdout, stderr=""),
    ):
        value = beads.prime_addendum(beads_root=Path("/beads"), cwd=Path("/repo"))

    assert value == stdout.strip()


def test_ensure_issue_prefix_noop_when_already_expected() -> None:
    with (
        patch("atelier.beads._current_issue_prefix", return_value="at"),
        patch("atelier.beads.run_bd_command") as run_command,
    ):
        changed = beads.ensure_issue_prefix("at", beads_root=Path("/beads"), cwd=Path("/repo"))

    assert changed is False
    run_command.assert_not_called()


def test_ensure_issue_prefix_updates_when_mismatched() -> None:
    calls: list[list[str]] = []

    def fake_command(
        args: list[str], *, beads_root: Path, cwd: Path, allow_failure: bool = False
    ) -> CompletedProcess[str]:
        calls.append(args)
        return CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    with (
        patch("atelier.beads._current_issue_prefix", return_value="atelier"),
        patch("atelier.beads.run_bd_command", side_effect=fake_command),
    ):
        changed = beads.ensure_issue_prefix("at", beads_root=Path("/beads"), cwd=Path("/repo"))

    assert changed is True
    assert calls[0] == ["config", "set", "issue_prefix", "at"]
    assert calls[1] == ["rename-prefix", "at-", "--repair"]


def test_claim_epic_updates_assignee_and_status() -> None:
    issue = {"id": "atelier-9", "labels": [], "assignee": None}
    updated = {"id": "atelier-9", "labels": ["at:hooked"], "assignee": "agent"}

    def fake_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:
        if args and args[0] == "show":
            return [updated]
        return [issue]

    with (
        patch("atelier.beads.run_bd_json", side_effect=fake_json),
        patch("atelier.beads.run_bd_command") as run_command,
    ):
        beads.claim_epic(
            "atelier-9",
            "agent",
            beads_root=Path("/beads"),
            cwd=Path("/repo"),
        )

    called_args = run_command.call_args.args[0]
    assert "update" in called_args
    assert "--assignee" in called_args
    assert "--status" in called_args
    assert "hooked" in called_args


def test_claim_epic_allows_expected_takeover() -> None:
    issue = {"id": "atelier-9", "labels": [], "assignee": "agent-old"}
    updated = {"id": "atelier-9", "labels": ["at:hooked"], "assignee": "agent-new"}

    def fake_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:
        if args and args[0] == "show":
            return [updated]
        return [issue]

    with (
        patch("atelier.beads.run_bd_json", side_effect=fake_json),
        patch("atelier.beads.run_bd_command") as run_command,
    ):
        beads.claim_epic(
            "atelier-9",
            "agent-new",
            beads_root=Path("/beads"),
            cwd=Path("/repo"),
            allow_takeover_from="agent-old",
        )

    called_args = run_command.call_args.args[0]
    assert "--assignee" in called_args
    assert "agent-new" in called_args


def test_claim_epic_blocks_planner_owned_executable_work() -> None:
    issue = {
        "id": "atelier-9",
        "status": "open",
        "labels": ["at:epic"],
        "assignee": "atelier/planner/codex/p111",
    }

    with (
        patch("atelier.beads.run_bd_json", return_value=[issue]),
        patch("atelier.beads.die", side_effect=RuntimeError("die called")) as die_fn,
    ):
        with pytest.raises(RuntimeError, match="die called"):
            beads.claim_epic(
                "atelier-9",
                "atelier/worker/codex/p222",
                beads_root=Path("/beads"),
                cwd=Path("/repo"),
            )
    assert "planner agents cannot own executable work" in str(die_fn.call_args.args[0])


def test_claim_epic_rejects_planner_claimant_for_executable_work() -> None:
    issue = {
        "id": "atelier-9",
        "status": "open",
        "labels": ["at:epic"],
        "assignee": None,
    }

    with (
        patch("atelier.beads.run_bd_json", return_value=[issue]),
        patch("atelier.beads.run_bd_command") as run_command,
        patch("atelier.beads.die", side_effect=RuntimeError("die called")) as die_fn,
    ):
        with pytest.raises(RuntimeError, match="die called"):
            beads.claim_epic(
                "atelier-9",
                "atelier/planner/codex/p111",
                beads_root=Path("/beads"),
                cwd=Path("/repo"),
            )
    run_command.assert_not_called()
    assert "planner agents cannot claim executable work" in str(die_fn.call_args.args[0])


def test_claim_epic_backfills_epic_label_for_standalone_changeset() -> None:
    issue = {
        "id": "at-legacy",
        "status": "open",
        "labels": [],
        "assignee": None,
        "type": "task",
    }
    updated = {
        "id": "at-legacy",
        "status": "in_progress",
        "labels": ["at:epic", "at:hooked"],
        "assignee": "agent",
    }
    show_calls = 0

    def fake_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:
        nonlocal show_calls
        if args and args[0] == "show":
            show_calls += 1
            return [issue] if show_calls == 1 else [updated]
        if args[:2] == ["list", "--parent"]:
            return []
        return [issue]

    with (
        patch("atelier.beads.run_bd_json", side_effect=fake_json),
        patch("atelier.beads.run_bd_command") as run_command,
    ):
        beads.claim_epic(
            "at-legacy",
            "agent",
            beads_root=Path("/beads"),
            cwd=Path("/repo"),
        )

    called_args = run_command.call_args.args[0]
    assert called_args.count("--add-label") == 2
    assert "at:hooked" in called_args
    assert "at:epic" in called_args


def test_claim_epic_rejects_executable_work_without_active_status() -> None:
    issue = {"id": "at-legacy", "labels": ["at:epic"], "assignee": None}

    with (
        patch("atelier.beads.run_bd_json", return_value=[issue]),
        patch("atelier.beads.die", side_effect=RuntimeError("die called")) as die_fn,
    ):
        with pytest.raises(RuntimeError, match="die called"):
            beads.claim_epic(
                "at-legacy",
                "agent",
                beads_root=Path("/beads"),
                cwd=Path("/repo"),
            )

    assert "not claimable under lifecycle contract (status=missing)" in str(
        die_fn.call_args.args[0]
    )


def test_claim_epic_rejects_deferred_executable_work() -> None:
    issue = {
        "id": "at-legacy",
        "status": "deferred",
        "labels": ["at:epic"],
        "assignee": None,
    }

    with (
        patch("atelier.beads.run_bd_json", return_value=[issue]),
        patch("atelier.beads.die", side_effect=RuntimeError("die called")) as die_fn,
    ):
        with pytest.raises(RuntimeError, match="die called"):
            beads.claim_epic(
                "at-legacy",
                "agent",
                beads_root=Path("/beads"),
                cwd=Path("/repo"),
            )

    assert "not claimable under lifecycle contract (status=deferred)" in str(
        die_fn.call_args.args[0]
    )


def test_set_agent_hook_updates_description() -> None:
    issue = {"id": "atelier-agent", "description": "role: worker\n"}
    captured: dict[str, str] = {}
    called: dict[str, list[str]] = {}

    def fake_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:
        return [issue]

    def fake_command(
        args: list[str], *, beads_root: Path, cwd: Path, allow_failure: bool = False
    ) -> CompletedProcess[str]:
        called["args"] = args
        return CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    def fake_update(issue_id: str, description: str, *, beads_root: Path, cwd: Path) -> None:
        captured["id"] = issue_id
        captured["description"] = description

    with (
        patch("atelier.beads.run_bd_json", side_effect=fake_json),
        patch("atelier.beads.run_bd_command", side_effect=fake_command),
        patch("atelier.beads._update_issue_description", side_effect=fake_update),
    ):
        beads.set_agent_hook(
            "atelier-agent",
            "atelier-epic",
            beads_root=Path("/beads"),
            cwd=Path("/repo"),
        )

    assert captured["id"] == "atelier-agent"
    assert "hook_bead: atelier-epic" in captured["description"]
    assert called["args"][:3] == ["slot", "set", "atelier-agent"]


def test_update_changeset_branch_metadata_skips_base_overwrite_by_default() -> None:
    issue = {
        "id": "at-1.1",
        "description": (
            "changeset.root_branch: feat/root\n"
            "changeset.parent_branch: main\n"
            "changeset.work_branch: feat/root-at-1.1\n"
            "changeset.root_base: aaa111\n"
            "changeset.parent_base: bbb222\n"
        ),
    }

    with (
        patch("atelier.beads.run_bd_json", return_value=[issue]),
        patch("atelier.beads._update_issue_description") as update_desc,
    ):
        result = beads.update_changeset_branch_metadata(
            "at-1.1",
            root_branch="feat/root",
            parent_branch="main",
            work_branch="feat/root-at-1.1",
            root_base="ccc333",
            parent_base="ddd444",
            beads_root=Path("/beads"),
            cwd=Path("/repo"),
        )

    update_desc.assert_not_called()
    assert result == issue


def test_get_agent_hook_prefers_slot() -> None:
    issue = {"id": "atelier-agent", "description": "hook_bead: epic-2\n"}

    def fake_command(
        args: list[str], *, beads_root: Path, cwd: Path, allow_failure: bool = False
    ) -> CompletedProcess[str]:
        return CompletedProcess(args=args, returncode=0, stdout='{"hook":"epic-1"}\n', stderr="")

    def fake_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:
        return [issue]

    with (
        patch("atelier.beads.run_bd_command", side_effect=fake_command),
        patch("atelier.beads.run_bd_json", side_effect=fake_json),
    ):
        hook = beads.get_agent_hook("atelier-agent", beads_root=Path("/beads"), cwd=Path("/repo"))

    assert hook == "epic-1"


def test_get_agent_hook_falls_back_to_description() -> None:
    issue = {"id": "atelier-agent", "description": "hook_bead: epic-2\n"}

    def fake_command(
        args: list[str], *, beads_root: Path, cwd: Path, allow_failure: bool = False
    ) -> CompletedProcess[str]:
        return CompletedProcess(args=args, returncode=1, stdout="", stderr="err")

    def fake_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:
        return [issue]

    with (
        patch("atelier.beads.run_bd_command", side_effect=fake_command),
        patch("atelier.beads.run_bd_json", side_effect=fake_json),
    ):
        hook = beads.get_agent_hook("atelier-agent", beads_root=Path("/beads"), cwd=Path("/repo"))

    assert hook == "epic-2"


def test_get_agent_hook_backfills_slot() -> None:
    issue = {"id": "atelier-agent", "description": "hook_bead: epic-2\n"}
    calls: list[list[str]] = []

    def fake_command(
        args: list[str], *, beads_root: Path, cwd: Path, allow_failure: bool = False
    ) -> CompletedProcess[str]:
        calls.append(args)
        if args[:2] == ["slot", "show"]:
            return CompletedProcess(args=args, returncode=0, stdout="{}\n", stderr="")
        return CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    def fake_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:
        return [issue]

    with (
        patch("atelier.beads.run_bd_command", side_effect=fake_command),
        patch("atelier.beads.run_bd_json", side_effect=fake_json),
    ):
        hook = beads.get_agent_hook("atelier-agent", beads_root=Path("/beads"), cwd=Path("/repo"))

    assert hook == "epic-2"
    assert any(args[:2] == ["slot", "set"] for args in calls)


def test_create_message_bead_renders_frontmatter() -> None:
    with (
        patch("atelier.beads.messages.render_message", return_value="body"),
        patch("atelier.beads._create_issue_with_body", return_value="atelier-55"),
        patch(
            "atelier.beads.run_bd_json",
            return_value=[{"id": "atelier-55", "title": "Hello"}],
        ),
    ):
        result = beads.create_message_bead(
            subject="Hello",
            body="Hi",
            metadata={"from": "alice"},
            assignee="bob",
            beads_root=Path("/beads"),
            cwd=Path("/repo"),
        )
    assert result["id"] == "atelier-55"


def test_claim_queue_message_sets_claimed_metadata() -> None:
    description = "---\nqueue: triage\n---\n\nBody\n"
    issue = {"id": "msg-1", "description": description}
    captured: dict[str, str] = {}

    def fake_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:
        return [issue]

    def fake_update(issue_id: str, description: str, *, beads_root: Path, cwd: Path) -> None:
        captured["id"] = issue_id
        captured["description"] = description

    with (
        patch("atelier.beads.run_bd_json", side_effect=fake_json),
        patch("atelier.beads._update_issue_description", side_effect=fake_update),
    ):
        beads.claim_queue_message(
            "msg-1",
            "atelier/worker/agent",
            beads_root=Path("/beads"),
            cwd=Path("/repo"),
        )

    assert captured["id"] == "msg-1"
    assert "claimed_by: atelier/worker/agent" in captured["description"]
    assert "claimed_at:" in captured["description"]


def test_list_inbox_messages_filters_unread() -> None:
    with patch("atelier.beads.run_bd_json", return_value=[{"id": "atelier-77"}]) as run_json:
        result = beads.list_inbox_messages("alice", beads_root=Path("/beads"), cwd=Path("/repo"))
    assert result
    called_args = run_json.call_args.args[0]
    assert "--label" in called_args
    assert "at:unread" in called_args


def test_list_queue_messages_filters_unread_by_default() -> None:
    with patch("atelier.beads.run_bd_json", return_value=[]) as run_json:
        beads.list_queue_messages(beads_root=Path("/beads"), cwd=Path("/repo"))
    called_args = run_json.call_args.args[0]
    assert called_args == ["list", "--label", "at:message", "--label", "at:unread"]


def test_list_queue_messages_can_include_read_messages() -> None:
    with patch("atelier.beads.run_bd_json", return_value=[]) as run_json:
        beads.list_queue_messages(beads_root=Path("/beads"), cwd=Path("/repo"), unread_only=False)
    called_args = run_json.call_args.args[0]
    assert called_args == ["list", "--label", "at:message"]


def test_mark_message_read_updates_labels() -> None:
    with patch("atelier.beads.run_bd_command") as run_command:
        beads.mark_message_read("atelier-88", beads_root=Path("/beads"), cwd=Path("/repo"))
    called_args = run_command.call_args.args[0]
    assert "update" in called_args
    assert "--remove-label" in called_args


def test_list_descendant_changesets_walks_tree() -> None:
    calls: list[str] = []
    work = lambda i: {"id": i, "labels": [], "type": "task"}

    def fake_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:
        parent = args[2]
        calls.append(parent)
        if parent == "epic-1":
            return [work("epic-1.1"), work("epic-1.2")]
        if parent == "epic-1.1":
            return [work("epic-1.1.1")]
        return []

    with patch("atelier.beads.run_bd_json", side_effect=fake_json):
        issues = beads.list_descendant_changesets(
            "epic-1", beads_root=Path("/beads"), cwd=Path("/repo")
        )

    ids = [issue["id"] for issue in issues]
    assert set(ids) == {"epic-1.2", "epic-1.1.1"}
    assert len(ids) == 2
    assert set(calls) == {"epic-1", "epic-1.1", "epic-1.2", "epic-1.1.1"}


def test_list_child_changesets_uses_graph_inference() -> None:
    """list_child_changesets infers leaf work beads from graph."""
    with patch("atelier.beads.run_bd_json", return_value=[]) as run_json:
        beads.list_child_changesets("epic-1", beads_root=Path("/beads"), cwd=Path("/repo"))
    calls = [c.args[0] for c in run_json.call_args_list]
    assert any(
        args[:3] == ["list", "--parent", "epic-1"] and "--label" not in args for args in calls
    )


def test_list_epics_uses_at_epic_and_all() -> None:
    """Regression: list_epics must use --label at:epic --all to avoid default caps."""
    with patch("atelier.beads.run_bd_json", return_value=[]) as run_json:
        beads.list_epics(beads_root=Path("/beads"), cwd=Path("/repo"), include_closed=True)
    called_args = run_json.call_args.args[0]
    assert "list" in called_args
    assert "--label" in called_args
    assert "at:epic" in called_args
    assert "--all" in called_args


def test_list_epics_finds_epic_beyond_default_window() -> None:
    """Regression: high-churn store with non-epics exceeding default list window."""
    epic = {"id": "at-epic", "status": "open", "labels": ["at:epic"]}

    def fake_run(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:
        if "at:epic" in args and "--all" in args:
            return [epic]
        return []

    with patch("atelier.beads.run_bd_json", side_effect=fake_run):
        result = beads.list_epics(
            beads_root=Path("/beads"), cwd=Path("/repo"), include_closed=False
        )
    assert len(result) == 1
    assert result[0]["id"] == "at-epic"


def test_summarize_changesets_counts_and_ready() -> None:
    changesets = [
        {"status": "closed", "description": "pr_state: merged\n"},
        {"status": "closed", "description": "pr_state: closed\n"},
        {"status": "open"},
    ]
    summary = beads.summarize_changesets(changesets, ready=[changesets[2]])
    assert summary.total == 3
    assert summary.ready == 1
    assert summary.merged == 1
    assert summary.abandoned == 1
    assert summary.remaining == 1
    assert summary.ready_to_close is False


def test_epic_changeset_summary_ready_to_close() -> None:
    def work(i: str, s: str = "open") -> dict:
        closed_desc = "\npr_state: merged\n" if s == "closed" else ""
        return {
            "id": i,
            "status": s,
            "labels": [],
            "type": "task",
            "description": closed_desc,
        }

    changesets = {
        "epic-1": [work("epic-1.1", "closed")],
        "epic-1.1": [work("epic-1.1.1", "closed")],
        "epic-1.1.1": [],
    }

    def fake_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:
        if args[:2] == ["show", "epic-1"]:
            return [{"id": "epic-1", "labels": ["at:epic"]}]
        if args[:2] == ["list", "--parent"]:
            return changesets.get(args[2], [])
        return []

    with patch("atelier.beads.run_bd_json", side_effect=fake_json):
        summary = beads.epic_changeset_summary(
            "epic-1", beads_root=Path("/beads"), cwd=Path("/repo")
        )

    assert summary.ready_to_close is True


def test_close_epic_if_complete_closes_and_clears_hook() -> None:
    work = lambda i, s="open": {"id": i, "status": s, "labels": [], "type": "task"}
    changesets = {
        "epic-1": [work("epic-1.1", "closed")],
        "epic-1.1": [],
    }

    def fake_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:
        if args[:2] == ["show", "epic-1"]:
            return [{"id": "epic-1", "labels": ["at:epic"]}]
        if args[:2] == ["list", "--parent"]:
            return changesets.get(args[2], [])
        return []

    with (
        patch("atelier.beads.run_bd_json", side_effect=fake_json),
        patch("atelier.beads.close_issue") as close_issue,
        patch("atelier.beads.clear_agent_hook") as clear_hook,
    ):
        result = beads.close_epic_if_complete(
            "epic-1",
            "agent-1",
            beads_root=Path("/beads"),
            cwd=Path("/repo"),
            confirm=lambda _summary: True,
        )

    assert result is True
    close_issue.assert_called_once_with(
        "epic-1",
        beads_root=Path("/beads"),
        cwd=Path("/repo"),
    )
    clear_hook.assert_called_once()


def test_close_epic_if_complete_respects_confirm() -> None:
    changesets = {
        "epic-1": [{"id": "epic-1.1", "status": "closed"}],
        "epic-1.1": [],
    }

    def fake_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:
        if args[:2] == ["list", "--parent"]:
            return changesets.get(args[2], [])
        return []

    with (
        patch("atelier.beads.run_bd_json", side_effect=fake_json),
        patch("atelier.beads.close_issue") as close_issue,
        patch("atelier.beads.clear_agent_hook"),
    ):
        result = beads.close_epic_if_complete(
            "epic-1",
            "agent-1",
            beads_root=Path("/beads"),
            cwd=Path("/repo"),
            confirm=lambda _summary: False,
        )

    assert result is False
    close_issue.assert_not_called()


def test_close_epic_if_complete_closes_standalone_changeset() -> None:
    def fake_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:
        if args[:2] == ["show", "at-irs"]:
            return [
                {
                    "id": "at-irs",
                    "labels": [],
                    "status": "closed",
                }
            ]
        if args[:2] == ["list", "--parent"]:
            return []
        return []

    with (
        patch("atelier.beads.run_bd_json", side_effect=fake_json),
        patch("atelier.beads.close_issue") as close_issue,
        patch("atelier.beads.clear_agent_hook") as clear_hook,
    ):
        result = beads.close_epic_if_complete(
            "at-irs",
            "agent-1",
            beads_root=Path("/beads"),
            cwd=Path("/repo"),
        )

    assert result is True
    close_issue.assert_called_once_with(
        "at-irs",
        beads_root=Path("/beads"),
        cwd=Path("/repo"),
    )
    clear_hook.assert_called_once()


def test_close_issue_runs_close_and_reconciles_on_success() -> None:
    completed = CompletedProcess(
        args=["bd", "close", "at-1"],
        returncode=0,
        stdout="",
        stderr="",
    )
    with (
        patch("atelier.beads.run_bd_command", return_value=completed) as run_command,
        patch("atelier.beads.reconcile_closed_issue_exported_github_tickets") as reconcile,
    ):
        result = beads.close_issue(
            "at-1",
            beads_root=Path("/beads"),
            cwd=Path("/repo"),
        )

    assert result.returncode == 0
    run_command.assert_called_once_with(
        ["close", "at-1"],
        beads_root=Path("/beads"),
        cwd=Path("/repo"),
        allow_failure=False,
    )
    reconcile.assert_called_once_with(
        "at-1",
        beads_root=Path("/beads"),
        cwd=Path("/repo"),
    )


def test_close_issue_skips_reconcile_when_close_fails_with_allow_failure() -> None:
    failed = CompletedProcess(
        args=["bd", "close", "at-1"],
        returncode=1,
        stdout="",
        stderr="failed",
    )
    with (
        patch("atelier.beads.run_bd_command", return_value=failed) as run_command,
        patch("atelier.beads.reconcile_closed_issue_exported_github_tickets") as reconcile,
    ):
        result = beads.close_issue(
            "at-1",
            beads_root=Path("/beads"),
            cwd=Path("/repo"),
            allow_failure=True,
        )

    assert result.returncode == 1
    run_command.assert_called_once_with(
        ["close", "at-1"],
        beads_root=Path("/beads"),
        cwd=Path("/repo"),
        allow_failure=True,
    )
    reconcile.assert_not_called()


def test_update_changeset_review_updates_description() -> None:
    issue = {"id": "atelier-99", "description": "scope: demo\n"}
    captured: dict[str, str] = {}

    def fake_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:
        return [issue]

    def fake_update(issue_id: str, description: str, *, beads_root: Path, cwd: Path) -> None:
        captured["id"] = issue_id
        captured["description"] = description

    with (
        patch("atelier.beads.run_bd_json", side_effect=fake_json),
        patch("atelier.beads._update_issue_description", side_effect=fake_update),
    ):
        beads.update_changeset_review(
            "atelier-99",
            beads.changesets.ReviewMetadata(pr_state="review"),
            beads_root=Path("/beads"),
            cwd=Path("/repo"),
        )

    assert captured["id"] == "atelier-99"
    assert "pr_state: review" in captured["description"]


def test_update_changeset_review_feedback_cursor_updates_description() -> None:
    issue = {"id": "atelier-99", "description": "scope: demo\n"}
    captured: dict[str, str] = {}

    def fake_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:
        return [issue]

    def fake_update(issue_id: str, description: str, *, beads_root: Path, cwd: Path) -> None:
        captured["id"] = issue_id
        captured["description"] = description

    with (
        patch("atelier.beads.run_bd_json", side_effect=fake_json),
        patch("atelier.beads._update_issue_description", side_effect=fake_update),
    ):
        beads.update_changeset_review_feedback_cursor(
            "atelier-99",
            "2026-02-20T12:00:00Z",
            beads_root=Path("/beads"),
            cwd=Path("/repo"),
        )

    assert captured["id"] == "atelier-99"
    assert "review.last_feedback_seen_at: 2026-02-20T12:00:00Z" in captured["description"]


def test_update_worktree_path_writes_description() -> None:
    issue = {"id": "epic-1", "description": "workspace.root_branch: main\n"}
    captured: dict[str, str] = {}

    def fake_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:
        return [issue]

    def fake_update(issue_id: str, description: str, *, beads_root: Path, cwd: Path) -> None:
        captured["id"] = issue_id
        captured["description"] = description

    with (
        patch("atelier.beads.run_bd_json", side_effect=fake_json),
        patch("atelier.beads._update_issue_description", side_effect=fake_update),
    ):
        beads.update_worktree_path(
            "epic-1", "worktrees/epic-1", beads_root=Path("/beads"), cwd=Path("/repo")
        )

    assert captured["id"] == "epic-1"
    assert "worktree_path: worktrees/epic-1" in captured["description"]


def test_parse_external_tickets_reads_json() -> None:
    description = 'external_tickets: [{"provider":"GitHub","id":"123","url":"u","relation":"Primary","direction":"import","sync_mode":"pull","state":"In-Progress","raw_state":"In Progress","state_updated_at":"2026-02-08T10:00:00Z","parent_id":"P-1","on_close":"Close","last_synced_at":"2026-02-08T11:00:00Z"}]\nscope: demo\n'
    tickets = beads.parse_external_tickets(description)
    assert len(tickets) == 1
    ticket = tickets[0]
    assert ticket.provider == "github"
    assert ticket.ticket_id == "123"
    assert ticket.url == "u"
    assert ticket.relation == "primary"
    assert ticket.direction == "imported"
    assert ticket.sync_mode == "import"
    assert ticket.state == "in_progress"
    assert ticket.raw_state == "In Progress"
    assert ticket.state_updated_at == "2026-02-08T10:00:00Z"
    assert ticket.parent_id == "P-1"
    assert ticket.on_close == "close"
    assert ticket.last_synced_at == "2026-02-08T11:00:00Z"


def test_update_external_tickets_updates_labels() -> None:
    issue = {"id": "issue-1", "description": "scope: demo\n", "labels": ["ext:github"]}
    captured: dict[str, object] = {"commands": []}

    def fake_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:
        return [issue]

    def fake_command(args: list[str], *, beads_root: Path, cwd: Path) -> None:
        captured["commands"].append(args)

    def fake_update(issue_id: str, description: str, *, beads_root: Path, cwd: Path) -> None:
        captured["description"] = description

    with (
        patch("atelier.beads.run_bd_json", side_effect=fake_json),
        patch("atelier.beads.run_bd_command", side_effect=fake_command),
        patch("atelier.beads._update_issue_description", side_effect=fake_update),
    ):
        beads.update_external_tickets(
            "issue-1",
            [beads.ExternalTicketRef(provider="jira", ticket_id="J-1")],
            beads_root=Path("/beads"),
            cwd=Path("/repo"),
        )

    assert "external_tickets:" in str(captured.get("description", ""))
    update_calls = [cmd for cmd in captured["commands"] if cmd and cmd[0] == "update"]
    assert update_calls
    combined = " ".join(update_calls[0])
    assert "--add-label" in combined
    assert "ext:jira" in combined
    assert "--remove-label" in combined
    assert "ext:github" in combined


def test_reconcile_closed_issue_exported_github_tickets_closes_and_updates() -> None:
    ticket_json = json.dumps(
        [
            {
                "provider": "github",
                "id": "175",
                "url": "https://api.github.com/repos/acme/widgets/issues/175",
                "relation": "primary",
                "direction": "exported",
                "sync_mode": "export",
                "state": "open",
                "parent_id": "174",
            }
        ]
    )
    issue = {
        "id": "at-4kv",
        "status": "closed",
        "description": f"external_tickets: {ticket_json}\n",
    }
    refreshed = beads.ExternalTicketRef(
        provider="github",
        ticket_id="175",
        url="https://github.com/acme/widgets/issues/175",
        state="closed",
        raw_state="completed",
        state_updated_at="2026-02-25T21:00:00Z",
        parent_id="200",
    )
    captured: dict[str, object] = {}

    def fake_update(
        issue_id: str,
        tickets: list[beads.ExternalTicketRef],
        *,
        beads_root: Path,
        cwd: Path,
    ) -> dict[str, object]:
        captured["issue_id"] = issue_id
        captured["tickets"] = tickets
        return {}

    with (
        patch("atelier.beads.run_bd_json", return_value=[issue]),
        patch("atelier.beads.update_external_tickets", side_effect=fake_update),
        patch(
            "atelier.github_issues_provider.GithubIssuesProvider.close_ticket",
            return_value=refreshed,
        ),
    ):
        result = beads.reconcile_closed_issue_exported_github_tickets(
            "at-4kv",
            beads_root=Path("/beads"),
            cwd=Path("/repo"),
        )

    assert result.stale_exported_github_tickets == 1
    assert result.reconciled_tickets == 1
    assert result.updated is True
    assert result.needs_decision_notes == tuple()
    assert captured["issue_id"] == "at-4kv"
    updated_tickets = captured["tickets"]
    assert isinstance(updated_tickets, list)
    assert updated_tickets[0].state == "closed"
    assert updated_tickets[0].state_updated_at == "2026-02-25T21:00:00Z"
    assert updated_tickets[0].parent_id == "200"
    assert updated_tickets[0].last_synced_at is not None


def test_reconcile_closed_issue_exported_github_tickets_adds_note_on_missing_repo() -> None:
    ticket_json = json.dumps(
        [
            {
                "provider": "github",
                "id": "176",
                "relation": "primary",
                "direction": "exported",
                "sync_mode": "export",
                "state": "open",
            }
        ]
    )
    issue = {
        "id": "at-4kv",
        "status": "closed",
        "description": f"external_tickets: {ticket_json}\n",
    }
    notes: list[str] = []

    def fake_command(
        args: list[str],
        *,
        beads_root: Path,
        cwd: Path,
        allow_failure: bool = False,
    ) -> None:
        if "--append-notes" in args:
            notes.append(args[-1])

    with (
        patch("atelier.beads.run_bd_json", return_value=[issue]),
        patch("atelier.beads.run_bd_command", side_effect=fake_command),
        patch("atelier.beads.update_external_tickets") as update_external,
    ):
        result = beads.reconcile_closed_issue_exported_github_tickets(
            "at-4kv",
            beads_root=Path("/beads"),
            cwd=Path("/repo"),
        )

    assert result.stale_exported_github_tickets == 1
    assert result.reconciled_tickets == 0
    assert result.updated is False
    assert result.needs_decision_notes
    assert any("missing repo slug" in note for note in result.needs_decision_notes)
    assert any(note.startswith("external_close_pending:") for note in notes)
    update_external.assert_not_called()


def test_reconcile_closed_issue_exported_github_tickets_skips_policy_opt_outs() -> None:
    ticket_json = json.dumps(
        [
            {
                "provider": "github",
                "id": "177",
                "url": "https://github.com/acme/widgets/issues/177",
                "relation": "context",
                "direction": "exported",
                "sync_mode": "export",
                "state": "open",
            },
            {
                "provider": "github",
                "id": "178",
                "url": "https://github.com/acme/widgets/issues/178",
                "relation": "primary",
                "direction": "exported",
                "sync_mode": "export",
                "state": "open",
                "on_close": "none",
            },
        ]
    )
    issue = {
        "id": "at-4kv",
        "status": "closed",
        "description": f"external_tickets: {ticket_json}\n",
    }
    with (
        patch("atelier.beads.run_bd_json", return_value=[issue]),
        patch("atelier.beads.update_external_tickets") as update_external,
        patch("atelier.github_issues_provider.GithubIssuesProvider.close_ticket") as close_ticket,
    ):
        result = beads.reconcile_closed_issue_exported_github_tickets(
            "at-4kv",
            beads_root=Path("/beads"),
            cwd=Path("/repo"),
        )

    assert result.stale_exported_github_tickets == 2
    assert result.reconciled_tickets == 0
    assert result.updated is False
    assert result.needs_decision_notes == tuple()
    close_ticket.assert_not_called()
    update_external.assert_not_called()


def test_merge_description_preserving_metadata_keeps_external_tickets() -> None:
    existing = (
        'scope: old\nexternal_tickets: [{"provider":"github","id":"174","direction":"export"}]\n'
    )
    next_description = "Intent\nupdated details\n"

    merged = beads.merge_description_preserving_metadata(existing, next_description)

    assert "Intent" in merged
    assert "external_tickets:" in merged
    assert '"id":"174"' in merged


def test_close_epic_if_complete_reconciles_exported_github_tickets() -> None:
    issue = {"id": "at-4kv", "labels": ["at:epic"], "status": "open"}
    summary = beads.ChangesetSummary(total=1, ready=0, merged=1, abandoned=0, remaining=0)

    with (
        patch("atelier.beads.run_bd_json", return_value=[issue]),
        patch("atelier.beads.epic_changeset_summary", return_value=summary),
        patch("atelier.beads.close_issue") as close_issue,
    ):
        closed = beads.close_epic_if_complete(
            "at-4kv",
            agent_bead_id=None,
            beads_root=Path("/beads"),
            cwd=Path("/repo"),
        )

    assert closed is True
    close_issue.assert_called_once_with(
        "at-4kv",
        beads_root=Path("/beads"),
        cwd=Path("/repo"),
    )


def test_list_external_ticket_metadata_gaps_detects_missing_field() -> None:
    issue = {
        "id": "at-73j",
        "labels": ["at:epic", "ext:github"],
        "description": "Intent\nno metadata yet\n",
    }
    with patch("atelier.beads.run_bd_json", return_value=[issue]):
        gaps = beads.list_external_ticket_metadata_gaps(
            beads_root=Path("/beads"),
            cwd=Path("/repo"),
        )

    assert len(gaps) == 1
    assert gaps[0].issue_id == "at-73j"
    assert gaps[0].providers == ("github",)


def _seed_events_db(
    db_path: Path, *, issue_id: str, old_description: str, new_description: str
) -> None:
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                issue_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                actor TEXT NOT NULL,
                old_value TEXT,
                new_value TEXT,
                comment TEXT,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.execute(
            """
            INSERT INTO events (issue_id, event_type, actor, old_value, new_value)
            VALUES (?, 'updated', 'test-agent', ?, ?)
            """,
            (
                issue_id,
                json.dumps({"description": old_description}),
                json.dumps({"description": new_description}),
            ),
        )
        connection.commit()


def test_recover_external_tickets_from_history_returns_latest_recorded_metadata() -> None:
    with TemporaryDirectory() as tmp:
        beads_root = Path(tmp)
        db_path = beads_root / "beads.db"
        _seed_events_db(
            db_path,
            issue_id="at-73j",
            old_description=(
                "scope: old\n"
                "external_tickets: "
                '[{"provider":"github","id":"174","direction":"export"}]\n'
            ),
            new_description="scope: rewritten\n",
        )
        tickets = beads.recover_external_tickets_from_history("at-73j", beads_root=beads_root)

    assert len(tickets) == 1
    assert tickets[0].provider == "github"
    assert tickets[0].ticket_id == "174"


def test_repair_external_ticket_metadata_from_history_recovers_and_updates() -> None:
    with TemporaryDirectory() as tmp:
        beads_root = Path(tmp)
        db_path = beads_root / "beads.db"
        _seed_events_db(
            db_path,
            issue_id="at-73j",
            old_description=(
                "scope: old\n"
                "external_tickets: "
                '[{"provider":"github","id":"174","direction":"export"}]\n'
            ),
            new_description="scope: rewritten\n",
        )

        issue = {
            "id": "at-73j",
            "labels": ["at:epic", "ext:github"],
            "description": "Intent\nmetadata missing now\n",
        }
        captured: dict[str, object] = {}

        def fake_update(
            issue_id: str,
            tickets: list[beads.ExternalTicketRef],
            *,
            beads_root: Path,
            cwd: Path,
        ) -> dict[str, object]:
            captured["issue_id"] = issue_id
            captured["tickets"] = tickets
            return {}

        with (
            patch("atelier.beads.run_bd_json", return_value=[issue]),
            patch("atelier.beads.update_external_tickets", side_effect=fake_update),
        ):
            results = beads.repair_external_ticket_metadata_from_history(
                beads_root=beads_root,
                cwd=Path("/repo"),
                apply=True,
            )

    assert len(results) == 1
    assert results[0].issue_id == "at-73j"
    assert results[0].recovered is True
    assert results[0].repaired is True
    assert captured["issue_id"] == "at-73j"
    tickets = captured["tickets"]
    assert isinstance(tickets, list)
    assert tickets[0].ticket_id == "174"

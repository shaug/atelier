import json
import sqlite3
import threading
import time
from pathlib import Path
from subprocess import CompletedProcess
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest

import atelier.beads as beads
from atelier import exec as exec_util


@pytest.fixture(autouse=True)
def _redirect_virtual_beads_issue_locks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Keep synthetic /beads tests writable while preserving real lock semantics."""
    virtual_root = Path("/beads")
    redirected_root = tmp_path / "virtual-beads-store"
    redirected_root.mkdir(parents=True, exist_ok=True)
    original_lock_path = beads._issue_write_lock_path  # pyright: ignore[reportPrivateUsage]

    def redirected_lock_path(*, issue_id: str, beads_root: Path) -> Path:
        if beads_root == virtual_root:
            return original_lock_path(issue_id=issue_id, beads_root=redirected_root)
        return original_lock_path(issue_id=issue_id, beads_root=beads_root)

    monkeypatch.setattr(beads, "_ISSUE_WRITE_LOCK_STATE", {})
    monkeypatch.setattr(beads, "_ISSUE_WRITE_LOCAL_LOCKS", {})
    monkeypatch.setattr(beads, "_issue_write_lock_path", redirected_lock_path)


def _write_beads_prefix_config(beads_root: Path, prefix: str) -> None:
    project_dir = beads_root.parent
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "config.sys.json").write_text(
        json.dumps({"beads": {"prefix": prefix}}),
        encoding="utf-8",
    )


def test_beads_env_sets_beads_db() -> None:
    env = beads.beads_env(Path("/tmp/project/.beads"))

    assert env["BEADS_DIR"] == "/tmp/project/.beads"
    assert env["BEADS_DB"] == "/tmp/project/.beads/beads.db"


def test_configured_issue_prefix_ignores_runtime_env_override(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    beads_root = tmp_path / ".beads"
    beads_root.mkdir()
    _write_beads_prefix_config(beads_root, "ts")
    monkeypatch.setenv("ATELIER_BEADS_PREFIX", "at")
    beads._ISSUE_PREFIX_CACHE.clear()  # pyright: ignore[reportPrivateUsage]

    assert beads.configured_issue_prefix(beads_root=beads_root) == "ts"
    assert beads._default_dolt_database_name(beads_root) == "beads_ts"  # pyright: ignore[reportPrivateUsage]


def test_issue_label_uses_fixed_at_namespace_with_custom_issue_prefix(tmp_path: Path) -> None:
    beads_root = tmp_path / ".beads"
    beads_root.mkdir()
    _write_beads_prefix_config(beads_root, "ts")
    beads._ISSUE_PREFIX_CACHE.clear()  # pyright: ignore[reportPrivateUsage]

    assert beads.issue_label("epic", beads_root=beads_root) == "at:epic"
    assert beads.issue_label_candidates("epic", beads_root=beads_root) == ("at:epic",)
    assert beads.issue_label_candidates(
        "epic",
        beads_root=beads_root,
        include_configured_prefix=True,
    ) == ("at:epic", "ts:epic")


def test_dolt_server_supervision_bypasses_rename_prefix() -> None:
    assert not beads._is_dolt_server_supervision_target(
        [
            "rename-prefix",
            "as-",
            "--repair",
        ]
    )


def test_default_dolt_database_name_is_prefix_only_and_prefix_aware(tmp_path: Path) -> None:
    beads_root = tmp_path / ".beads"
    beads_root.mkdir()

    beads._ISSUE_PREFIX_CACHE.clear()  # pyright: ignore[reportPrivateUsage]
    default_name = beads._default_dolt_database_name(beads_root)  # pyright: ignore[reportPrivateUsage]
    assert default_name == "beads_at"

    relocated_project = tmp_path / "relocated"
    relocated_project.mkdir()
    relocated_beads_root = relocated_project / ".beads"
    relocated_beads_root.mkdir()
    relocated_default = beads._default_dolt_database_name(  # pyright: ignore[reportPrivateUsage]
        relocated_beads_root
    )
    assert relocated_default == default_name

    _write_beads_prefix_config(beads_root, "ops")
    beads._ISSUE_PREFIX_CACHE.clear()  # pyright: ignore[reportPrivateUsage]
    ops_name = beads._default_dolt_database_name(beads_root)  # pyright: ignore[reportPrivateUsage]
    assert ops_name == "beads_ops"
    assert default_name != ops_name


def test_normalize_dolt_runtime_metadata_once_converges_to_project_database(tmp_path: Path) -> None:
    beads_root = tmp_path / ".beads"
    beads_root.mkdir()
    _write_beads_prefix_config(beads_root, "ops")
    beads._ISSUE_PREFIX_CACHE.clear()  # pyright: ignore[reportPrivateUsage]
    expected_database = beads._default_dolt_database_name(beads_root)  # pyright: ignore[reportPrivateUsage]
    (beads_root / "dolt" / expected_database / ".dolt").mkdir(parents=True)
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
    assert expected_database == "beads_ops"
    assert payload["dolt_database"] == expected_database
    assert (beads_root / "dolt" / "beads_at" / ".dolt").is_dir()


def test_normalize_dolt_runtime_metadata_once_sanitizes_database_name(tmp_path: Path) -> None:
    beads_root = tmp_path / ".beads"
    beads_root.mkdir()
    metadata_path = beads_root / "metadata.json"
    metadata_path.write_text(
        json.dumps(
            {
                "backend": "dolt",
                "dolt_mode": "server",
                "dolt_server_host": "127.0.0.1",
                "dolt_server_port": 3307,
                "dolt_server_user": "root",
                "dolt_database": "beads_at/",
            }
        ),
        encoding="utf-8",
    )

    beads._DOLT_RUNTIME_NORMALIZED.clear()  # pyright: ignore[reportPrivateUsage]
    beads._normalize_dolt_runtime_metadata_once(  # pyright: ignore[reportPrivateUsage]
        beads_root=beads_root
    )

    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert payload["dolt_database"] == beads._default_dolt_database_name(  # pyright: ignore[reportPrivateUsage]
        beads_root
    )


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


def test_normalize_dolt_runtime_metadata_once_preserves_database_for_env_contamination_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    beads_root = tmp_path / ".beads"
    beads_root.mkdir()
    _write_beads_prefix_config(beads_root, "ts")
    monkeypatch.setenv("ATELIER_BEADS_PREFIX", "at")
    beads._ISSUE_PREFIX_CACHE.clear()  # pyright: ignore[reportPrivateUsage]
    preferred = beads._default_dolt_database_name(beads_root)  # pyright: ignore[reportPrivateUsage]
    (beads_root / "dolt" / preferred / ".dolt").mkdir(parents=True)
    (beads_root / "dolt" / "beads_at" / ".dolt").mkdir(parents=True)
    metadata_path = beads_root / "metadata.json"
    metadata_path.write_text(
        json.dumps(
            {
                "backend": "dolt",
                "dolt_mode": "embedded",
                "dolt_server_host": "",
                "dolt_server_port": 0,
                "dolt_database": "beads_at",
            }
        ),
        encoding="utf-8",
    )

    beads._DOLT_RUNTIME_NORMALIZED.clear()  # pyright: ignore[reportPrivateUsage]
    with patch("atelier.beads.atelier_log.warning") as warning_log:
        beads._normalize_dolt_runtime_metadata_once(  # pyright: ignore[reportPrivateUsage]
            beads_root=beads_root
        )

    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert payload["dolt_database"] == "beads_at"
    assert (beads_root / "dolt" / preferred / ".dolt").is_dir()
    assert (beads_root / "dolt" / "beads_at" / ".dolt").is_dir()
    messages = [str(call.args[0]) for call in warning_log.call_args_list if call.args]
    assert any("does not match project-scoped expected database" in message for message in messages)


def test_normalize_dolt_runtime_metadata_once_preserves_database_when_expected_missing(
    tmp_path: Path,
) -> None:
    beads_root = tmp_path / ".beads"
    beads_root.mkdir()
    expected_database = beads._default_dolt_database_name(beads_root)  # pyright: ignore[reportPrivateUsage]
    (beads_root / "dolt" / "beads" / ".dolt").mkdir(parents=True)
    (beads_root / "dolt" / "beads_other" / ".dolt").mkdir(parents=True)
    metadata_path = beads_root / "metadata.json"
    metadata_path.write_text(
        json.dumps(
            {
                "backend": "dolt",
                "dolt_mode": "embedded",
                "dolt_server_host": "",
                "dolt_server_port": 0,
                "dolt_database": "beads",
            }
        ),
        encoding="utf-8",
    )

    beads._DOLT_RUNTIME_NORMALIZED.clear()  # pyright: ignore[reportPrivateUsage]
    with patch("atelier.beads.atelier_log.warning") as warning_log:
        beads._normalize_dolt_runtime_metadata_once(  # pyright: ignore[reportPrivateUsage]
            beads_root=beads_root
        )

    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert payload["dolt_database"] == "beads"
    messages = [str(call.args[0]) for call in warning_log.call_args_list if call.args]
    assert any("does not match project-scoped expected database" in message for message in messages)


def test_normalize_dolt_runtime_metadata_once_skips_expected_missing_warning_when_configured(
    tmp_path: Path,
) -> None:
    beads_root = tmp_path / ".beads"
    beads_root.mkdir()
    _write_beads_prefix_config(beads_root, "ts")
    beads._ISSUE_PREFIX_CACHE.clear()  # pyright: ignore[reportPrivateUsage]
    expected_database = beads._default_dolt_database_name(beads_root)  # pyright: ignore[reportPrivateUsage]
    (beads_root / "dolt" / "beads_at" / ".dolt").mkdir(parents=True)
    metadata_path = beads_root / "metadata.json"
    metadata_path.write_text(
        json.dumps(
            {
                "backend": "dolt",
                "dolt_mode": "server",
                "dolt_server_host": "127.0.0.1",
                "dolt_server_port": 3307,
                "dolt_server_user": "root",
                "dolt_database": expected_database,
            }
        ),
        encoding="utf-8",
    )

    beads._DOLT_RUNTIME_NORMALIZED.clear()  # pyright: ignore[reportPrivateUsage]
    with patch("atelier.beads.atelier_log.warning") as warning_log:
        beads._normalize_dolt_runtime_metadata_once(  # pyright: ignore[reportPrivateUsage]
            beads_root=beads_root
        )

    messages = [str(call.args[0]) for call in warning_log.call_args_list if call.args]
    assert not any(
        f"do not include expected {expected_database}" in message for message in messages
    )


def test_normalize_dolt_runtime_metadata_once_sets_expected_db_with_multiple_candidates(
    tmp_path: Path,
) -> None:
    beads_root = tmp_path / ".beads"
    beads_root.mkdir()
    preferred = beads._default_dolt_database_name(beads_root)  # pyright: ignore[reportPrivateUsage]
    (beads_root / "dolt" / preferred / ".dolt").mkdir(parents=True)
    (beads_root / "dolt" / "beads" / ".dolt").mkdir(parents=True)
    metadata_path = beads_root / "metadata.json"
    metadata_path.write_text(
        json.dumps(
            {
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

    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert payload["dolt_database"] == preferred


def test_normalize_dolt_runtime_metadata_once_sets_project_db_for_single_project_store(
    tmp_path: Path,
) -> None:
    beads_root = tmp_path / ".beads"
    beads_root.mkdir()
    preferred = beads._default_dolt_database_name(beads_root)  # pyright: ignore[reportPrivateUsage]
    (beads_root / "dolt" / preferred / ".dolt").mkdir(parents=True)
    metadata_path = beads_root / "metadata.json"
    metadata_path.write_text(
        json.dumps(
            {
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

    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert payload["dolt_database"] == preferred


def test_resolve_dolt_server_runtime_uses_prefix_database_by_default(
    tmp_path: Path,
) -> None:
    beads_root = tmp_path / ".beads"
    expected_database = beads._default_dolt_database_name(  # pyright: ignore[reportPrivateUsage]
        beads_root
    )
    (beads_root / "dolt" / expected_database / ".dolt").mkdir(parents=True)
    (beads_root / "dolt" / "beads_other" / ".dolt").mkdir(parents=True)
    (beads_root / "metadata.json").write_text(json.dumps({"backend": "dolt"}), encoding="utf-8")

    runtime = beads._resolve_dolt_server_runtime(  # pyright: ignore[reportPrivateUsage]
        beads_root
    )

    assert runtime.database == expected_database
    assert runtime.ownership_error is None


def test_resolve_dolt_server_runtime_fails_closed_when_metadata_database_differs_from_project(
    tmp_path: Path,
) -> None:
    beads_root = tmp_path / ".beads"
    expected_database = beads._default_dolt_database_name(  # pyright: ignore[reportPrivateUsage]
        beads_root
    )
    (beads_root / "dolt" / expected_database / ".dolt").mkdir(parents=True)
    (beads_root / "dolt" / "beads_other" / ".dolt").mkdir(parents=True)
    (beads_root / "metadata.json").write_text(
        json.dumps({"backend": "dolt", "dolt_database": "beads_other/"}),
        encoding="utf-8",
    )

    runtime = beads._resolve_dolt_server_runtime(  # pyright: ignore[reportPrivateUsage]
        beads_root
    )

    assert runtime.database == "beads_other"
    assert runtime.ownership_error is not None
    assert "runtime metadata configures beads_other" in runtime.ownership_error


def test_resolve_dolt_server_runtime_fails_closed_when_metadata_database_is_unknown(
    tmp_path: Path,
) -> None:
    beads_root = tmp_path / ".beads"
    expected_database = beads._default_dolt_database_name(  # pyright: ignore[reportPrivateUsage]
        beads_root
    )
    (beads_root / "dolt" / expected_database / ".dolt").mkdir(parents=True)
    (beads_root / "dolt" / "beads_local" / ".dolt").mkdir(parents=True)
    (beads_root / "dolt" / "beads_other" / ".dolt").mkdir(parents=True)
    (beads_root / "metadata.json").write_text(
        json.dumps({"backend": "dolt", "dolt_database": "beads_unknown"}),
        encoding="utf-8",
    )

    runtime = beads._resolve_dolt_server_runtime(  # pyright: ignore[reportPrivateUsage]
        beads_root
    )

    assert runtime.database == "beads_unknown"
    assert runtime.ownership_error is not None
    assert "runtime metadata configures beads_unknown" in runtime.ownership_error


def test_resolve_dolt_server_runtime_fails_closed_when_expected_db_missing(
    tmp_path: Path,
) -> None:
    beads_root = tmp_path / ".beads"
    _write_beads_prefix_config(beads_root, "ops")
    beads._ISSUE_PREFIX_CACHE.clear()  # pyright: ignore[reportPrivateUsage]
    expected_database = beads._default_dolt_database_name(  # pyright: ignore[reportPrivateUsage]
        beads_root
    )
    (beads_root / "dolt" / "beads_at" / ".dolt").mkdir(parents=True)
    (beads_root / "dolt" / "beads_other" / ".dolt").mkdir(parents=True)
    (beads_root / "metadata.json").write_text(
        json.dumps({"backend": "dolt", "dolt_database": ""}),
        encoding="utf-8",
    )

    runtime = beads._resolve_dolt_server_runtime(  # pyright: ignore[reportPrivateUsage]
        beads_root
    )

    assert runtime.database == expected_database
    assert runtime.ownership_error is not None
    assert "local databases (beads_at, beads_other)" in runtime.ownership_error
    assert f"do not include expected {expected_database}" in runtime.ownership_error


def test_resolve_dolt_server_runtime_adopts_single_local_database_when_expected_missing(
    tmp_path: Path,
) -> None:
    beads_root = tmp_path / ".beads"
    _write_beads_prefix_config(beads_root, "ts")
    beads._ISSUE_PREFIX_CACHE.clear()  # pyright: ignore[reportPrivateUsage]
    expected_database = beads._default_dolt_database_name(  # pyright: ignore[reportPrivateUsage]
        beads_root
    )
    adopted_database = "beads_at"
    (beads_root / "dolt" / adopted_database / ".dolt").mkdir(parents=True)
    (beads_root / "metadata.json").write_text(
        json.dumps({"backend": "dolt", "dolt_database": expected_database}),
        encoding="utf-8",
    )

    runtime = beads._resolve_dolt_server_runtime(  # pyright: ignore[reportPrivateUsage]
        beads_root
    )

    assert expected_database == "beads_ts"
    assert runtime.database == expected_database
    assert runtime.ownership_error is None


def test_resolve_dolt_server_runtime_adopts_single_local_database_when_unconfigured(
    tmp_path: Path,
) -> None:
    beads_root = tmp_path / ".beads"
    _write_beads_prefix_config(beads_root, "ts")
    beads._ISSUE_PREFIX_CACHE.clear()  # pyright: ignore[reportPrivateUsage]
    expected_database = beads._default_dolt_database_name(  # pyright: ignore[reportPrivateUsage]
        beads_root
    )
    adopted_database = "beads_at"
    (beads_root / "dolt" / adopted_database / ".dolt").mkdir(parents=True)
    (beads_root / "metadata.json").write_text(
        json.dumps({"backend": "dolt"}),
        encoding="utf-8",
    )

    runtime = beads._resolve_dolt_server_runtime(  # pyright: ignore[reportPrivateUsage]
        beads_root
    )

    assert expected_database == "beads_ts"
    assert runtime.database == adopted_database
    assert runtime.ownership_error is None


def test_run_bd_command_fails_closed_when_server_reports_other_project_database(
    tmp_path: Path,
) -> None:
    beads_root = tmp_path / ".beads"
    (beads_root / "dolt").mkdir(parents=True)
    expected_database = beads._default_dolt_database_name(beads_root)  # pyright: ignore[reportPrivateUsage]
    (beads_root / "metadata.json").write_text(
        json.dumps({"backend": "dolt", "dolt_database": expected_database}),
        encoding="utf-8",
    )
    cwd = tmp_path / "repo"
    cwd.mkdir(parents=True)
    calls: list[list[str]] = []

    def fake_run_with_runner(
        request: exec_util.CommandRequest,
    ) -> exec_util.CommandResult | None:
        argv = list(request.argv)
        calls.append(argv)
        if argv == ["bd", "dolt", "show", "--json"]:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout='{"connection_ok":true,"database":"beads_other"}',
                stderr="",
            )
        raise AssertionError(f"unexpected command: {argv}")

    def fake_die(message: str, code: int = 1) -> None:
        del code
        raise RuntimeError(message)

    with (
        patch("atelier.beads.bd_invocation.ensure_supported_bd_version"),
        patch("atelier.beads.exec.run_with_runner", side_effect=fake_run_with_runner),
        patch(
            "atelier.beads._restart_dolt_server_with_recovery",
            return_value=(
                False,
                "dolt server ownership mismatch: "
                f"expected database={expected_database}, got beads_other. "
                f"{beads._dolt_database_remediation(expected_database=expected_database)}",  # pyright: ignore[reportPrivateUsage]
            ),
        ),
        patch("atelier.beads._startup_state_diagnostics", return_value="startup-diag"),
        patch("atelier.beads.die", side_effect=fake_die),
    ):
        with pytest.raises(RuntimeError) as excinfo:
            beads.run_bd_command(["list", "--json"], beads_root=beads_root, cwd=cwd)

    message = str(excinfo.value)
    assert "dolt server preflight failed before running bd command" in message
    assert f"expected database={expected_database}" in message
    assert "Run `bd dolt set database" in message
    assert "startup-diag" in message
    assert calls == [["bd", "dolt", "show", "--json"]]


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


def test_run_bd_command_repairs_missing_store_for_rename_prefix_error(
    tmp_path: Path,
) -> None:
    beads_root = tmp_path / "project" / ".beads"
    beads_root.mkdir(parents=True)
    cwd = tmp_path / "repo"
    cwd.mkdir(parents=True)
    calls: list[list[str]] = []

    missing_store_error = (
        "Error: failed to get current prefix: <nil>\n"
        "Startup Beads state: classification=startup_state_unknown; migration_eligible=no; "
        "configured_backend=dolt; dolt_store=missing; legacy_sqlite=present; "
        "dolt_issue_total=0; dolt_count_source=bd_stats_without_dolt_store; "
        "legacy_issue_total=0; legacy_count_source=bd_stats_legacy_sqlite; "
        "reason=dolt_store_missing_without_recoverable_legacy_data"
    )

    def fake_run_with_runner(
        request: exec_util.CommandRequest,
    ) -> exec_util.CommandResult | None:
        argv = list(request.argv)
        calls.append(argv)
        if argv == ["bd", "rename-prefix", "as-", "--repair"] and len(calls) == 1:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=1,
                stdout="",
                stderr=missing_store_error,
            )
        if argv[:3] == ["bd", "doctor", "--fix"]:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout="fixed",
                stderr="",
            )
        if argv[:4] == ["bd", "init", "--prefix", "at"]:
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
        if argv == ["bd", "rename-prefix", "as-", "--repair"] and len(calls) > 1:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout="renamed",
                stderr="",
            )
        raise AssertionError(f"unexpected command: {argv}")

    with (
        patch("atelier.beads.bd_invocation.ensure_supported_bd_version"),
        patch("atelier.beads.exec.run_with_runner", side_effect=fake_run_with_runner),
    ):
        result = beads.run_bd_command(
            ["rename-prefix", "as-", "--repair"], beads_root=beads_root, cwd=cwd
        )

    assert result.returncode == 0
    assert calls[0] == ["bd", "rename-prefix", "as-", "--repair"]
    assert ["bd", "doctor", "--fix", "--yes"] in calls
    assert ["bd", "init", "--prefix", "at"] in calls
    assert calls[-1] == ["bd", "rename-prefix", "as-", "--repair"]


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


def test_run_bd_json_read_only_returns_payload_without_error() -> None:
    with patch(
        "atelier.beads.run_bd_command",
        return_value=CompletedProcess(
            args=["bd", "show", "at-1", "--json"],
            returncode=0,
            stdout='[{"id":"at-1","status":"open","labels":[]}]',
            stderr="",
        ),
    ):
        payload, error = beads.run_bd_json_read_only(
            ["show", "at-1"],
            beads_root=Path("/beads"),
            cwd=Path("/repo"),
        )

    assert payload == [{"id": "at-1", "status": "open", "labels": []}]
    assert error is None


def test_run_bd_json_read_only_includes_command_and_stream_details_on_failure() -> None:
    with patch(
        "atelier.beads.run_bd_command",
        return_value=CompletedProcess(
            args=["bd", "list", "--parent", "at-1", "--json"],
            returncode=1,
            stdout="db timeout",
            stderr="TLS timeout",
        ),
    ):
        payload, error = beads.run_bd_json_read_only(
            ["list", "--parent", "at-1"],
            beads_root=Path("/beads"),
            cwd=Path("/repo"),
        )

    assert payload == []
    assert error is not None
    assert "command failed: bd list --parent at-1 --json (exit 1)" in error
    assert "stderr: TLS timeout" in error
    assert "stdout: db timeout" in error


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


def test_run_bd_command_preflight_fails_closed_for_wrong_active_database(
    tmp_path: Path,
) -> None:
    beads_root = tmp_path / ".beads"
    beads_root.mkdir(parents=True)
    preferred = beads._default_dolt_database_name(beads_root)  # pyright: ignore[reportPrivateUsage]
    (beads_root / "dolt" / preferred / ".dolt").mkdir(parents=True)
    (beads_root / "dolt" / "beads" / ".dolt").mkdir(parents=True)
    (beads_root / "metadata.json").write_text(
        json.dumps({"backend": "dolt", "dolt_mode": "server", "dolt_database": ""}),
        encoding="utf-8",
    )
    cwd = tmp_path / "repo"
    cwd.mkdir()

    def fake_die(message: str, code: int = 1) -> None:
        del code
        raise RuntimeError(message)

    def fake_run_with_runner(
        request: exec_util.CommandRequest,
    ) -> exec_util.CommandResult | None:
        argv = list(request.argv)
        if argv == ["bd", "dolt", "show", "--json"]:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout='{"connection_ok":true,"database":"beads"}',
                stderr="",
            )
        raise AssertionError(f"unexpected command: {argv}")

    with (
        patch("atelier.beads.bd_invocation.ensure_supported_bd_version"),
        patch(
            "atelier.beads._restart_dolt_server_with_recovery",
            return_value=(
                False,
                "dolt server ownership mismatch: "
                f"expected database={preferred}, got beads. "
                f"{beads._dolt_database_remediation(expected_database=preferred)}",  # pyright: ignore[reportPrivateUsage]
            ),
        ) as restart,
        patch("atelier.beads.exec.run_with_runner", side_effect=fake_run_with_runner),
        patch("atelier.beads._startup_state_diagnostics", return_value="startup-diag"),
        patch("atelier.beads.die", side_effect=fake_die),
    ):
        with pytest.raises(
            RuntimeError, match="dolt server preflight failed before running bd command"
        ):
            beads.run_bd_command(["show", "at-1", "--json"], beads_root=beads_root, cwd=cwd)

    restart.assert_called_once()


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


def test_run_bd_command_fails_closed_when_prefix_claimed_by_other_project(
    tmp_path: Path,
) -> None:
    projects_root = tmp_path / "projects"
    project_a = projects_root / "project-a"
    project_b = projects_root / "project-b"
    project_a_beads = project_a / ".beads"
    project_b_beads = project_b / ".beads"
    for beads_root in (project_a_beads, project_b_beads):
        (beads_root / "dolt").mkdir(parents=True)
    (project_a / "config.sys.json").write_text(
        json.dumps({"beads": {"prefix": "at"}}),
        encoding="utf-8",
    )
    (project_b / "config.sys.json").write_text(
        json.dumps({"beads": {"prefix": "at"}}),
        encoding="utf-8",
    )
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    repo_a.mkdir()
    repo_b.mkdir()

    expected_a = beads._default_dolt_database_name(project_a_beads)  # pyright: ignore[reportPrivateUsage]
    expected_b = beads._default_dolt_database_name(project_b_beads)  # pyright: ignore[reportPrivateUsage]
    (project_a_beads / "metadata.json").write_text(
        json.dumps({"backend": "dolt", "dolt_database": expected_a}),
        encoding="utf-8",
    )
    (project_b_beads / "metadata.json").write_text(
        json.dumps({"backend": "dolt", "dolt_database": expected_b}),
        encoding="utf-8",
    )

    calls: list[tuple[Path, list[str]]] = []

    def fake_run_with_runner(
        request: exec_util.CommandRequest,
    ) -> exec_util.CommandResult | None:
        argv = list(request.argv)
        calls.append((request.cwd, argv))
        if argv == ["bd", "dolt", "show", "--json"]:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout=f'{{"connection_ok":true,"database":"{expected_a}"}}',
                stderr="",
            )
        if argv == ["bd", "list", "--json"] and request.cwd == repo_a:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout="[]",
                stderr="",
            )
        raise AssertionError(f"unexpected command: cwd={request.cwd} argv={argv}")

    def fake_die(message: str, code: int = 1) -> None:
        del code
        raise RuntimeError(message)

    with (
        patch("atelier.beads.bd_invocation.ensure_supported_bd_version"),
        patch("atelier.beads.exec.run_with_runner", side_effect=fake_run_with_runner),
        patch("atelier.beads.paths.projects_root", return_value=projects_root),
        patch("atelier.beads._startup_state_diagnostics", return_value="startup-diag"),
        patch("atelier.beads.die", side_effect=fake_die),
    ):
        result_a = beads.run_bd_command(["list", "--json"], beads_root=project_a_beads, cwd=repo_a)
        with pytest.raises(RuntimeError) as excinfo:
            beads.run_bd_command(["list", "--json"], beads_root=project_b_beads, cwd=repo_b)

    assert result_a.returncode == 0
    assert expected_a == expected_b == "beads_at"
    message = str(excinfo.value)
    assert "dolt server preflight failed before running bd command" in message
    assert "beads.prefix collision for 'at'" in message
    assert "claimed by" in message
    assert (repo_b, ["bd", "list", "--json"]) not in calls


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
        patch("atelier.beads._repo_slug_for_gate", return_value=None),
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


def test_run_bd_command_allows_in_progress_when_dependency_integrated_but_not_closed(
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
                stdout=(
                    '[{"id":"at-1","status":"in_progress","labels":[],'
                    '"description":"changeset.work_branch: feat/at-1\\n","type":"task"}]'
                ),
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
        patch("atelier.beads.git.git_origin_url", return_value="git@github.com:org/repo.git"),
        patch(
            "atelier.beads.prs.read_github_pr_status",
            return_value={"state": "MERGED", "mergedAt": "2026-02-28T00:00:00Z"},
        ),
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


def test_changeset_integrated_for_gate_uses_worker_integration_signal() -> None:
    issue = {"id": "at-1", "description": "changeset.work_branch: feat/at-1\n"}
    repo_root = Path("/repo")

    with (
        patch("atelier.beads._repo_slug_for_gate", return_value="org/repo"),
        patch(
            "atelier.worker.integration.changeset_integration_signal",
            return_value=(True, "abc1234"),
        ) as integration_signal,
    ):
        integrated = beads._changeset_integrated_for_gate(  # pyright: ignore[reportPrivateUsage]
            issue,
            repo_root=repo_root,
        )

    assert integrated is True
    integration_signal.assert_called_once()
    assert integration_signal.call_args.args == (issue,)
    assert integration_signal.call_args.kwargs["repo_slug"] == "org/repo"
    assert integration_signal.call_args.kwargs["repo_root"] == repo_root
    assert callable(integration_signal.call_args.kwargs["lookup_pr_payload"])


def test_run_bd_command_prime_auto_migrates_recoverable_startup_state(
    tmp_path: Path,
) -> None:
    beads_root = tmp_path / ".beads"
    beads_root.mkdir()
    (beads_root / "beads.db").write_bytes(b"legacy")
    cwd = tmp_path / "repo"
    cwd.mkdir()

    db_stats = ["bd", "--db", str(beads_root / "beads.db"), "stats", "--json"]
    probe_command = [
        "bd",
        "--db",
        str(beads_root / "beads.db"),
        "migrate",
        "--to-dolt",
        "--inspect",
        "--json",
    ]
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
        if argv == probe_command:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout='{"inspect":"ok"}',
                stderr="",
            )
        if argv == migrate:
            (beads_root / "dolt" / "beads_at" / ".dolt").mkdir(parents=True, exist_ok=True)
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


def test_run_bd_command_list_auto_migrates_recoverable_startup_state(
    tmp_path: Path,
) -> None:
    beads_root = tmp_path / ".beads"
    beads_root.mkdir()
    (beads_root / "beads.db").write_bytes(b"legacy")
    cwd = tmp_path / "repo"
    cwd.mkdir()

    db_stats = ["bd", "--db", str(beads_root / "beads.db"), "stats", "--json"]
    probe_command = [
        "bd",
        "--db",
        str(beads_root / "beads.db"),
        "migrate",
        "--to-dolt",
        "--inspect",
        "--json",
    ]
    migrate = [
        "bd",
        "--db",
        str(beads_root / "beads.db"),
        "migrate",
        "--to-dolt",
        "--yes",
        "--json",
    ]
    expected_database = beads._default_dolt_database_name(  # pyright: ignore[reportPrivateUsage]
        beads_root
    )
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
        if argv == probe_command:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout='{"inspect":"ok"}',
                stderr="",
            )
        if argv == migrate:
            (beads_root / "dolt" / expected_database / ".dolt").mkdir(parents=True, exist_ok=True)
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout='{"migrated":8}',
                stderr="",
            )
        if argv == ["bd", "dolt", "show", "--json"]:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout=f'{{"connection_ok":true,"database":"{expected_database}"}}',
                stderr="",
            )
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
        patch("atelier.beads.bd_invocation.detect_bd_version", return_value=(0, 56, 1)),
        patch("atelier.beads.exec.run_with_runner", side_effect=fake_run_with_runner),
        patch("atelier.beads.say", side_effect=diagnostics.append),
    ):
        result = beads.run_bd_command(["list", "--json"], beads_root=beads_root, cwd=cwd)

    assert result.returncode == 0
    assert migrate in calls
    assert calls[-1] == ["bd", "list", "--json"]
    assert diagnostics == []


def test_reconcile_startup_auto_migration_runtime_database_falls_back_to_metadata(
    tmp_path: Path,
) -> None:
    beads_root = tmp_path / ".beads"
    beads_root.mkdir()
    expected_database = beads._default_dolt_database_name(beads_root)  # pyright: ignore[reportPrivateUsage]
    metadata_path = beads_root / "metadata.json"
    metadata_path.write_text(
        json.dumps({"backend": "dolt", "dolt_database": f"{expected_database}/"}),
        encoding="utf-8",
    )
    cwd = tmp_path / "repo"
    cwd.mkdir()
    calls: list[list[str]] = []
    warnings: list[str] = []

    def fake_run_with_runner(
        request: exec_util.CommandRequest,
    ) -> exec_util.CommandResult | None:
        argv = list(request.argv)
        calls.append(argv)
        if argv == ["bd", "dolt", "show", "--json"]:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout=f'{{"connection_ok":true,"database":"{expected_database}/"}}',
                stderr="",
            )
        if argv == ["bd", "dolt", "set", "database", expected_database, "--update-config"]:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=1,
                stdout="",
                stderr="unknown flag: --update-config",
            )
        raise AssertionError(f"unexpected command: {argv}")

    with (
        patch("atelier.beads.exec.run_with_runner", side_effect=fake_run_with_runner),
        patch("atelier.beads.atelier_log.warning", side_effect=warnings.append),
    ):
        beads._reconcile_startup_auto_migration_runtime_database(  # pyright: ignore[reportPrivateUsage]
            beads_root=beads_root,
            cwd=cwd,
            env={},
        )

    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert payload["dolt_database"] == expected_database
    assert ["bd", "dolt", "set", "database", expected_database, "--update-config"] in calls
    assert any("fell back to metadata update" in message for message in warnings)


def test_reconcile_startup_auto_migration_runtime_database_logs_unchanged_metadata(
    tmp_path: Path,
) -> None:
    beads_root = tmp_path / ".beads"
    beads_root.mkdir()
    expected_database = beads._default_dolt_database_name(beads_root)  # pyright: ignore[reportPrivateUsage]
    metadata_path = beads_root / "metadata.json"
    metadata_path.write_text(
        json.dumps({"backend": "dolt", "dolt_database": expected_database}),
        encoding="utf-8",
    )
    cwd = tmp_path / "repo"
    cwd.mkdir()
    calls: list[list[str]] = []
    warnings: list[str] = []

    def fake_run_with_runner(
        request: exec_util.CommandRequest,
    ) -> exec_util.CommandResult | None:
        argv = list(request.argv)
        calls.append(argv)
        if argv == ["bd", "dolt", "show", "--json"]:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout=f'{{"connection_ok":true,"database":"{expected_database}"}}',
                stderr="",
            )
        if argv == ["bd", "dolt", "set", "database", expected_database, "--update-config"]:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=1,
                stdout="",
                stderr="unknown flag: --update-config",
            )
        raise AssertionError(f"unexpected command: {argv}")

    with (
        patch("atelier.beads.exec.run_with_runner", side_effect=fake_run_with_runner),
        patch("atelier.beads.atelier_log.warning", side_effect=warnings.append),
    ):
        beads._reconcile_startup_auto_migration_runtime_database(  # pyright: ignore[reportPrivateUsage]
            beads_root=beads_root,
            cwd=cwd,
            env={},
        )

    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert payload["dolt_database"] == expected_database
    assert ["bd", "dolt", "set", "database", expected_database, "--update-config"] in calls
    assert any("already matched the active database" in message for message in warnings)
    assert not any("fell back to metadata update" in message for message in warnings)


def test_reconcile_startup_auto_migration_runtime_database_updates_to_expected_db(
    tmp_path: Path,
) -> None:
    beads_root = tmp_path / ".beads"
    beads_root.mkdir()
    (beads_root / "dolt" / "beads_at" / ".dolt").mkdir(parents=True)
    (beads_root / "dolt" / "beads_other" / ".dolt").mkdir(parents=True)
    metadata_path = beads_root / "metadata.json"
    metadata_path.write_text(
        json.dumps({"backend": "dolt", "dolt_database": "beads_other"}),
        encoding="utf-8",
    )
    cwd = tmp_path / "repo"
    cwd.mkdir()
    calls: list[list[str]] = []
    warnings: list[str] = []

    def fake_run_with_runner(
        request: exec_util.CommandRequest,
    ) -> exec_util.CommandResult | None:
        argv = list(request.argv)
        calls.append(argv)
        if argv == ["bd", "dolt", "show", "--json"]:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout='{"connection_ok":true,"database":"beads_at"}',
                stderr="",
            )
        if argv == ["bd", "dolt", "set", "database", "beads_at", "--update-config"]:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=1,
                stdout="",
                stderr="unknown flag: --update-config",
            )
        raise AssertionError(f"unexpected command: {argv}")

    with (
        patch("atelier.beads.exec.run_with_runner", side_effect=fake_run_with_runner),
        patch("atelier.beads.atelier_log.warning", side_effect=warnings.append),
    ):
        beads._reconcile_startup_auto_migration_runtime_database(  # pyright: ignore[reportPrivateUsage]
            beads_root=beads_root,
            cwd=cwd,
            env={},
        )

    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert payload["dolt_database"] == "beads_at"
    assert ["bd", "dolt", "set", "database", "beads_at", "--update-config"] in calls
    assert any("fell back to metadata update" in message for message in warnings)
    assert not any("reconciliation failed" in message for message in warnings)


def test_update_runtime_metadata_dolt_database_blocks_expected_database_mismatch(
    tmp_path: Path,
) -> None:
    beads_root = tmp_path / ".beads"
    beads_root.mkdir()
    (beads_root / "dolt" / "beads_at" / ".dolt").mkdir(parents=True)
    (beads_root / "dolt" / "beads_other" / ".dolt").mkdir(parents=True)
    metadata_path = beads_root / "metadata.json"
    metadata_path.write_text(
        json.dumps({"backend": "dolt", "dolt_database": "beads_other/"}),
        encoding="utf-8",
    )

    result = beads._update_runtime_metadata_dolt_database(  # pyright: ignore[reportPrivateUsage]
        beads_root=beads_root,
        database_name="beads_other",
    )

    assert result == "blocked_mismatch"
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert payload["dolt_database"] == "beads_other/"


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
    probe_command = [
        "bd",
        "--db",
        str(beads_root / "beads.db"),
        "migrate",
        "--to-dolt",
        "--inspect",
        "--json",
    ]
    migrate = [
        "bd",
        "--db",
        str(beads_root / "beads.db"),
        "migrate",
        "--to-dolt",
        "--yes",
        "--json",
    ]
    migrated = False
    calls: list[list[str]] = []
    diagnostics: list[str] = []

    def fake_run_with_runner(
        request: exec_util.CommandRequest,
    ) -> exec_util.CommandResult | None:
        nonlocal migrated
        argv = list(request.argv)
        calls.append(argv)
        if argv == ["bd", "stats", "--json"]:
            if not migrated:
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
        if argv == probe_command:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout='{"inspect":"ok"}',
                stderr="",
            )
        if argv == migrate:
            migrated = True
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


def test_run_bd_command_degrades_when_migration_capability_is_unavailable(
    tmp_path: Path,
) -> None:
    beads_root = tmp_path / ".beads"
    beads_root.mkdir()
    (beads_root / "beads.db").write_bytes(b"legacy")
    cwd = tmp_path / "repo"
    cwd.mkdir()

    db_stats = ["bd", "--db", str(beads_root / "beads.db"), "stats", "--json"]
    probe_command = [
        "bd",
        "--db",
        str(beads_root / "beads.db"),
        "migrate",
        "--to-dolt",
        "--inspect",
        "--json",
    ]
    migrate = [
        "bd",
        "--db",
        str(beads_root / "beads.db"),
        "migrate",
        "--to-dolt",
        "--yes",
        "--json",
    ]
    calls: list[list[str]] = []
    diagnostics: list[str] = []

    def fake_run_with_runner(
        request: exec_util.CommandRequest,
    ) -> exec_util.CommandResult | None:
        argv = list(request.argv)
        calls.append(argv)
        if argv == ["bd", "stats", "--json"]:
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
                stdout='{"summary":{"total_issues":8}}',
                stderr="",
            )
        if argv == probe_command:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=1,
                stdout=(
                    '{"error":"dolt_not_available","message":"Dolt backend requires CGO. '
                    'This binary was built without CGO support."}'
                ),
                stderr="",
            )
        if argv == ["bd", "prime"]:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout="primed",
                stderr="",
            )
        if argv == ["bd", "ready"]:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout="[]",
                stderr="",
            )
        raise AssertionError(f"unexpected command: {argv}")

    with (
        patch("atelier.beads.bd_invocation.ensure_supported_bd_version"),
        patch("atelier.beads.bd_invocation.detect_bd_version", return_value=(0, 56, 1)),
        patch("atelier.beads.exec.run_with_runner", side_effect=fake_run_with_runner),
        patch("atelier.beads.say", side_effect=diagnostics.append),
    ):
        prime_result = beads.run_bd_command(["prime"], beads_root=beads_root, cwd=cwd)
        ready_result = beads.run_bd_command(["ready"], beads_root=beads_root, cwd=cwd)

    assert prime_result.returncode == 0
    assert ready_result.returncode == 0
    assert diagnostics
    assert "auto-upgrade blocked" in diagnostics[0]
    assert "requires a `bd` build with Dolt/CGO support" in diagnostics[0]
    assert probe_command in calls
    assert calls.count(probe_command) == 1
    assert migrate not in calls


def test_run_bd_command_prime_blocks_when_migration_parity_fails(
    tmp_path: Path,
) -> None:
    beads_root = tmp_path / ".beads"
    beads_root.mkdir()
    (beads_root / "beads.db").write_bytes(b"legacy")
    cwd = tmp_path / "repo"
    cwd.mkdir()

    db_stats = ["bd", "--db", str(beads_root / "beads.db"), "stats", "--json"]
    probe_command = [
        "bd",
        "--db",
        str(beads_root / "beads.db"),
        "migrate",
        "--to-dolt",
        "--inspect",
        "--json",
    ]
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
        if argv == probe_command:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout='{"inspect":"ok"}',
                stderr="",
            )
        if argv == migrate:
            (beads_root / "dolt" / "beads_at" / ".dolt").mkdir(parents=True, exist_ok=True)
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
    probe_command = [
        "bd",
        "--db",
        str(beads_root / "beads.db"),
        "migrate",
        "--to-dolt",
        "--inspect",
        "--json",
    ]
    migrate = [
        "bd",
        "--db",
        str(beads_root / "beads.db"),
        "migrate",
        "--to-dolt",
        "--yes",
        "--json",
    ]
    expected_database = beads._default_dolt_database_name(  # pyright: ignore[reportPrivateUsage]
        beads_root
    )
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
        if argv == probe_command:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout='{"inspect":"ok"}',
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
        if argv == ["bd", "dolt", "show", "--json"]:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout=f'{{"connection_ok":true,"database":"{expected_database}"}}',
                stderr="",
            )
        if argv == migrate:
            (beads_root / "dolt" / expected_database / ".dolt").mkdir(parents=True, exist_ok=True)
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
    probe_command = [
        "bd",
        "--db",
        str(beads_root / "beads.db"),
        "migrate",
        "--to-dolt",
        "--inspect",
        "--json",
    ]
    migrate = [
        "bd",
        "--db",
        str(beads_root / "beads.db"),
        "migrate",
        "--to-dolt",
        "--yes",
        "--json",
    ]
    expected_database = beads._default_dolt_database_name(  # pyright: ignore[reportPrivateUsage]
        beads_root
    )
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
        if argv == probe_command:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout='{"inspect":"ok"}',
                stderr="",
            )
        if argv == ["bd", "show", "at-agent-required", "--json"]:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout="[]",
                stderr="",
            )
        if argv == ["bd", "dolt", "show", "--json"]:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout=f'{{"connection_ok":true,"database":"{expected_database}"}}',
                stderr="",
            )
        if argv == migrate:
            (beads_root / "dolt" / expected_database / ".dolt").mkdir(parents=True, exist_ok=True)
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


def test_detect_startup_beads_state_never_reports_healthy_without_dolt_store(
    tmp_path: Path,
) -> None:
    beads_root = tmp_path / ".beads"
    beads_root.mkdir()
    (beads_root / "beads.db").write_bytes(b"")
    (beads_root / "issues.jsonl").write_text('{"id":"at-1"}\n', encoding="utf-8")
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
                stdout='{"summary":{"total_issues":3}}',
                stderr="",
            )
        raise AssertionError(f"unexpected command: {argv}")

    with patch("atelier.beads.exec.run_with_runner", side_effect=fake_run_with_runner):
        state = beads.detect_startup_beads_state(beads_root=beads_root, cwd=cwd)

    assert state.classification == "missing_dolt_with_legacy_sqlite"
    assert state.migration_eligible is True
    assert state.has_dolt_store is False
    assert state.dolt_issue_total == 3
    assert state.legacy_issue_total == 3
    assert state.dolt_count_source == "bd_stats_without_dolt_store"
    assert state.legacy_count_source == "bd_stats_legacy_sqlite"
    diagnostics = beads.format_startup_beads_diagnostics(state)
    assert "dolt_store=missing" in diagnostics
    assert "dolt_count_source=bd_stats_without_dolt_store" in diagnostics


def test_detect_startup_beads_state_skips_recovery_for_explicit_non_dolt_backend(
    tmp_path: Path,
) -> None:
    beads_root = tmp_path / ".beads"
    beads_root.mkdir()
    (beads_root / "beads.db").write_bytes(b"")
    (beads_root / "metadata.json").write_text('{"backend":"sqlite"}\n', encoding="utf-8")
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
                stdout='{"summary":{"total_issues":3}}',
                stderr="",
            )
        raise AssertionError(f"unexpected command: {argv}")

    with patch("atelier.beads.exec.run_with_runner", side_effect=fake_run_with_runner):
        state = beads.detect_startup_beads_state(beads_root=beads_root, cwd=cwd)

    assert state.classification == "startup_state_unknown"
    assert state.migration_eligible is False
    assert state.reason == "dolt_store_missing_for_non_dolt_backend"
    assert state.backend == "sqlite"
    assert state.dolt_count_source == "bd_stats_non_dolt_backend"


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


def test_detect_startup_beads_state_resamples_transient_mismatch(tmp_path: Path) -> None:
    beads_root = tmp_path / ".beads"
    (beads_root / "dolt" / "beads_at" / ".dolt").mkdir(parents=True)
    (beads_root / "beads.db").write_bytes(b"")
    cwd = tmp_path / "repo"
    cwd.mkdir()

    legacy_argv = ["bd", "--db", str(beads_root / "beads.db"), "stats", "--json"]
    dolt_calls = 0
    legacy_calls = 0

    def fake_run_with_runner(
        request: exec_util.CommandRequest,
    ) -> exec_util.CommandResult | None:
        nonlocal dolt_calls, legacy_calls
        argv = list(request.argv)
        if argv == ["bd", "stats", "--json"]:
            dolt_calls += 1
            total = 3 if dolt_calls == 1 else 4
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout=json.dumps({"summary": {"total_issues": total}}),
                stderr="",
            )
        if argv == legacy_argv:
            legacy_calls += 1
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout='{"summary":{"total_issues":4}}',
                stderr="",
            )
        raise AssertionError(f"unexpected command: {argv}")

    with patch("atelier.beads.exec.run_with_runner", side_effect=fake_run_with_runner):
        state = beads.detect_startup_beads_state(beads_root=beads_root, cwd=cwd)

    assert state.classification == "healthy_dolt"
    assert state.migration_eligible is False
    assert state.dolt_issue_total == 4
    assert state.legacy_issue_total == 4
    assert dolt_calls >= 2
    assert legacy_calls >= 2


def test_verify_migration_parity_with_resample_handles_transient_skew() -> None:
    before = beads.StartupBeadsState(
        classification="missing_dolt_with_legacy_sqlite",
        migration_eligible=True,
        has_dolt_store=False,
        has_legacy_sqlite=True,
        dolt_issue_total=None,
        legacy_issue_total=8,
        reason="legacy_sqlite_has_data_while_dolt_is_unavailable",
    )
    after = beads.StartupBeadsState(
        classification="healthy_dolt",
        migration_eligible=False,
        has_dolt_store=True,
        has_legacy_sqlite=True,
        dolt_issue_total=7,
        legacy_issue_total=8,
        reason="dolt_issue_total_is_healthy",
    )
    healed = beads.StartupBeadsState(
        classification="healthy_dolt",
        migration_eligible=False,
        has_dolt_store=True,
        has_legacy_sqlite=True,
        dolt_issue_total=8,
        legacy_issue_total=8,
        reason="dolt_issue_total_is_healthy",
    )

    with patch("atelier.beads.detect_startup_beads_state", return_value=healed):
        verified, state = beads._verify_migration_parity_with_resample(  # pyright: ignore[reportPrivateUsage]
            before=before,
            after=after,
            beads_root=Path("/beads"),
            cwd=Path("/repo"),
        )

    assert verified is True
    assert state == healed


def test_verify_migration_parity_with_resample_retries_more_than_once() -> None:
    before = beads.StartupBeadsState(
        classification="missing_dolt_with_legacy_sqlite",
        migration_eligible=True,
        has_dolt_store=False,
        has_legacy_sqlite=True,
        dolt_issue_total=None,
        legacy_issue_total=12,
        reason="legacy_sqlite_has_data_while_dolt_is_unavailable",
    )
    after = beads.StartupBeadsState(
        classification="healthy_dolt",
        migration_eligible=False,
        has_dolt_store=True,
        has_legacy_sqlite=True,
        dolt_issue_total=10,
        legacy_issue_total=12,
        reason="dolt_issue_total_is_healthy",
    )
    still_skewed = beads.StartupBeadsState(
        classification="healthy_dolt",
        migration_eligible=False,
        has_dolt_store=True,
        has_legacy_sqlite=True,
        dolt_issue_total=11,
        legacy_issue_total=12,
        reason="dolt_issue_total_is_healthy",
    )
    healed = beads.StartupBeadsState(
        classification="healthy_dolt",
        migration_eligible=False,
        has_dolt_store=True,
        has_legacy_sqlite=True,
        dolt_issue_total=12,
        legacy_issue_total=12,
        reason="dolt_issue_total_is_healthy",
    )

    with patch("atelier.beads.detect_startup_beads_state", side_effect=[still_skewed, healed]):
        verified, state = beads._verify_migration_parity_with_resample(  # pyright: ignore[reportPrivateUsage]
            before=before,
            after=after,
            beads_root=Path("/beads"),
            cwd=Path("/repo"),
        )

    assert verified is True
    assert state == healed


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


def test_find_agent_bead_reads_compatibility_label_namespace(
    tmp_path: Path,
) -> None:
    beads_root = tmp_path / ".beads"
    beads_root.mkdir()
    _write_beads_prefix_config(beads_root, "ts")
    beads._ISSUE_PREFIX_CACHE.clear()  # pyright: ignore[reportPrivateUsage]
    calls: list[list[str]] = []

    def fake_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:
        del beads_root, cwd
        calls.append(args)
        if args == ["list", "--label", "at:agent", "--title", "agent-7"]:
            return []
        if args == ["list", "--label", "ts:agent", "--title", "agent-7"]:
            return [{"id": "ts-agent", "title": "agent-7", "labels": ["ts:agent"]}]
        raise AssertionError(f"unexpected args: {args}")

    with patch("atelier.beads.run_bd_json", side_effect=fake_json):
        result = beads.find_agent_bead("agent-7", beads_root=beads_root, cwd=Path("/repo"))

    assert result == {"id": "ts-agent", "title": "agent-7", "labels": ["ts:agent"]}
    assert calls == [
        ["list", "--label", "at:agent", "--title", "agent-7"],
        ["list", "--label", "ts:agent", "--title", "agent-7"],
    ]


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


def test_run_bd_command_skips_dolt_commit_when_direct_mode(tmp_path: Path) -> None:
    beads_root = tmp_path / ".beads"
    beads_root.mkdir(parents=True)
    (beads_root / "metadata.json").write_text(
        json.dumps({"backend": "dolt", "dolt_mode": "direct"}),
        encoding="utf-8",
    )
    cwd = tmp_path / "repo"
    cwd.mkdir(parents=True)

    with (
        patch("atelier.beads.bd_invocation.ensure_supported_bd_version"),
        patch("atelier.beads.exec.run_with_runner") as run_with_runner,
    ):
        result = beads.run_bd_command(["dolt", "commit"], beads_root=beads_root, cwd=cwd)

    run_with_runner.assert_not_called()
    assert result.returncode == 0
    assert "dolt_mode is `direct`" in result.stdout.lower()


def test_resolve_dolt_commit_decision_requires_batch_pending_changes(tmp_path: Path) -> None:
    beads_root = tmp_path / ".beads"
    beads_root.mkdir(parents=True)
    (beads_root / "metadata.json").write_text(
        json.dumps({"backend": "dolt", "dolt_mode": "server"}),
        encoding="utf-8",
    )
    cwd = tmp_path / "repo"
    cwd.mkdir(parents=True)
    calls: list[list[str]] = []

    def fake_run_raw(
        argv: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
    ) -> exec_util.CommandResult | None:
        del cwd, env
        calls.append(list(argv))
        if argv == ["bd", "config", "get", "dolt.auto-commit", "--json"]:
            return exec_util.CommandResult(
                argv=tuple(argv),
                returncode=0,
                stdout='{"key":"dolt.auto-commit","value":"batch"}',
                stderr="",
            )
        if argv == ["bd", "dolt", "show", "--json"]:
            return exec_util.CommandResult(
                argv=tuple(argv),
                returncode=0,
                stdout='{"backend":"dolt","connection_ok":true}',
                stderr="",
            )
        if argv == ["bd", "vc", "status", "--json"]:
            return exec_util.CommandResult(
                argv=tuple(argv),
                returncode=0,
                stdout='{"working_set":{"tables":["issues"]}}',
                stderr="",
            )
        raise AssertionError(f"unexpected command: {argv}")

    with patch("atelier.beads._run_raw_bd_command", side_effect=fake_run_raw):
        decision = beads._resolve_dolt_commit_decision(  # pyright: ignore[reportPrivateUsage]
            args=["dolt", "commit"],
            beads_root=beads_root,
            cwd=cwd,
            env=beads.beads_env(beads_root),
        )

    assert decision is not None
    assert decision.should_run is True
    assert decision.reason == "batch_pending_changes"
    assert calls == [
        ["bd", "config", "get", "dolt.auto-commit", "--json"],
        ["bd", "dolt", "show", "--json"],
        ["bd", "vc", "status", "--json"],
    ]


def test_resolve_dolt_commit_decision_skips_non_indicative_nonempty_collections(
    tmp_path: Path,
) -> None:
    beads_root = tmp_path / ".beads"
    beads_root.mkdir(parents=True)
    (beads_root / "metadata.json").write_text(
        json.dumps({"backend": "dolt", "dolt_mode": "server"}),
        encoding="utf-8",
    )
    cwd = tmp_path / "repo"
    cwd.mkdir(parents=True)
    calls: list[list[str]] = []

    def fake_run_raw(
        argv: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
    ) -> exec_util.CommandResult | None:
        del cwd, env
        calls.append(list(argv))
        if argv == ["bd", "config", "get", "dolt.auto-commit", "--json"]:
            return exec_util.CommandResult(
                argv=tuple(argv),
                returncode=0,
                stdout='{"key":"dolt.auto-commit","value":"batch"}',
                stderr="",
            )
        if argv == ["bd", "dolt", "show", "--json"]:
            return exec_util.CommandResult(
                argv=tuple(argv),
                returncode=0,
                stdout='{"backend":"dolt","connection_ok":true}',
                stderr="",
            )
        if argv == ["bd", "vc", "status", "--json"]:
            return exec_util.CommandResult(
                argv=tuple(argv),
                returncode=0,
                stdout='{"working_set":[0,false,{"pending":0}]}',
                stderr="",
            )
        raise AssertionError(f"unexpected command: {argv}")

    with patch("atelier.beads._run_raw_bd_command", side_effect=fake_run_raw):
        decision = beads._resolve_dolt_commit_decision(  # pyright: ignore[reportPrivateUsage]
            args=["dolt", "commit"],
            beads_root=beads_root,
            cwd=cwd,
            env=beads.beads_env(beads_root),
        )

    assert decision is not None
    assert decision.should_run is False
    assert decision.reason == "no_pending_changes"
    assert calls == [
        ["bd", "config", "get", "dolt.auto-commit", "--json"],
        ["bd", "dolt", "show", "--json"],
        ["bd", "vc", "status", "--json"],
    ]


def test_resolve_dolt_commit_decision_skips_unsupported_commit_path(tmp_path: Path) -> None:
    beads_root = tmp_path / ".beads"
    beads_root.mkdir(parents=True)
    (beads_root / "metadata.json").write_text(
        json.dumps({"backend": "dolt", "dolt_mode": "server"}),
        encoding="utf-8",
    )
    cwd = tmp_path / "repo"
    cwd.mkdir(parents=True)
    calls: list[list[str]] = []

    def fake_run_raw(
        argv: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
    ) -> exec_util.CommandResult | None:
        del cwd, env
        calls.append(list(argv))
        if argv == ["bd", "config", "get", "dolt.auto-commit", "--json"]:
            return exec_util.CommandResult(
                argv=tuple(argv),
                returncode=0,
                stdout='{"key":"dolt.auto-commit","value":"batch"}',
                stderr="",
            )
        if argv == ["bd", "dolt", "show", "--json"]:
            return exec_util.CommandResult(
                argv=tuple(argv),
                returncode=1,
                stdout="",
                stderr="Error: no store available",
            )
        raise AssertionError(f"unexpected command: {argv}")

    with patch("atelier.beads._run_raw_bd_command", side_effect=fake_run_raw):
        decision = beads._resolve_dolt_commit_decision(  # pyright: ignore[reportPrivateUsage]
            args=["dolt", "commit"],
            beads_root=beads_root,
            cwd=cwd,
            env=beads.beads_env(beads_root),
        )

    assert decision is not None
    assert decision.should_run is False
    assert decision.reason == "dolt_capability_unavailable"
    assert "no store available" in decision.message
    assert calls == [
        ["bd", "config", "get", "dolt.auto-commit", "--json"],
        ["bd", "dolt", "show", "--json"],
    ]


def test_run_bd_command_skips_unsupported_dolt_commit_without_false_error(tmp_path: Path) -> None:
    beads_root = tmp_path / ".beads"
    beads_root.mkdir(parents=True)
    (beads_root / "metadata.json").write_text(
        json.dumps({"backend": "dolt", "dolt_mode": "server"}),
        encoding="utf-8",
    )
    cwd = tmp_path / "repo"
    cwd.mkdir(parents=True)

    def fake_run_with_runner(
        request: exec_util.CommandRequest,
    ) -> exec_util.CommandResult | None:
        argv = list(request.argv)
        if argv == ["bd", "config", "get", "dolt.auto-commit", "--json"]:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout='{"key":"dolt.auto-commit","value":"batch"}',
                stderr="",
            )
        if argv == ["bd", "dolt", "show", "--json"]:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=1,
                stdout="",
                stderr="Error: no store available",
            )
        raise AssertionError(f"unexpected command: {argv}")

    with (
        patch("atelier.beads.bd_invocation.ensure_supported_bd_version"),
        patch("atelier.beads.exec.run_with_runner", side_effect=fake_run_with_runner),
    ):
        result = beads.run_bd_command(["dolt", "commit"], beads_root=beads_root, cwd=cwd)

    assert result.returncode == 0
    assert "no store available" in result.stdout.lower()
    assert "command failed" not in result.stdout.lower()


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


def test_prime_addendum_strips_unsupported_command_lines() -> None:
    """Unsupported/deprecated command lines are removed from prime addendum output."""
    stdout = (
        "## Beads Workflow Context\n\n"
        "```\n"
        "[ ] bd export\n"
        "[ ] bd sync --flush-only\n"
        "[ ] bd sync --export\n"
        "[ ] bd dolt commit\n"
        "```\n"
        "- Use bd ready.\n"
    )
    with patch(
        "atelier.beads.exec.run_with_runner",
        return_value=type(
            "Result",
            (),
            {"returncode": 0, "stdout": stdout, "stderr": ""},
        )(),
    ):
        value = beads.prime_addendum(beads_root=Path("/beads"), cwd=Path("/repo"))

    assert value is not None
    assert "bd export" not in value
    assert "sync --export" not in value
    assert "bd dolt commit" not in value
    assert "bd sync --flush-only" in value
    assert "Use bd ready" in value


def test_prime_addendum_keeps_dolt_commit_when_batch_pending_changes_exist(
    tmp_path: Path,
) -> None:
    beads_root = tmp_path / ".beads"
    beads_root.mkdir(parents=True)
    (beads_root / "metadata.json").write_text(
        json.dumps({"backend": "dolt", "dolt_mode": "server"}),
        encoding="utf-8",
    )
    cwd = tmp_path / "repo"
    cwd.mkdir(parents=True)
    stdout = (
        "## Beads Workflow Context\n\n"
        "```\n"
        "[ ] bd export\n"
        "[ ] bd sync --export\n"
        "[ ] bd dolt commit\n"
        "```\n"
        "- Runtime-close checklist.\n"
    )

    def fake_run_with_runner(
        request: exec_util.CommandRequest,
    ) -> exec_util.CommandResult | None:
        argv = list(request.argv)
        if argv == ["bd", "prime", "--full"]:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout=stdout,
                stderr="",
            )
        if argv == ["bd", "config", "get", "dolt.auto-commit", "--json"]:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout='{"key":"dolt.auto-commit","value":"batch"}',
                stderr="",
            )
        if argv == ["bd", "dolt", "show", "--json"]:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout='{"backend":"dolt","connection_ok":true}',
                stderr="",
            )
        if argv == ["bd", "vc", "status", "--json"]:
            return exec_util.CommandResult(
                argv=request.argv,
                returncode=0,
                stdout='{"working_set":{"tables":["issues"]}}',
                stderr="",
            )
        raise AssertionError(f"unexpected command: {argv}")

    with patch("atelier.beads.exec.run_with_runner", side_effect=fake_run_with_runner):
        value = beads.prime_addendum(beads_root=beads_root, cwd=cwd)

    assert value is not None
    assert "bd export" not in value
    assert "sync --export" not in value
    assert "bd dolt commit" in value


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
        patch("atelier.beads._current_issue_prefix", side_effect=["atelier", "at"]),
        patch("atelier.beads.run_bd_command", side_effect=fake_command),
    ):
        changed = beads.ensure_issue_prefix("at", beads_root=Path("/beads"), cwd=Path("/repo"))

    assert changed is True
    assert calls == [["rename-prefix", "at-", "--repair"]]


def test_ensure_issue_prefix_sets_config_if_rename_does_not_update_it() -> None:
    calls: list[list[str]] = []

    def fake_command(
        args: list[str], *, beads_root: Path, cwd: Path, allow_failure: bool = False
    ) -> CompletedProcess[str]:
        calls.append(args)
        return CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    with (
        patch("atelier.beads._current_issue_prefix", side_effect=["atelier", "atelier"]),
        patch("atelier.beads.run_bd_command", side_effect=fake_command),
    ):
        changed = beads.ensure_issue_prefix("at", beads_root=Path("/beads"), cwd=Path("/repo"))

    assert changed is True
    assert calls == [["rename-prefix", "at-", "--repair"], ["config", "set", "issue_prefix", "at"]]


def test_ensure_issue_prefix_preserves_runtime_metadata_on_database_mismatch(
    tmp_path: Path,
) -> None:
    beads_root = tmp_path / ".beads"
    beads_root.mkdir()
    metadata_path = beads_root / "metadata.json"
    metadata_path.write_text(
        json.dumps(
            {
                "backend": "dolt",
                "dolt_mode": "server",
                "dolt_server_host": "127.0.0.1",
                "dolt_server_port": 3307,
                "dolt_server_user": "root",
                "dolt_database": "beads_at",
            }
        ),
        encoding="utf-8",
    )
    calls: list[list[str]] = []

    def fake_command(
        args: list[str], *, beads_root: Path, cwd: Path, allow_failure: bool = False
    ) -> CompletedProcess[str]:
        del beads_root, cwd, allow_failure
        calls.append(args)
        return CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    warnings: list[str] = []
    with (
        patch("atelier.beads._current_issue_prefix", side_effect=["atelier", "ops"]),
        patch("atelier.beads.run_bd_command", side_effect=fake_command),
        patch("atelier.beads.atelier_log.warning", side_effect=warnings.append),
    ):
        beads._ISSUE_PREFIX_CACHE.clear()  # pyright: ignore[reportPrivateUsage]
        beads._DOLT_RUNTIME_NORMALIZED.clear()  # pyright: ignore[reportPrivateUsage]
        changed = beads.ensure_issue_prefix("ops", beads_root=beads_root, cwd=tmp_path)

    assert changed is True
    assert calls == [["rename-prefix", "ops-", "--repair"]]
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert payload["dolt_database"] == "beads_at"
    assert any(
        "does not match project-scoped expected database beads_ops" in message
        for message in warnings
    )


def test_preview_issue_prefix_rename_skips_when_prefix_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(beads, "_current_issue_prefix", lambda *, beads_root, cwd: "at")

    def fake_run(*args: object, **kwargs: object) -> CompletedProcess[str]:
        raise AssertionError("bd rename-prefix should not run when preview is skipped")

    monkeypatch.setattr(beads, "run_bd_command", fake_run)
    preview = beads.preview_issue_prefix_rename(
        "at",
        beads_root=Path("/beads"),
        cwd=Path("/repo"),
    )
    assert preview is None


def test_preview_issue_prefix_rename_parses_dry_run(monkeypatch: pytest.MonkeyPatch) -> None:
    detail = (
        "DRY RUN: Would rename 2 issues from prefix 'old' to 'new'\n\n"
        "Sample changes:\n"
        "  old-one -> new-one\n"
        "  old-two -> new-two\n"
    )

    def fake_run(
        args: list[str],
        *,
        beads_root: Path,
        cwd: Path,
        allow_failure: bool = False,
    ) -> CompletedProcess[str]:
        del beads_root, cwd, allow_failure
        return CompletedProcess(args=args, returncode=0, stdout=detail, stderr="")

    monkeypatch.setattr(beads, "_current_issue_prefix", lambda *, beads_root, cwd: "old")
    monkeypatch.setattr(beads, "run_bd_command", fake_run)

    preview = beads.preview_issue_prefix_rename(
        "new",
        beads_root=Path("/beads"),
        cwd=Path("/repo"),
    )

    assert preview is not None
    assert preview.count == 2
    assert preview.current_prefix == "old"
    assert preview.target_prefix == "new"
    assert detail.strip() == preview.detail


def test_claim_epic_updates_assignee_and_status() -> None:
    issue = {"id": "atelier-9", "labels": [], "assignee": None}
    updated = {
        "id": "atelier-9",
        "status": "in_progress",
        "labels": ["at:hooked"],
        "assignee": "agent",
    }

    def fake_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:
        if args and args[0] == "show":
            return [updated]
        return [issue]

    with (
        patch("atelier.beads.run_bd_json", side_effect=fake_json),
        patch(
            "atelier.beads.run_bd_command", return_value=CompletedProcess([], 0, "", "")
        ) as run_command,
    ):
        beads.claim_epic(
            "atelier-9",
            "agent",
            beads_root=Path("/beads"),
            cwd=Path("/repo"),
        )

    commands = [call.args[0] for call in run_command.call_args_list]
    assert any(cmd[:3] == ["update", "atelier-9", "--claim"] for cmd in commands)
    assert any("--status" in cmd and "in_progress" in cmd for cmd in commands)


def test_claim_epic_allows_expected_takeover() -> None:
    issue = {"id": "atelier-9", "labels": [], "assignee": "agent-old"}
    updated = {
        "id": "atelier-9",
        "status": "in_progress",
        "labels": ["at:hooked"],
        "assignee": "agent-new",
    }
    show_calls = 0

    def fake_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:
        nonlocal show_calls
        if args and args[0] == "show":
            show_calls += 1
            return [issue] if show_calls == 1 else [updated]
        return [issue]

    with (
        patch("atelier.beads.run_bd_json", side_effect=fake_json),
        patch(
            "atelier.beads.run_bd_command", return_value=CompletedProcess([], 0, "", "")
        ) as run_command,
        patch(
            "atelier.beads_runtime.agent_hooks.release_epic_assignment", return_value=True
        ) as release_claim,
    ):
        beads.claim_epic(
            "atelier-9",
            "agent-new",
            beads_root=Path("/beads"),
            cwd=Path("/repo"),
            allow_takeover_from="agent-old",
        )

    commands = [call.args[0] for call in run_command.call_args_list]
    assert any(cmd[:3] == ["update", "atelier-9", "--claim"] for cmd in commands)
    release_claim.assert_called_once()


def test_claim_epic_fails_closed_when_takeover_owner_changes() -> None:
    issue = {"id": "atelier-9", "labels": ["at:epic"], "status": "open", "assignee": "agent-old"}

    with (
        patch("atelier.beads.run_bd_json", return_value=[issue]),
        patch("atelier.beads_runtime.agent_hooks.release_epic_assignment", return_value=False),
        patch("atelier.beads.die", side_effect=RuntimeError("die called")) as die_fn,
    ):
        with pytest.raises(RuntimeError, match="die called"):
            beads.claim_epic(
                "atelier-9",
                "agent-new",
                beads_root=Path("/beads"),
                cwd=Path("/repo"),
                allow_takeover_from="agent-old",
            )

    assert "takeover failed; claim ownership changed" in str(die_fn.call_args.args[0])


def test_claim_epic_retries_until_hooked_state_visible() -> None:
    issue = {"id": "atelier-9", "status": "open", "labels": ["at:epic"], "assignee": None}
    incomplete = {"id": "atelier-9", "status": "open", "labels": ["at:epic"], "assignee": "agent"}
    complete = {
        "id": "atelier-9",
        "status": "in_progress",
        "labels": ["at:epic", "at:hooked"],
        "assignee": "agent",
    }
    show_calls = 0

    def fake_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:
        nonlocal show_calls
        if args and args[0] == "show":
            show_calls += 1
            if show_calls == 1:
                return [issue]
            if show_calls == 2:
                return [incomplete]
            return [complete]
        return [issue]

    with (
        patch("atelier.beads.run_bd_json", side_effect=fake_json),
        patch(
            "atelier.beads.run_bd_command", return_value=CompletedProcess([], 0, "", "")
        ) as run_command,
    ):
        beads.claim_epic(
            "atelier-9",
            "agent",
            beads_root=Path("/beads"),
            cwd=Path("/repo"),
        )

    commands = [call.args[0] for call in run_command.call_args_list]
    update_commands = [cmd for cmd in commands if "--status" in cmd and "in_progress" in cmd]
    assert len(update_commands) == 2


def test_claim_epic_fails_closed_when_hook_state_not_applied() -> None:
    issue = {"id": "atelier-9", "status": "open", "labels": ["at:epic"], "assignee": None}
    incomplete = {"id": "atelier-9", "status": "open", "labels": ["at:epic"], "assignee": "agent"}
    show_calls = 0

    def fake_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:
        nonlocal show_calls
        if args and args[0] == "show":
            show_calls += 1
            if show_calls == 1:
                return [issue]
            return [incomplete]
        return [issue]

    with (
        patch("atelier.beads.run_bd_json", side_effect=fake_json),
        patch("atelier.beads.run_bd_command", return_value=CompletedProcess([], 0, "", "")),
        patch("atelier.beads.die", side_effect=RuntimeError("die called")) as die_fn,
    ):
        with pytest.raises(RuntimeError, match="die called"):
            beads.claim_epic(
                "atelier-9",
                "agent",
                beads_root=Path("/beads"),
                cwd=Path("/repo"),
            )

    assert "expected status=in_progress and label at:hooked" in str(die_fn.call_args.args[0])


def test_release_epic_assignment_skips_when_assignee_no_longer_matches() -> None:
    issue = {"id": "epic-9", "labels": ["at:epic", "at:hooked"], "assignee": "agent-new"}

    with (
        patch("atelier.beads.run_bd_json", return_value=[issue]),
        patch("atelier.beads.run_bd_command") as run_command,
    ):
        released = beads.release_epic_assignment(
            "epic-9",
            beads_root=Path("/beads"),
            cwd=Path("/repo"),
            expected_assignee="agent-old",
            expected_hooked=True,
        )

    assert released is False
    run_command.assert_not_called()


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
    state = {"description": "role: worker\n"}
    captured: dict[str, str] = {}
    called: dict[str, list[str]] = {}

    def fake_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:
        return [{"id": "atelier-agent", "description": state["description"]}]

    def fake_command(
        args: list[str], *, beads_root: Path, cwd: Path, allow_failure: bool = False
    ) -> CompletedProcess[str]:
        called["args"] = args
        return CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    def fake_update(issue_id: str, description: str, *, beads_root: Path, cwd: Path) -> None:
        captured["id"] = issue_id
        captured["description"] = description
        state["description"] = description

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


def test_update_issue_description_fields_serializes_concurrent_writers() -> None:
    state = {"description": "scope: demo\n"}
    release_first_write = threading.Event()
    first_write_started = threading.Event()
    errors: list[BaseException] = []
    write_order = 0

    def fake_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:
        del args, beads_root, cwd
        return [{"id": "issue-1", "description": state["description"]}]

    def fake_update(issue_id: str, description: str, *, beads_root: Path, cwd: Path) -> None:
        del issue_id, beads_root, cwd
        nonlocal write_order
        write_order += 1
        if write_order == 1:
            first_write_started.set()
            assert release_first_write.wait(timeout=1.0)
        state["description"] = description

    def apply_fields(fields: dict[str, str | None]) -> None:
        try:
            beads.update_issue_description_fields(
                "issue-1",
                fields,
                beads_root=Path("/beads"),
                cwd=Path("/repo"),
            )
        except BaseException as exc:  # pragma: no cover - assertion surface
            errors.append(exc)

    with (
        patch("atelier.beads.run_bd_json", side_effect=fake_json),
        patch("atelier.beads._update_issue_description", side_effect=fake_update),
    ):
        first = threading.Thread(target=apply_fields, args=({"hook_bead": "epic-1"},))
        second = threading.Thread(target=apply_fields, args=({"pr_state": "in-review"},))
        first.start()
        assert first_write_started.wait(timeout=1.0)
        second.start()
        time.sleep(0.05)
        release_first_write.set()
        first.join(timeout=1.0)
        second.join(timeout=1.0)

    assert not first.is_alive()
    assert not second.is_alive()
    assert not errors
    assert "hook_bead: epic-1" in state["description"]
    assert "pr_state: in-review" in state["description"]


def test_issue_write_lock_releases_global_guard_before_file_lock(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class _TrackingLock:
        def __init__(self) -> None:
            self._lock = threading.Lock()
            self.held = False

        def acquire(self, blocking: bool = True, timeout: float = -1.0) -> bool:
            if timeout < 0:
                acquired = self._lock.acquire(blocking)
            else:
                acquired = self._lock.acquire(blocking, timeout)
            if acquired:
                self.held = True
            return acquired

        def release(self) -> None:
            self.held = False
            self._lock.release()

        def __enter__(self) -> "_TrackingLock":
            self.acquire()
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            self.release()

    beads_root = tmp_path / ".beads"
    beads_root.mkdir()
    guard = _TrackingLock()
    saw_guard_during_acquire: list[bool] = []

    def fake_acquire(handle: object) -> None:
        del handle
        saw_guard_during_acquire.append(guard.held)

    monkeypatch.setattr(beads, "_ISSUE_WRITE_LOCK_STATE_GUARD", guard)
    monkeypatch.setattr(beads, "_ISSUE_WRITE_LOCK_STATE", {})
    monkeypatch.setattr(beads, "_ISSUE_WRITE_LOCAL_LOCKS", {})
    monkeypatch.setattr(beads, "_acquire_issue_file_lock", fake_acquire)

    with beads._issue_write_lock("issue-1", beads_root=beads_root):  # pyright: ignore[reportPrivateUsage]
        pass

    assert saw_guard_during_acquire == [False]


def test_issue_write_lock_fails_closed_on_file_lock_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    beads_root = tmp_path / ".beads"
    beads_root.mkdir()
    key = beads._issue_write_lock_key(  # pyright: ignore[reportPrivateUsage]
        issue_id="issue-1", beads_root=beads_root
    )

    def fail_acquire(handle: object) -> None:
        del handle
        raise OSError("boom")

    monkeypatch.setattr(beads, "_ISSUE_WRITE_LOCK_STATE", {})
    monkeypatch.setattr(beads, "_ISSUE_WRITE_LOCAL_LOCKS", {})
    monkeypatch.setattr(beads, "_acquire_issue_file_lock", fail_acquire)

    def fake_die(message: str, code: int = 1) -> None:
        raise RuntimeError(f"{code}:{message}")

    with patch("atelier.beads.die", side_effect=fake_die):
        with pytest.raises(RuntimeError, match="1:failed to acquire issue write lock for issue-1"):
            with beads._issue_write_lock("issue-1", beads_root=beads_root):  # pyright: ignore[reportPrivateUsage]
                pytest.fail("context body should not execute on lock acquisition failure")

    assert key not in beads._ISSUE_WRITE_LOCK_STATE  # pyright: ignore[reportPrivateUsage]


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
    state: dict[str, object] = {
        "id": "msg-1",
        "description": description,
        "assignee": None,
    }
    captured: dict[str, str] = {}
    commands: list[list[str]] = []

    def fake_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:
        return [dict(state)]

    def fake_run_command(
        args: list[str], *, beads_root: Path, cwd: Path, allow_failure: bool = False
    ) -> CompletedProcess[str]:
        del beads_root, cwd, allow_failure
        commands.append(args)
        if args[:3] == ["update", "msg-1", "--claim"]:
            state["assignee"] = "atelier/worker/agent"
        return CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    def fake_update(issue_id: str, description: str, *, beads_root: Path, cwd: Path) -> None:
        captured["id"] = issue_id
        captured["description"] = description
        state["description"] = description

    with (
        patch("atelier.beads.run_bd_json", side_effect=fake_json),
        patch("atelier.beads.run_bd_command", side_effect=fake_run_command),
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
    assert any(cmd[:3] == ["update", "msg-1", "--claim"] for cmd in commands)


def test_claim_queue_message_rejects_second_concurrent_claimant() -> None:
    state_lock = threading.Lock()
    state: dict[str, object] = {
        "id": "msg-2",
        "description": "---\nqueue: triage\n---\n\nBody\n",
        "assignee": None,
    }
    outcome: dict[str, str] = {}
    thread_agents: dict[int, str] = {}

    def fake_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:
        del args, beads_root, cwd
        with state_lock:
            return [dict(state)]

    def fake_run_command(
        args: list[str], *, beads_root: Path, cwd: Path, allow_failure: bool = False
    ) -> CompletedProcess[str]:
        del beads_root, cwd, allow_failure
        with state_lock:
            if args[:3] == ["update", "msg-2", "--claim"]:
                if state["assignee"] is None:
                    actor = thread_agents.get(threading.get_ident(), "")
                    state["assignee"] = actor
                    if "winner" not in outcome:
                        outcome["winner"] = actor
                    return CompletedProcess(args=args, returncode=0, stdout="", stderr="")
                return CompletedProcess(
                    args=args, returncode=1, stdout="", stderr="already claimed"
                )
        return CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    def fake_update(issue_id: str, description: str, *, beads_root: Path, cwd: Path) -> None:
        del issue_id, beads_root, cwd
        with state_lock:
            state["description"] = description

    failures: list[str] = []

    def claim(agent_id: str) -> None:
        thread_agents[threading.get_ident()] = agent_id
        try:
            beads.claim_queue_message(
                "msg-2",
                agent_id,
                beads_root=Path("/beads"),
                cwd=Path("/repo"),
            )
        except RuntimeError as exc:
            failures.append(str(exc))

    with (
        patch("atelier.beads.run_bd_json", side_effect=fake_json),
        patch("atelier.beads.run_bd_command", side_effect=fake_run_command),
        patch("atelier.beads._update_issue_description", side_effect=fake_update),
        patch("atelier.beads.die", side_effect=RuntimeError),
    ):
        first = threading.Thread(target=claim, args=("agent-a",))
        second = threading.Thread(target=claim, args=("agent-b",))
        first.start()
        second.start()
        first.join(timeout=1.0)
        second.join(timeout=1.0)

    assert not first.is_alive()
    assert not second.is_alive()
    assert len(failures) == 1
    with state_lock:
        description = str(state["description"])
    assert "claimed_by:" in description
    assert "claimed_at:" in description


def test_claim_queue_message_fails_closed_after_metadata_conflict_retry_exhaustion() -> None:
    state: dict[str, object] = {
        "id": "msg-3",
        "description": "---\nqueue: triage\n---\n\nBody\n",
        "assignee": None,
    }
    updates: list[str] = []

    def fake_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:
        del args, beads_root, cwd
        return [dict(state)]

    def fake_run_command(
        args: list[str], *, beads_root: Path, cwd: Path, allow_failure: bool = False
    ) -> CompletedProcess[str]:
        del beads_root, cwd, allow_failure
        if args[:3] == ["update", "msg-3", "--claim"]:
            state["assignee"] = "agent-a"
        return CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    def fake_update(issue_id: str, description: str, *, beads_root: Path, cwd: Path) -> None:
        del issue_id, beads_root, cwd
        updates.append(description)
        # Simulate another writer overwriting metadata immediately after each write.
        state["description"] = "---\nqueue: triage\n---\n\nBody\n"

    with (
        patch("atelier.beads.run_bd_json", side_effect=fake_json),
        patch("atelier.beads.run_bd_command", side_effect=fake_run_command),
        patch("atelier.beads._update_issue_description", side_effect=fake_update),
        patch("atelier.beads.die", side_effect=RuntimeError("die called")) as die_fn,
    ):
        with pytest.raises(RuntimeError, match="die called"):
            beads.claim_queue_message(
                "msg-3",
                "agent-a",
                beads_root=Path("/beads"),
                cwd=Path("/repo"),
            )

    assert len(updates) == beads._DESCRIPTION_UPDATE_MAX_ATTEMPTS  # pyright: ignore[reportPrivateUsage]
    assert "concurrent queue claim metadata conflict for msg-3" in str(die_fn.call_args.args[0])


def test_list_inbox_messages_filters_unread() -> None:
    with patch("atelier.beads.run_bd_json", return_value=[{"id": "atelier-77"}]) as run_json:
        result = beads.list_inbox_messages("alice", beads_root=Path("/beads"), cwd=Path("/repo"))
    assert result
    called_args = run_json.call_args.args[0]
    assert called_args == [
        "list",
        "--label",
        "at:message",
        "--assignee",
        "alice",
        "--label",
        "at:unread",
    ]


def test_list_inbox_messages_auto_resolves_stale_review_feedback_message() -> None:
    inbox_issue = {
        "id": "msg-review-feedback",
        "title": "NEEDS-DECISION: Review feedback unchanged (at-epic.1)",
        "description": "---\nthread: at-epic.1\n---\n\nBody\n",
        "assignee": "planner",
    }
    thread_issue = {
        "id": "at-epic.1",
        "status": "in_progress",
        "description": "pr_state: pr-open\npr_number: 42\n",
    }
    open_message = dict(inbox_issue)
    open_message["status"] = "open"
    closed_message = dict(inbox_issue)
    closed_message["status"] = "closed"
    message_show_count = 0

    def fake_read_only(
        args: list[str],
        *,
        beads_root: Path,
        cwd: Path,
    ) -> tuple[list[dict[str, object]], str | None]:
        del beads_root, cwd
        nonlocal message_show_count
        if args == ["show", "at-epic.1"]:
            return [thread_issue], None
        if args == ["show", "msg-review-feedback"]:
            message_show_count += 1
            if message_show_count == 1:
                return [open_message], None
            return [closed_message], None
        return [], None

    with (
        patch("atelier.beads.run_bd_json", return_value=[inbox_issue]),
        patch("atelier.beads.run_bd_json_read_only", side_effect=fake_read_only),
        patch("atelier.beads._repo_slug_for_gate", return_value="owner/repo"),
        patch("atelier.beads.prs.unresolved_review_thread_count", return_value=0),
        patch("atelier.beads.run_bd_command") as run_command,
    ):
        queued = beads.list_inbox_messages("planner", beads_root=Path("/beads"), cwd=Path("/repo"))

    assert queued == []
    assert [call.args[0] for call in run_command.call_args_list] == [
        [
            "update",
            "msg-review-feedback",
            "--append-notes",
            "auto-resolved stale NEEDS-DECISION: unresolved review threads=0 (pr #42)",
        ],
        ["close", "msg-review-feedback"],
        ["update", "msg-review-feedback", "--remove-label", "at:unread"],
    ]


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


def test_list_queue_messages_dedupes_needs_decision_thread_reason() -> None:
    issues = [
        {
            "id": "msg-old",
            "title": "NEEDS-DECISION: Startup preparation failed (at-epic.1)",
            "created_at": "2026-03-02T01:00:00Z",
            "description": "---\nqueue: planner\nthread: at-epic.1\n---\n\nBody\n",
            "assignee": None,
        },
        {
            "id": "msg-new",
            "title": "NEEDS-DECISION: Startup preparation failed (at-epic.1)",
            "created_at": "2026-03-02T02:00:00Z",
            "description": "---\nqueue: planner\nthread: at-epic.1\n---\n\nBody\n",
            "assignee": None,
        },
    ]

    with (
        patch("atelier.beads.run_bd_json", return_value=issues),
        patch("atelier.beads.run_bd_command") as run_command,
    ):
        queued = beads.list_queue_messages(beads_root=Path("/beads"), cwd=Path("/repo"))

    assert [item["id"] for item in queued] == ["msg-new"]
    run_command.assert_called_once_with(
        ["update", "msg-old", "--remove-label", "at:unread"],
        beads_root=Path("/beads"),
        cwd=Path("/repo"),
        allow_failure=True,
    )


def test_list_queue_messages_auto_resolves_stale_closed_active_pr_lifecycle() -> None:
    queue_issue = {
        "id": "msg-closed-active",
        "title": "NEEDS-DECISION: Closed changeset has active PR lifecycle (at-epic.1)",
        "created_at": "2026-03-02T02:00:00Z",
        "description": "---\nqueue: planner\nthread: at-epic.1\n---\n\nBody\n",
        "assignee": None,
    }
    thread_issue = {
        "id": "at-epic.1",
        "status": "in_progress",
        "description": "pr_state: pr-open\n",
    }
    open_message = dict(queue_issue)
    open_message["status"] = "open"
    closed_message = dict(queue_issue)
    closed_message["status"] = "closed"
    message_show_count = 0

    def fake_run_json(
        args: list[str],
        *,
        beads_root: Path,
        cwd: Path,
    ) -> list[dict[str, object]]:
        del beads_root, cwd
        if args[:1] == ["list"]:
            return [queue_issue]
        return []

    def fake_read_only(
        args: list[str],
        *,
        beads_root: Path,
        cwd: Path,
    ) -> tuple[list[dict[str, object]], str | None]:
        del beads_root, cwd
        nonlocal message_show_count
        if args == ["show", "at-epic.1"]:
            return [thread_issue], None
        if args == ["show", "msg-closed-active"]:
            message_show_count += 1
            if message_show_count == 1:
                return [open_message], None
            return [closed_message], None
        return [], None

    with (
        patch("atelier.beads.run_bd_json", side_effect=fake_run_json),
        patch("atelier.beads.run_bd_json_read_only", side_effect=fake_read_only),
        patch("atelier.beads.run_bd_command") as run_command,
    ):
        queued = beads.list_queue_messages(beads_root=Path("/beads"), cwd=Path("/repo"))

    assert queued == []
    assert [call.args[0] for call in run_command.call_args_list] == [
        [
            "update",
            "msg-closed-active",
            "--append-notes",
            "auto-resolved stale NEEDS-DECISION: changeset status=in_progress",
        ],
        ["close", "msg-closed-active"],
        ["update", "msg-closed-active", "--remove-label", "at:unread"],
    ]


def test_list_queue_messages_auto_resolves_review_feedback_when_threads_resolved() -> None:
    queue_issue = {
        "id": "msg-review-feedback",
        "title": "NEEDS-DECISION: Review feedback unchanged (at-epic.1)",
        "created_at": "2026-03-02T02:00:00Z",
        "description": "---\nqueue: planner\nthread: at-epic.1\n---\n\nBody\n",
        "assignee": None,
    }
    thread_issue = {
        "id": "at-epic.1",
        "status": "blocked",
        "description": "pr_state: in-review\npr_number: 42\n",
    }
    open_message = dict(queue_issue)
    open_message["status"] = "open"
    closed_message = dict(queue_issue)
    closed_message["status"] = "closed"
    message_show_count = 0

    def fake_run_json(
        args: list[str],
        *,
        beads_root: Path,
        cwd: Path,
    ) -> list[dict[str, object]]:
        del beads_root, cwd
        if args[:1] == ["list"]:
            return [queue_issue]
        return []

    def fake_read_only(
        args: list[str],
        *,
        beads_root: Path,
        cwd: Path,
    ) -> tuple[list[dict[str, object]], str | None]:
        del beads_root, cwd
        nonlocal message_show_count
        if args == ["show", "at-epic.1"]:
            return [thread_issue], None
        if args == ["show", "msg-review-feedback"]:
            message_show_count += 1
            if message_show_count == 1:
                return [open_message], None
            return [closed_message], None
        return [], None

    with (
        patch("atelier.beads.run_bd_json", side_effect=fake_run_json),
        patch("atelier.beads.run_bd_json_read_only", side_effect=fake_read_only),
        patch("atelier.beads._repo_slug_for_gate", return_value="owner/repo"),
        patch("atelier.beads.prs.unresolved_review_thread_count", return_value=0),
        patch("atelier.beads.run_bd_command") as run_command,
    ):
        queued = beads.list_queue_messages(beads_root=Path("/beads"), cwd=Path("/repo"))

    assert queued == []
    assert [call.args[0] for call in run_command.call_args_list] == [
        [
            "update",
            "msg-review-feedback",
            "--append-notes",
            "auto-resolved stale NEEDS-DECISION: unresolved review threads=0 (pr #42)",
        ],
        ["close", "msg-review-feedback"],
        ["update", "msg-review-feedback", "--remove-label", "at:unread"],
    ]


def test_list_queue_messages_keeps_unread_label_when_stale_close_not_confirmed() -> None:
    queue_issue = {
        "id": "msg-review-feedback",
        "title": "NEEDS-DECISION: Review feedback unchanged (at-epic.1)",
        "created_at": "2026-03-02T02:00:00Z",
        "description": "---\nqueue: planner\nthread: at-epic.1\n---\n\nBody\n",
        "assignee": None,
    }
    thread_issue = {
        "id": "at-epic.1",
        "status": "blocked",
        "description": "pr_state: in-review\npr_number: 42\n",
    }
    open_message = dict(queue_issue)
    open_message["status"] = "open"

    def fake_run_json(
        args: list[str],
        *,
        beads_root: Path,
        cwd: Path,
    ) -> list[dict[str, object]]:
        del beads_root, cwd
        if args[:1] == ["list"]:
            return [queue_issue]
        return []

    def fake_read_only(
        args: list[str],
        *,
        beads_root: Path,
        cwd: Path,
    ) -> tuple[list[dict[str, object]], str | None]:
        del beads_root, cwd
        if args == ["show", "at-epic.1"]:
            return [thread_issue], None
        if args == ["show", "msg-review-feedback"]:
            return [open_message], None
        return [], None

    with (
        patch("atelier.beads.run_bd_json", side_effect=fake_run_json),
        patch("atelier.beads.run_bd_json_read_only", side_effect=fake_read_only),
        patch("atelier.beads._repo_slug_for_gate", return_value="owner/repo"),
        patch("atelier.beads.prs.unresolved_review_thread_count", return_value=0),
        patch("atelier.beads.run_bd_command") as run_command,
    ):
        queued = beads.list_queue_messages(beads_root=Path("/beads"), cwd=Path("/repo"))

    assert queued == []
    assert [call.args[0] for call in run_command.call_args_list] == [
        [
            "update",
            "msg-review-feedback",
            "--append-notes",
            "auto-resolved stale NEEDS-DECISION: unresolved review threads=0 (pr #42)",
        ],
        ["close", "msg-review-feedback"],
    ]


def test_list_queue_messages_keeps_review_feedback_when_threads_unresolved() -> None:
    queue_issue = {
        "id": "msg-review-feedback",
        "title": "NEEDS-DECISION: Review feedback unchanged (at-epic.1)",
        "created_at": "2026-03-02T02:00:00Z",
        "description": "---\nqueue: planner\nthread: at-epic.1\n---\n\nBody\n",
        "assignee": None,
    }
    thread_issue = {
        "id": "at-epic.1",
        "status": "blocked",
        "description": "pr_state: in-review\npr_number: 42\n",
    }

    def fake_run_json(
        args: list[str],
        *,
        beads_root: Path,
        cwd: Path,
    ) -> list[dict[str, object]]:
        del beads_root, cwd
        if args[:1] == ["list"]:
            return [queue_issue]
        return []

    with (
        patch("atelier.beads.run_bd_json", side_effect=fake_run_json),
        patch("atelier.beads.run_bd_json_read_only", return_value=([thread_issue], None)),
        patch("atelier.beads._repo_slug_for_gate", return_value="owner/repo"),
        patch("atelier.beads.prs.unresolved_review_thread_count", return_value=2),
        patch("atelier.beads.run_bd_command") as run_command,
    ):
        queued = beads.list_queue_messages(beads_root=Path("/beads"), cwd=Path("/repo"))

    assert [item["id"] for item in queued] == ["msg-review-feedback"]
    run_command.assert_not_called()


def test_list_queue_messages_keeps_latest_active_closed_pr_lifecycle_notification() -> None:
    older = {
        "id": "msg-old",
        "title": "NEEDS-DECISION: Closed changeset has active PR lifecycle (at-epic.1)",
        "created_at": "2026-03-02T01:00:00Z",
        "description": "---\nqueue: planner\nthread: at-epic.1\n---\n\nBody\n",
        "assignee": None,
    }
    newer = {
        "id": "msg-new",
        "title": "NEEDS-DECISION: Closed changeset has active PR lifecycle (at-epic.1)",
        "created_at": "2026-03-02T03:00:00Z",
        "description": "---\nqueue: planner\nthread: at-epic.1\n---\n\nBody\n",
        "assignee": None,
    }
    thread_issue = {
        "id": "at-epic.1",
        "status": "closed",
        "description": "pr_state: pr-open\n",
    }

    def fake_run_json(
        args: list[str],
        *,
        beads_root: Path,
        cwd: Path,
    ) -> list[dict[str, object]]:
        del beads_root, cwd
        if args[:1] == ["list"]:
            return [older, newer]
        return []

    with (
        patch("atelier.beads.run_bd_json", side_effect=fake_run_json),
        patch("atelier.beads.run_bd_json_read_only", return_value=([thread_issue], None)),
        patch("atelier.beads.run_bd_command") as run_command,
    ):
        queued = beads.list_queue_messages(beads_root=Path("/beads"), cwd=Path("/repo"))

    assert [item["id"] for item in queued] == ["msg-new"]
    run_command.assert_called_once_with(
        ["update", "msg-old", "--remove-label", "at:unread"],
        beads_root=Path("/beads"),
        cwd=Path("/repo"),
        allow_failure=True,
    )


def test_list_queue_messages_tolerates_missing_thread_issue() -> None:
    queue_issue = {
        "id": "msg-closed-active",
        "title": "NEEDS-DECISION: Closed changeset has active PR lifecycle (at-epic.1)",
        "created_at": "2026-03-02T02:00:00Z",
        "description": "---\nqueue: planner\nthread: at-epic.1\n---\n\nBody\n",
        "assignee": None,
    }

    def fake_run_json(
        args: list[str],
        *,
        beads_root: Path,
        cwd: Path,
    ) -> list[dict[str, object]]:
        del beads_root, cwd
        if args[:1] == ["list"]:
            return [queue_issue]
        return []

    with (
        patch("atelier.beads.run_bd_json", side_effect=fake_run_json),
        patch(
            "atelier.beads.run_bd_json_read_only",
            return_value=([], "command failed: bd show at-epic.1 --json (exit 1)"),
        ),
        patch("atelier.beads.run_bd_command") as run_command,
    ):
        queued = beads.list_queue_messages(beads_root=Path("/beads"), cwd=Path("/repo"))

    assert [item["id"] for item in queued] == ["msg-closed-active"]
    run_command.assert_not_called()


def test_mark_message_read_updates_labels() -> None:
    with patch("atelier.beads.run_bd_command") as run_command:
        beads.mark_message_read("atelier-88", beads_root=Path("/beads"), cwd=Path("/repo"))
    called_args = run_command.call_args.args[0]
    assert called_args == ["update", "atelier-88", "--remove-label", "at:unread"]


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


def test_list_epics_uses_at_epic_all_and_unbounded_limit() -> None:
    """Regression: list_epics must bypass default caps with explicit limit."""
    with patch("atelier.beads.run_bd_json", return_value=[]) as run_json:
        beads.list_epics(beads_root=Path("/beads"), cwd=Path("/repo"), include_closed=True)
    called_args = run_json.call_args.args[0]
    assert "list" in called_args
    assert "--label" in called_args
    assert "at:epic" in called_args
    assert "--all" in called_args
    assert "--limit" in called_args
    assert "0" in called_args


def test_list_epics_finds_epic_beyond_default_window() -> None:
    """Regression: high-churn store with non-epics exceeding default list window."""
    epic = {"id": "at-epic", "status": "open", "labels": ["at:epic"]}

    def fake_run(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:
        if "at:epic" in args and "--all" in args and "--limit" in args and "0" in args:
            return [epic]
        return []

    with patch("atelier.beads.run_bd_json", side_effect=fake_run):
        result = beads.list_epics(
            beads_root=Path("/beads"), cwd=Path("/repo"), include_closed=False
        )
    assert len(result) == 1
    assert result[0]["id"] == "at-epic"


def test_epic_discovery_parity_report_detects_identity_violations() -> None:
    indexed_epic = {
        "id": "at-indexed",
        "status": "open",
        "labels": ["at:epic"],
        "issue_type": "epic",
    }
    active_issues = [
        indexed_epic,
        {
            "id": "at-missing",
            "status": "in_progress",
            "issue_type": "epic",
            "labels": [],
        },
        {
            "id": "at-indexed.1",
            "status": "open",
            "issue_type": "task",
            "labels": [],
            "parent": "at-indexed",
        },
    ]

    def fake_run(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:
        if args[:4] == ["list", "--all", "--limit", "0"]:
            return active_issues
        if args[:3] == ["list", "--label", "at:epic"]:
            return [indexed_epic]
        return []

    with patch("atelier.beads.run_bd_json", side_effect=fake_run):
        report = beads.epic_discovery_parity_report(
            beads_root=Path("/beads"),
            cwd=Path("/repo"),
        )

    assert report.active_top_level_work_count == 2
    assert report.indexed_active_epic_count == 1
    assert report.missing_from_index == ()
    assert len(report.missing_executable_identity) == 1
    violation = report.missing_executable_identity[0]
    assert violation.issue_id == "at-missing"
    assert violation.remediation_command == "bd update at-missing --type epic --add-label at:epic"


def test_epic_discovery_parity_report_detects_index_mismatch() -> None:
    active_issue = {
        "id": "at-epic",
        "status": "open",
        "issue_type": "epic",
        "labels": ["at:epic"],
    }

    def fake_run(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:
        if args[:4] == ["list", "--all", "--limit", "0"]:
            return [active_issue]
        if args[:3] == ["list", "--label", "at:epic"]:
            return []
        return []

    with patch("atelier.beads.run_bd_json", side_effect=fake_run):
        report = beads.epic_discovery_parity_report(
            beads_root=Path("/beads"),
            cwd=Path("/repo"),
        )

    assert report.active_top_level_work_count == 1
    assert report.indexed_active_epic_count == 0
    assert report.missing_executable_identity == ()
    assert report.missing_from_index == ("at-epic",)


def test_epic_discovery_parity_report_flags_type_drift_with_epic_label() -> None:
    indexed_epic = {
        "id": "at-indexed",
        "status": "open",
        "issue_type": "epic",
        "labels": ["at:epic"],
    }
    type_drift_issue = {
        "id": "at-type-drift",
        "status": "open",
        "issue_type": "task",
        "labels": ["at:epic"],
    }

    def fake_run(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:
        if args[:4] == ["list", "--all", "--limit", "0"]:
            return [indexed_epic, type_drift_issue]
        if args[:3] == ["list", "--label", "at:epic"]:
            return [indexed_epic, type_drift_issue]
        return []

    with patch("atelier.beads.run_bd_json", side_effect=fake_run):
        report = beads.epic_discovery_parity_report(
            beads_root=Path("/beads"),
            cwd=Path("/repo"),
        )

    assert report.active_top_level_work_count == 2
    assert report.indexed_active_epic_count == 1
    assert report.missing_from_index == ()
    assert len(report.missing_executable_identity) == 1
    violation = report.missing_executable_identity[0]
    assert violation.issue_id == "at-type-drift"
    assert violation.issue_type == "task"
    assert violation.labels == ("at:epic",)
    assert (
        violation.remediation_command == "bd update at-type-drift --type epic --add-label at:epic"
    )


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


def test_close_epic_if_complete_reopens_active_pr_descendant() -> None:
    def fake_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:
        if args[:2] == ["show", "epic-1"]:
            return [{"id": "epic-1", "labels": ["at:epic"], "status": "in_progress"}]
        if args[:2] == ["list", "--parent"] and args[2] == "epic-1":
            return [
                {
                    "id": "epic-1.1",
                    "status": "closed",
                    "description": "pr_state: draft-pr\n",
                    "labels": [],
                    "type": "task",
                }
            ]
        if args[:2] == ["list", "--parent"] and args[2] == "epic-1.1":
            return []
        return []

    with (
        patch("atelier.beads.run_bd_json", side_effect=fake_json),
        patch("atelier.beads.mark_issue_in_progress") as mark_issue_in_progress,
        patch("atelier.beads.close_issue") as close_issue,
        patch("atelier.beads.clear_agent_hook") as clear_hook,
    ):
        result = beads.close_epic_if_complete(
            "epic-1",
            "agent-1",
            beads_root=Path("/beads"),
            cwd=Path("/repo"),
        )

    assert result is False
    mark_issue_in_progress.assert_called_once_with(
        "epic-1.1",
        beads_root=Path("/beads"),
        cwd=Path("/repo"),
    )
    close_issue.assert_not_called()
    clear_hook.assert_not_called()


def test_close_epic_if_complete_dry_run_skips_active_pr_recovery_mutation() -> None:
    def fake_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:
        if args[:2] == ["show", "epic-1"]:
            return [{"id": "epic-1", "labels": ["at:epic"], "status": "in_progress"}]
        if args[:2] == ["list", "--parent"] and args[2] == "epic-1":
            return [
                {
                    "id": "epic-1.1",
                    "status": "closed",
                    "description": "pr_state: draft-pr\n",
                    "labels": [],
                    "type": "task",
                }
            ]
        if args[:2] == ["list", "--parent"] and args[2] == "epic-1.1":
            return []
        return []

    with (
        patch("atelier.beads.run_bd_json", side_effect=fake_json),
        patch("atelier.beads.mark_issue_in_progress") as mark_issue_in_progress,
        patch("atelier.beads.close_issue") as close_issue,
        patch("atelier.beads.clear_agent_hook") as clear_hook,
    ):
        result = beads.close_epic_if_complete(
            "epic-1",
            "agent-1",
            beads_root=Path("/beads"),
            cwd=Path("/repo"),
            dry_run=True,
        )

    assert result is False
    mark_issue_in_progress.assert_not_called()
    close_issue.assert_not_called()
    clear_hook.assert_not_called()


def test_close_epic_if_complete_dry_run_skips_close_mutation() -> None:
    work = lambda i, s="open": {"id": i, "status": s, "labels": [], "type": "task"}
    changesets = {
        "epic-1": [work("epic-1.1", "closed")],
        "epic-1.1": [],
    }
    dry_run_lines: list[str] = []

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
            dry_run=True,
            dry_run_log=dry_run_lines.append,
        )

    assert result is False
    assert dry_run_lines == ["Would close epic epic-1 and clear hook agent-1."]
    close_issue.assert_not_called()
    clear_hook.assert_not_called()


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


def test_close_epic_if_complete_reopens_active_pr_standalone_changeset() -> None:
    def fake_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:
        if args[:2] == ["show", "at-irs"]:
            return [
                {
                    "id": "at-irs",
                    "labels": [],
                    "status": "closed",
                    "description": "pr_state: in-review\n",
                }
            ]
        if args[:2] == ["list", "--parent"]:
            return []
        return []

    with (
        patch("atelier.beads.run_bd_json", side_effect=fake_json),
        patch("atelier.beads.mark_issue_in_progress") as mark_issue_in_progress,
        patch("atelier.beads.close_issue") as close_issue,
        patch("atelier.beads.clear_agent_hook") as clear_hook,
    ):
        result = beads.close_epic_if_complete(
            "at-irs",
            "agent-1",
            beads_root=Path("/beads"),
            cwd=Path("/repo"),
        )

    assert result is False
    mark_issue_in_progress.assert_called_once_with(
        "at-irs",
        beads_root=Path("/beads"),
        cwd=Path("/repo"),
    )
    close_issue.assert_not_called()
    clear_hook.assert_not_called()


def test_close_transition_has_active_pr_lifecycle_treats_pushed_as_active_when_closed() -> None:
    assert (
        beads.close_transition_has_active_pr_lifecycle(
            {"status": "closed", "description": "pr_state: pushed\n"}
        )
        is True
    )


def test_close_transition_has_active_pr_lifecycle_treats_pushed_as_inactive_when_open() -> None:
    assert (
        beads.close_transition_has_active_pr_lifecycle(
            {"status": "in_progress", "description": "pr_state: pushed\n"}
        )
        is False
    )


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


def test_mark_issue_in_progress_runs_update_and_reconciles_reopen() -> None:
    with (
        patch("atelier.beads.run_bd_command") as run_command,
        patch("atelier.beads.reconcile_reopened_issue_exported_github_tickets") as reconcile,
    ):
        beads.mark_issue_in_progress(
            "at-1",
            beads_root=Path("/beads"),
            cwd=Path("/repo"),
        )

    run_command.assert_called_once_with(
        ["update", "at-1", "--status", "in_progress"],
        beads_root=Path("/beads"),
        cwd=Path("/repo"),
    )
    reconcile.assert_called_once_with(
        "at-1",
        beads_root=Path("/beads"),
        cwd=Path("/repo"),
    )


def test_update_changeset_review_updates_description() -> None:
    state = {"description": "scope: demo\n"}
    captured: dict[str, str] = {}

    def fake_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:
        return [{"id": "atelier-99", "description": state["description"]}]

    def fake_update(issue_id: str, description: str, *, beads_root: Path, cwd: Path) -> None:
        captured["id"] = issue_id
        captured["description"] = description
        state["description"] = description

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
    state = {"description": "scope: demo\n"}
    captured: dict[str, str] = {}

    def fake_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:
        return [{"id": "atelier-99", "description": state["description"]}]

    def fake_update(issue_id: str, description: str, *, beads_root: Path, cwd: Path) -> None:
        captured["id"] = issue_id
        captured["description"] = description
        state["description"] = description

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


def test_update_issue_description_fields_retries_after_interleaved_overwrite() -> None:
    state = {"description": "hook_bead: epic-1\npr_state: draft-pr\n"}
    writes = 0

    def fake_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:
        return [{"id": "agent-1", "description": state["description"]}]

    def fake_update(issue_id: str, description: str, *, beads_root: Path, cwd: Path) -> None:
        nonlocal writes
        del issue_id, beads_root, cwd
        writes += 1
        if writes == 1:
            state["description"] = "pr_state: in-review\n"
            return
        state["description"] = description

    with (
        patch("atelier.beads.run_bd_json", side_effect=fake_json),
        patch("atelier.beads._update_issue_description", side_effect=fake_update),
    ):
        beads.update_issue_description_fields(
            "agent-1",
            {"hook_bead": "epic-2"},
            beads_root=Path("/beads"),
            cwd=Path("/repo"),
        )

    assert "hook_bead: epic-2" in state["description"]
    assert "pr_state: in-review" in state["description"]


def test_update_worktree_path_writes_description() -> None:
    state = {"description": "workspace.root_branch: main\n"}
    captured: dict[str, str] = {}

    def fake_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:
        return [{"id": "epic-1", "description": state["description"]}]

    def fake_update(issue_id: str, description: str, *, beads_root: Path, cwd: Path) -> None:
        captured["id"] = issue_id
        captured["description"] = description
        state["description"] = description

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
    state = {"description": "scope: demo\n"}
    issue = {"id": "issue-1", "description": state["description"], "labels": ["ext:github"]}
    captured: dict[str, object] = {"commands": []}

    def fake_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:
        return [{**issue, "description": state["description"]}]

    def fake_command(args: list[str], *, beads_root: Path, cwd: Path) -> None:
        captured["commands"].append(args)

    def fake_update(issue_id: str, description: str, *, beads_root: Path, cwd: Path) -> None:
        captured["description"] = description
        state["description"] = description

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
    state = {
        "description": issue["description"],
        "labels": ["ext:github"],
    }
    gh_calls: list[tuple[str, ...]] = []

    def fake_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:
        del beads_root, cwd
        if args[:2] == ["show", "at-4kv"]:
            return [
                {
                    "id": "at-4kv",
                    "status": "closed",
                    "description": state["description"],
                    "labels": list(state["labels"]),
                }
            ]
        return []

    def fake_command(
        args: list[str],
        *,
        beads_root: Path,
        cwd: Path,
        allow_failure: bool = False,
    ) -> CompletedProcess[str]:
        del beads_root, cwd, allow_failure
        if "--add-label" in args or "--remove-label" in args:
            labels = set(state["labels"])
            if "--add-label" in args:
                labels.add(args[args.index("--add-label") + 1])
            if "--remove-label" in args:
                labels.discard(args[args.index("--remove-label") + 1])
            state["labels"] = sorted(labels)
        return CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    def fake_update(issue_id: str, description: str, *, beads_root: Path, cwd: Path) -> None:
        del issue_id, beads_root, cwd
        state["description"] = description

    def fake_run_with_runner(request: object) -> CompletedProcess[str]:
        argv = tuple(getattr(request, "argv"))
        gh_calls.append(argv)
        if argv[:5] == ("gh", "issue", "close", "175", "--repo"):
            return CompletedProcess(args=list(argv), returncode=0, stdout="", stderr="")
        if argv == ("gh", "api", "repos/acme/widgets/issues/175"):
            payload = {
                "number": 175,
                "url": "https://github.com/acme/widgets/issues/175",
                "state": "CLOSED",
                "stateReason": "completed",
                "updatedAt": "2026-02-25T21:00:00Z",
            }
            return CompletedProcess(
                args=list(argv),
                returncode=0,
                stdout=json.dumps(payload),
                stderr="",
            )
        if argv == ("gh", "api", "repos/acme/widgets/issues/175/parent"):
            return CompletedProcess(
                args=list(argv),
                returncode=0,
                stdout=json.dumps({"number": 200}),
                stderr="",
            )
        raise AssertionError(f"unexpected gh call: {argv}")

    with (
        patch("atelier.beads.run_bd_json", side_effect=fake_json),
        patch("atelier.beads.run_bd_command", side_effect=fake_command),
        patch("atelier.beads._update_issue_description", side_effect=fake_update),
        patch("atelier.beads.exec.run_with_runner", side_effect=fake_run_with_runner),
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
    assert any(call[:4] == ("gh", "issue", "close", "175") for call in gh_calls)
    updated_tickets = beads.parse_external_tickets(state["description"])
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
        patch("atelier.beads.exec.run_with_runner") as gh_runner,
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
    gh_runner.assert_not_called()


def test_reconcile_reopened_issue_exported_github_tickets_reopens_and_updates() -> None:
    ticket_json = json.dumps(
        [
            {
                "provider": "github",
                "id": "179",
                "url": "https://api.github.com/repos/acme/widgets/issues/179",
                "relation": "primary",
                "direction": "exported",
                "sync_mode": "export",
                "state": "closed",
                "parent_id": "174",
            }
        ]
    )
    issue = {
        "id": "at-4kv",
        "status": "in_progress",
        "description": f"external_tickets: {ticket_json}\n",
    }
    state = {
        "description": issue["description"],
        "labels": ["ext:github"],
    }
    gh_calls: list[tuple[str, ...]] = []

    def fake_json(args: list[str], *, beads_root: Path, cwd: Path) -> list[dict[str, object]]:
        del beads_root, cwd
        if args[:2] == ["show", "at-4kv"]:
            return [
                {
                    "id": "at-4kv",
                    "status": "in_progress",
                    "description": state["description"],
                    "labels": list(state["labels"]),
                }
            ]
        return []

    def fake_command(
        args: list[str],
        *,
        beads_root: Path,
        cwd: Path,
        allow_failure: bool = False,
    ) -> CompletedProcess[str]:
        del beads_root, cwd, allow_failure
        if "--add-label" in args or "--remove-label" in args:
            labels = set(state["labels"])
            if "--add-label" in args:
                labels.add(args[args.index("--add-label") + 1])
            if "--remove-label" in args:
                labels.discard(args[args.index("--remove-label") + 1])
            state["labels"] = sorted(labels)
        return CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    def fake_update(issue_id: str, description: str, *, beads_root: Path, cwd: Path) -> None:
        del issue_id, beads_root, cwd
        state["description"] = description

    def fake_run_with_runner(request: object) -> CompletedProcess[str]:
        argv = tuple(getattr(request, "argv"))
        gh_calls.append(argv)
        if argv[:5] == ("gh", "issue", "reopen", "179", "--repo"):
            return CompletedProcess(args=list(argv), returncode=0, stdout="", stderr="")
        if argv == ("gh", "api", "repos/acme/widgets/issues/179"):
            payload = {
                "number": 179,
                "url": "https://github.com/acme/widgets/issues/179",
                "state": "OPEN",
                "stateReason": "reopened",
                "updatedAt": "2026-02-25T22:00:00Z",
            }
            return CompletedProcess(
                args=list(argv),
                returncode=0,
                stdout=json.dumps(payload),
                stderr="",
            )
        if argv == ("gh", "api", "repos/acme/widgets/issues/179/parent"):
            return CompletedProcess(
                args=list(argv),
                returncode=0,
                stdout=json.dumps({"number": 200}),
                stderr="",
            )
        raise AssertionError(f"unexpected gh call: {argv}")

    with (
        patch("atelier.beads.run_bd_json", side_effect=fake_json),
        patch("atelier.beads.run_bd_command", side_effect=fake_command),
        patch("atelier.beads._update_issue_description", side_effect=fake_update),
        patch("atelier.beads.exec.run_with_runner", side_effect=fake_run_with_runner),
    ):
        result = beads.reconcile_reopened_issue_exported_github_tickets(
            "at-4kv",
            beads_root=Path("/beads"),
            cwd=Path("/repo"),
        )

    assert result.stale_exported_github_tickets == 1
    assert result.reconciled_tickets == 1
    assert result.updated is True
    assert result.needs_decision_notes == tuple()
    assert any(call[:4] == ("gh", "issue", "reopen", "179") for call in gh_calls)
    updated_tickets = beads.parse_external_tickets(state["description"])
    assert updated_tickets[0].state == "open"
    assert updated_tickets[0].state_updated_at == "2026-02-25T22:00:00Z"
    assert updated_tickets[0].parent_id == "200"
    assert updated_tickets[0].last_synced_at is not None


def test_reconcile_reopened_issue_exported_github_tickets_adds_note_on_missing_repo() -> None:
    ticket_json = json.dumps(
        [
            {
                "provider": "github",
                "id": "180",
                "relation": "primary",
                "direction": "exported",
                "sync_mode": "export",
                "state": "closed",
            }
        ]
    )
    issue = {
        "id": "at-4kv",
        "status": "open",
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
    ):
        result = beads.reconcile_reopened_issue_exported_github_tickets(
            "at-4kv",
            beads_root=Path("/beads"),
            cwd=Path("/repo"),
        )

    assert result.stale_exported_github_tickets == 1
    assert result.reconciled_tickets == 0
    assert result.updated is False
    assert result.needs_decision_notes
    assert any("missing repo slug" in note for note in result.needs_decision_notes)
    assert any(note.startswith("external_reopen_pending:") for note in notes)


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

from __future__ import annotations

from pathlib import Path

from atelier.bd_invocation import should_use_bd_daemon, with_bd_mode


def test_with_bd_mode_defaults_to_direct_mode() -> None:
    command = with_bd_mode("list", "--json", beads_dir=None, env={})

    assert command[:3] == ["bd", "list", "--json"]
    assert "--no-daemon" in command


def test_with_bd_mode_honors_explicit_daemon_env_override() -> None:
    command = with_bd_mode(
        "show",
        "at-1",
        "--json",
        beads_dir=None,
        env={"ATELIER_BD_DAEMON": "true"},
    )

    assert command == ["bd", "show", "at-1", "--json"]


def test_should_use_bd_daemon_reads_project_config(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    beads_dir = project_dir / ".beads"
    beads_dir.mkdir(parents=True)
    (project_dir / "config.sys.json").write_text('{"beads":{"mode":"daemon"}}', encoding="utf-8")

    assert should_use_bd_daemon(beads_dir=str(beads_dir), env={}) is True


def test_with_bd_mode_never_mutates_daemon_subcommands() -> None:
    command = with_bd_mode("daemon", "status", beads_dir=None, env={})

    assert command == ["bd", "daemon", "status"]

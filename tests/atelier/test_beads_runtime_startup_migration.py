"""Tests for beads_runtime.startup_migration via beads facade with exec patching."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from atelier import beads

from . import bd_mock


def test_detect_startup_beads_state_classifies_healthy_dolt_with_fake_deps(tmp_path: Path) -> None:
    beads_root = tmp_path / ".beads"
    beads_root.mkdir()
    (beads_root / "dolt" / "beads_at" / ".dolt").mkdir(parents=True)
    (beads_root / "beads.db").write_bytes(b"")
    cwd = tmp_path / "repo"
    cwd.mkdir()

    mock = bd_mock.mock_bd_run_with_runner(stats_total=9)

    with patch("atelier.beads.exec.run_with_runner", side_effect=mock):
        state = beads.detect_startup_beads_state(beads_root=beads_root, cwd=cwd)

    assert state.classification == "healthy_dolt"
    assert state.migration_eligible is False
    assert state.dolt_issue_total == 9
    assert state.legacy_issue_total == 9


def test_detect_startup_beads_state_classifies_missing_dolt_with_legacy_fake_deps(
    tmp_path: Path,
) -> None:
    beads_root = tmp_path / ".beads"
    beads_root.mkdir()
    (beads_root / "beads.db").write_bytes(b"")
    cwd = tmp_path / "repo"
    cwd.mkdir()
    # No dolt store: (beads_root / "dolt" / "beads_at" / ".dolt") does not exist

    mock = bd_mock.mock_bd_run_with_runner(
        dolt_stats_fail=True,
        legacy_stats_total=8,
    )

    with patch("atelier.beads.exec.run_with_runner", side_effect=mock):
        state = beads.detect_startup_beads_state(beads_root=beads_root, cwd=cwd)

    assert state.classification == "missing_dolt_with_legacy_sqlite"
    assert state.migration_eligible is True
    assert state.dolt_issue_total is None
    assert state.legacy_issue_total == 8


def test_detect_startup_beads_state_classifies_insufficient_dolt_fake_deps(tmp_path: Path) -> None:
    beads_root = tmp_path / ".beads"
    beads_root.mkdir()
    (beads_root / "dolt" / "beads_at" / ".dolt").mkdir(parents=True)
    (beads_root / "beads.db").write_bytes(b"")
    cwd = tmp_path / "repo"
    cwd.mkdir()

    mock = bd_mock.mock_bd_run_with_runner(
        dolt_stats_total=3,
        legacy_stats_total=11,
    )

    with patch("atelier.beads.exec.run_with_runner", side_effect=mock):
        state = beads.detect_startup_beads_state(beads_root=beads_root, cwd=cwd)

    assert state.classification == "insufficient_dolt_vs_legacy_data"
    assert state.migration_eligible is True
    assert state.dolt_issue_total == 3
    assert state.legacy_issue_total == 11

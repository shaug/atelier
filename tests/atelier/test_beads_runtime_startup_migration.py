from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from atelier.beads_runtime import startup_migration


@dataclass(frozen=True)
class _StartupState:
    classification: str
    migration_eligible: bool
    has_dolt_store: bool
    has_legacy_sqlite: bool
    dolt_issue_total: int | None
    legacy_issue_total: int | None
    reason: str
    backend: str | None
    dolt_count_source: str = "unavailable"
    legacy_count_source: str = "unavailable"
    dolt_detail: str | None = None
    legacy_detail: str | None = None


def _labels() -> startup_migration.StartupClassificationLabels:
    return startup_migration.StartupClassificationLabels(
        healthy="healthy_dolt",
        missing_dolt="missing_dolt_with_legacy_sqlite",
        insufficient_dolt="insufficient_dolt_vs_legacy_data",
        unknown="startup_state_unknown",
    )


def _read_stats_total(
    totals: tuple[int | None, str | None, int | None, str | None],
) -> startup_migration.BdStatsTotalReader:
    def read_stats_total(
        argv: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
    ) -> tuple[int | None, str | None]:
        del cwd, env
        if "--db" in argv:
            return totals[2], totals[3]
        return totals[0], totals[1]

    return read_stats_total


def test_detect_startup_beads_state_classifies_healthy_dolt_with_fake_deps(tmp_path: Path) -> None:
    beads_root = tmp_path / ".beads"
    beads_root.mkdir()
    (beads_root / "beads.db").write_text("", encoding="utf-8")
    read_stats_total = _read_stats_total((9, None, 9, None))

    state = startup_migration.detect_startup_beads_state(
        beads_root=beads_root,
        cwd=tmp_path,
        startup_dolt_store_exists=lambda _root: True,
        configured_beads_backend=lambda _root: None,
        beads_env=lambda _root: {"BEADS_DIR": "/tmp/.beads"},
        read_bd_stats_total=read_stats_total,
        is_embedded_backend_panic=lambda _detail: False,
        labels=_labels(),
        startup_state_factory=_StartupState,
    )

    assert state.classification == "healthy_dolt"
    assert state.migration_eligible is False
    assert state.dolt_issue_total == 9
    assert state.legacy_issue_total == 9


def test_detect_startup_beads_state_classifies_missing_dolt_with_legacy_fake_deps(
    tmp_path: Path,
) -> None:
    beads_root = tmp_path / ".beads"
    beads_root.mkdir()
    (beads_root / "beads.db").write_text("", encoding="utf-8")
    read_stats_total = _read_stats_total((None, "dolt unavailable", 8, None))

    state = startup_migration.detect_startup_beads_state(
        beads_root=beads_root,
        cwd=tmp_path,
        startup_dolt_store_exists=lambda _root: False,
        configured_beads_backend=lambda _root: None,
        beads_env=lambda _root: {"BEADS_DIR": "/tmp/.beads"},
        read_bd_stats_total=read_stats_total,
        is_embedded_backend_panic=lambda _detail: False,
        labels=_labels(),
        startup_state_factory=_StartupState,
    )

    assert state.classification == "missing_dolt_with_legacy_sqlite"
    assert state.migration_eligible is True
    assert state.dolt_issue_total is None
    assert state.legacy_issue_total == 8


def test_detect_startup_beads_state_classifies_insufficient_dolt_fake_deps(tmp_path: Path) -> None:
    beads_root = tmp_path / ".beads"
    beads_root.mkdir()
    (beads_root / "beads.db").write_text("", encoding="utf-8")
    read_stats_total = _read_stats_total((3, None, 11, None))

    state = startup_migration.detect_startup_beads_state(
        beads_root=beads_root,
        cwd=tmp_path,
        startup_dolt_store_exists=lambda _root: True,
        configured_beads_backend=lambda _root: None,
        beads_env=lambda _root: {"BEADS_DIR": "/tmp/.beads"},
        read_bd_stats_total=read_stats_total,
        is_embedded_backend_panic=lambda _detail: False,
        labels=_labels(),
        startup_state_factory=_StartupState,
    )

    assert state.classification == "insufficient_dolt_vs_legacy_data"
    assert state.migration_eligible is True
    assert state.dolt_issue_total == 3
    assert state.legacy_issue_total == 11

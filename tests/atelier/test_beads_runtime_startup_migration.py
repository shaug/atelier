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


def _deps(
    *,
    has_dolt_store: bool,
    backend: str | None,
    totals: tuple[int | None, str | None, int | None, str | None],
) -> startup_migration.StartupMigrationDeps:
    def read_totals(**_kwargs: object) -> tuple[int | None, str | None, int | None, str | None]:
        return totals

    def stabilize_totals(
        **_kwargs: object,
    ) -> tuple[int | None, str | None, int | None, str | None]:
        return totals

    return startup_migration.StartupMigrationDeps(
        startup_dolt_store_exists=lambda _root: has_dolt_store,
        configured_beads_backend=lambda _root: backend,
        beads_env=lambda _root: {"BEADS_DIR": "/tmp/.beads"},
        read_startup_issue_totals=read_totals,
        stabilize_startup_issue_totals=stabilize_totals,
        is_embedded_backend_panic=lambda _detail: False,
    )


def test_detect_startup_beads_state_classifies_healthy_dolt_with_fake_deps(tmp_path: Path) -> None:
    beads_root = tmp_path / ".beads"
    beads_root.mkdir()
    (beads_root / "beads.db").write_text("", encoding="utf-8")

    state = startup_migration.detect_startup_beads_state(
        beads_root=beads_root,
        cwd=tmp_path,
        deps=_deps(
            has_dolt_store=True,
            backend=None,
            totals=(9, None, 9, None),
        ),
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

    state = startup_migration.detect_startup_beads_state(
        beads_root=beads_root,
        cwd=tmp_path,
        deps=_deps(
            has_dolt_store=False,
            backend=None,
            totals=(None, "dolt unavailable", 8, None),
        ),
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

    state = startup_migration.detect_startup_beads_state(
        beads_root=beads_root,
        cwd=tmp_path,
        deps=_deps(
            has_dolt_store=True,
            backend=None,
            totals=(3, None, 11, None),
        ),
        labels=_labels(),
        startup_state_factory=_StartupState,
    )

    assert state.classification == "insufficient_dolt_vs_legacy_data"
    assert state.migration_eligible is True
    assert state.dolt_issue_total == 3
    assert state.legacy_issue_total == 11

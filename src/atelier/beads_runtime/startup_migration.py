"""Startup Beads state classification helpers.

This module hosts startup classification logic extracted from
``atelier.beads`` so the legacy facade can delegate to bounded runtime code.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, TypeVar


class StartupDiagnosticsState(Protocol):
    """Protocol for startup state values that can render diagnostics."""

    def diagnostics(self) -> tuple[str, ...]:
        """Return deterministic diagnostics lines for startup state."""
        ...


StartupStateT = TypeVar("StartupStateT")


@dataclass(frozen=True)
class StartupClassificationLabels:
    """Lifecycle classification labels used by startup state detection.

    Args:
        healthy: Classification when Dolt store and issue totals are healthy.
        missing_dolt: Classification when Dolt is missing but legacy data exists.
        insufficient_dolt: Classification when Dolt counts are behind legacy.
        unknown: Classification when startup signals are inconclusive.
    """

    healthy: str
    missing_dolt: str
    insufficient_dolt: str
    unknown: str


@dataclass(frozen=True)
class StartupMigrationDeps:
    """Dependencies for startup classification.

    Args:
        startup_dolt_store_exists: Probe for Dolt store availability.
        configured_beads_backend: Read configured Beads backend from metadata.
        beads_env: Build env for Beads command probes.
        read_startup_issue_totals: Initial Dolt/legacy issue total probe.
        stabilize_startup_issue_totals: Optional re-sample pass.
        is_embedded_backend_panic: Detect embedded backend panic stderr detail.
    """

    startup_dolt_store_exists: Callable[[Path], bool]
    configured_beads_backend: Callable[[Path], str | None]
    beads_env: Callable[[Path], dict[str, str]]
    read_startup_issue_totals: Callable[..., tuple[int | None, str | None, int | None, str | None]]
    stabilize_startup_issue_totals: Callable[
        ..., tuple[int | None, str | None, int | None, str | None]
    ]
    is_embedded_backend_panic: Callable[[str], bool]


def detect_startup_beads_state(
    *,
    beads_root: Path,
    cwd: Path,
    deps: StartupMigrationDeps,
    labels: StartupClassificationLabels,
    startup_state_factory: Callable[..., StartupStateT],
) -> StartupStateT:
    """Classify startup Beads state without mutating Dolt/SQLite stores.

    Args:
        beads_root: Project Beads directory.
        cwd: Working directory for command execution.
        deps: Runtime dependency bundle.
        labels: Canonical startup classification labels.
        startup_state_factory: Factory for the caller's startup state dataclass.

    Returns:
        Startup state value from ``startup_state_factory``.
    """
    has_legacy_sqlite = (beads_root / "beads.db").is_file()
    has_dolt_store = bool(deps.startup_dolt_store_exists(beads_root))
    configured_backend = deps.configured_beads_backend(beads_root)
    dolt_backend_expected = configured_backend in {None, "dolt"}
    if not beads_root.exists():
        return startup_state_factory(
            classification=labels.unknown,
            migration_eligible=False,
            has_dolt_store=has_dolt_store,
            has_legacy_sqlite=has_legacy_sqlite,
            dolt_issue_total=None,
            legacy_issue_total=None,
            reason="beads_root_missing",
            backend=configured_backend,
        )

    env = deps.beads_env(beads_root)
    dolt_issue_total, dolt_detail, legacy_issue_total, legacy_detail = (
        deps.read_startup_issue_totals(
            beads_root=beads_root,
            has_legacy_sqlite=has_legacy_sqlite,
            cwd=cwd,
            env=env,
        )
    )
    dolt_issue_total, dolt_detail, legacy_issue_total, legacy_detail = (
        deps.stabilize_startup_issue_totals(
            beads_root=beads_root,
            has_dolt_store=has_dolt_store,
            has_legacy_sqlite=has_legacy_sqlite,
            dolt_issue_total=dolt_issue_total,
            dolt_detail=dolt_detail,
            legacy_issue_total=legacy_issue_total,
            legacy_detail=legacy_detail,
            cwd=cwd,
            env=env,
        )
    )

    if dolt_issue_total is None:
        dolt_count_source = "unavailable"
    elif has_dolt_store:
        dolt_count_source = "bd_stats_dolt_store"
    elif dolt_backend_expected:
        dolt_count_source = "bd_stats_without_dolt_store"
    else:
        dolt_count_source = "bd_stats_non_dolt_backend"

    legacy_count_source = "unavailable" if legacy_issue_total is None else "bd_stats_legacy_sqlite"
    legacy_has_data = bool(legacy_issue_total and legacy_issue_total > 0)
    common_state = {
        "has_dolt_store": has_dolt_store,
        "has_legacy_sqlite": has_legacy_sqlite,
        "dolt_issue_total": dolt_issue_total,
        "legacy_issue_total": legacy_issue_total,
        "backend": configured_backend,
        "dolt_count_source": dolt_count_source,
        "legacy_count_source": legacy_count_source,
        "dolt_detail": dolt_detail,
        "legacy_detail": legacy_detail,
    }

    if not has_dolt_store:
        if legacy_has_data and dolt_backend_expected:
            return startup_state_factory(
                classification=labels.missing_dolt,
                migration_eligible=True,
                reason="legacy_sqlite_has_data_while_dolt_is_unavailable",
                **common_state,
            )
        reason = "dolt_store_missing_without_recoverable_legacy_data"
        if configured_backend and configured_backend != "dolt":
            reason = "dolt_store_missing_for_non_dolt_backend"
        return startup_state_factory(
            classification=labels.unknown,
            migration_eligible=False,
            reason=reason,
            **common_state,
        )

    if dolt_issue_total is not None:
        if (
            has_legacy_sqlite
            and legacy_issue_total is not None
            and legacy_issue_total > dolt_issue_total
        ):
            return startup_state_factory(
                classification=labels.insufficient_dolt,
                migration_eligible=True,
                reason="legacy_issue_total_exceeds_dolt_issue_total",
                **common_state,
            )
        return startup_state_factory(
            classification=labels.healthy,
            migration_eligible=False,
            reason="dolt_issue_total_is_healthy",
            **common_state,
        )

    if legacy_has_data and deps.is_embedded_backend_panic(dolt_detail or ""):
        return startup_state_factory(
            classification=labels.missing_dolt,
            migration_eligible=True,
            reason="legacy_sqlite_has_data_while_dolt_is_unavailable",
            **common_state,
        )
    return startup_state_factory(
        classification=labels.unknown,
        migration_eligible=False,
        reason="insufficient_signals_for_classification",
        **common_state,
    )


def format_startup_beads_diagnostics(state: StartupDiagnosticsState) -> str:
    """Render startup diagnostics string from a startup state.

    Args:
        state: Startup state object with diagnostics output.

    Returns:
        Deterministic diagnostic summary string.
    """
    return "Startup Beads state: " + "; ".join(state.diagnostics())

from __future__ import annotations

import importlib.util
from pathlib import Path

import atelier.beads as beads


def _load_script():
    scripts_dir = (
        Path(__file__).resolve().parents[3] / "src/atelier/skills/import-legacy-tickets/scripts"
    )
    path = scripts_dir / "import_legacy_tickets.py"
    spec = importlib.util.spec_from_file_location("test_import_legacy_tickets_script", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _state(
    *,
    classification: str,
    migration_eligible: bool,
    has_dolt_store: bool,
    has_legacy_sqlite: bool,
    dolt_issue_total: int | None,
    legacy_issue_total: int | None,
    reason: str,
) -> beads.StartupBeadsState:
    return beads.StartupBeadsState(
        classification=classification,
        migration_eligible=migration_eligible,
        has_dolt_store=has_dolt_store,
        has_legacy_sqlite=has_legacy_sqlite,
        dolt_issue_total=dolt_issue_total,
        legacy_issue_total=legacy_issue_total,
        reason=reason,
    )


def test_main_runs_prime_and_reports_skipped_status(monkeypatch, capsys, tmp_path: Path) -> None:
    module = _load_script()
    before = _state(
        classification="startup_state_unknown",
        migration_eligible=False,
        has_dolt_store=True,
        has_legacy_sqlite=False,
        dolt_issue_total=6,
        legacy_issue_total=None,
        reason="legacy_sqlite_missing",
    )
    after = before
    state_reads = iter([before, after])
    calls: list[tuple[list[str], Path, Path]] = []

    beads_root = tmp_path / "beads"
    repo_root = tmp_path / "repo"
    beads_root.mkdir()
    repo_root.mkdir()
    monkeypatch.setattr(module, "_resolve_context", lambda **_kwargs: (beads_root, repo_root, None))
    monkeypatch.setattr(
        module.beads,
        "detect_startup_beads_state",
        lambda **_kwargs: next(state_reads),
    )
    monkeypatch.setattr(
        module.beads,
        "run_bd_command",
        lambda args, *, beads_root, cwd: calls.append((args, beads_root, cwd)),
    )
    monkeypatch.setattr(
        module.beads,
        "format_startup_beads_diagnostics",
        lambda state: f"classification={state.classification}",
    )
    monkeypatch.setattr(module.sys, "argv", ["import_legacy_tickets.py"])

    module.main()

    output = capsys.readouterr().out.strip().splitlines()
    assert output[0] == (
        "Beads startup auto-upgrade skipped: no recoverable legacy SQLite startup state detected"
    )
    assert output[1] == "before=classification=startup_state_unknown"
    assert output[2] == "after=classification=startup_state_unknown"
    assert calls == [(["prime"], beads_root, repo_root)]


def test_main_reports_migrated_when_recoverable_state_is_resolved(
    monkeypatch, capsys, tmp_path: Path
) -> None:
    module = _load_script()
    before = _state(
        classification="missing_dolt_with_legacy_sqlite",
        migration_eligible=True,
        has_dolt_store=False,
        has_legacy_sqlite=True,
        dolt_issue_total=None,
        legacy_issue_total=4,
        reason="legacy_sqlite_has_data_while_dolt_is_unavailable",
    )
    after = _state(
        classification="healthy_dolt",
        migration_eligible=False,
        has_dolt_store=True,
        has_legacy_sqlite=True,
        dolt_issue_total=4,
        legacy_issue_total=4,
        reason="dolt_issue_total_is_healthy",
    )
    state_reads = iter([before, after])

    beads_root = tmp_path / "beads"
    repo_root = tmp_path / "repo"
    beads_root.mkdir()
    repo_root.mkdir()
    monkeypatch.setattr(module, "_resolve_context", lambda **_kwargs: (beads_root, repo_root, None))
    monkeypatch.setattr(
        module.beads,
        "detect_startup_beads_state",
        lambda **_kwargs: next(state_reads),
    )
    monkeypatch.setattr(module.beads, "run_bd_command", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        module.beads,
        "format_startup_beads_diagnostics",
        lambda state: f"classification={state.classification}",
    )
    monkeypatch.setattr(module.sys, "argv", ["import_legacy_tickets.py"])

    module.main()

    output = capsys.readouterr().out.strip().splitlines()
    assert output[0] == (
        "Beads startup auto-upgrade migrated: legacy SQLite data exists but Dolt backend is missing"
    )


def test_main_reports_blocked_when_recoverable_state_remains_unresolved(
    monkeypatch, capsys, tmp_path: Path
) -> None:
    module = _load_script()
    before = _state(
        classification="missing_dolt_with_legacy_sqlite",
        migration_eligible=True,
        has_dolt_store=False,
        has_legacy_sqlite=True,
        dolt_issue_total=3,
        legacy_issue_total=3,
        reason="legacy_sqlite_has_data_while_dolt_is_unavailable",
    )
    after = before
    state_reads = iter([before, after])

    beads_root = tmp_path / "beads"
    repo_root = tmp_path / "repo"
    beads_root.mkdir()
    repo_root.mkdir()
    monkeypatch.setattr(module, "_resolve_context", lambda **_kwargs: (beads_root, repo_root, None))
    monkeypatch.setattr(
        module.beads,
        "detect_startup_beads_state",
        lambda **_kwargs: next(state_reads),
    )
    monkeypatch.setattr(module.beads, "run_bd_command", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        module.beads,
        "format_startup_beads_diagnostics",
        lambda state: f"classification={state.classification}",
    )
    monkeypatch.setattr(module.sys, "argv", ["import_legacy_tickets.py"])

    module.main()

    output = capsys.readouterr().out.strip().splitlines()
    assert output[0] == (
        "Beads startup auto-upgrade blocked: legacy migration remained unresolved after startup prime"
    )


def test_main_emits_override_warning(monkeypatch, capsys, tmp_path: Path) -> None:
    module = _load_script()
    beads_root = tmp_path / "override-beads"
    repo_root = tmp_path / "repo"
    beads_root.mkdir()
    repo_root.mkdir()
    state = _state(
        classification="startup_state_unknown",
        migration_eligible=False,
        has_dolt_store=True,
        has_legacy_sqlite=False,
        dolt_issue_total=1,
        legacy_issue_total=None,
        reason="legacy_sqlite_missing",
    )
    state_reads = iter([state, state])

    monkeypatch.setattr(
        module,
        "_resolve_context",
        lambda **_kwargs: (beads_root, repo_root, "warning: override mismatch"),
    )
    monkeypatch.setattr(
        module.beads,
        "detect_startup_beads_state",
        lambda **_kwargs: next(state_reads),
    )
    monkeypatch.setattr(module.beads, "run_bd_command", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        module.beads,
        "format_startup_beads_diagnostics",
        lambda _state: "classification=startup_state_unknown",
    )
    monkeypatch.setattr(module.sys, "argv", ["import_legacy_tickets.py"])

    module.main()

    captured = capsys.readouterr()
    assert "warning: override mismatch" in captured.err

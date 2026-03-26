"""Implementation for targeted Beads event-history overflow repair commands."""

from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
from pathlib import Path

from .. import beads, config
from ..io import die, say
from .resolve import resolve_current_project_with_repo_root

_FORMATS = {"table", "json"}


def _backup_file_timestamp(now: dt.datetime | None = None) -> str:
    current = now or dt.datetime.now(dt.timezone.utc)
    return current.strftime("%Y%m%dT%H%M%S%fZ")


def _sqlite_backup_path(*, beads_root: Path, issue_id: str) -> Path:
    filename = f"{issue_id}-event-history-overflow-{_backup_file_timestamp()}.sqlite3"
    return beads_root / "repair-backups" / filename


def _backup_sqlite_store(*, beads_root: Path, issue_id: str) -> Path:
    """Create a verified SQLite backup before in-place overflow repair.

    Args:
        beads_root: Path to the project-scoped Beads store.
        issue_id: Issue identifier included in the backup filename.

    Returns:
        The path to the created SQLite backup.

    Raises:
        RuntimeError: If the source database is missing or the backup cannot be
            created atomically.
    """
    source_path = beads_root / "beads.db"
    if not source_path.exists():
        raise RuntimeError(f"beads database not found for backup: {source_path}")

    backup_path = _sqlite_backup_path(beads_root=beads_root, issue_id=issue_id)
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = backup_path.with_suffix(f"{backup_path.suffix}.tmp")

    source_connection: sqlite3.Connection | None = None
    backup_connection: sqlite3.Connection | None = None
    try:
        source_connection = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
        backup_connection = sqlite3.connect(temp_path)
        source_connection.backup(backup_connection)
        backup_connection.commit()
    except sqlite3.Error as exc:
        raise RuntimeError(f"failed to create SQLite Beads backup: {exc}") from exc
    finally:
        if backup_connection is not None:
            backup_connection.close()
        if source_connection is not None:
            source_connection.close()

    try:
        os.replace(temp_path, backup_path)
    except OSError as exc:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        raise RuntimeError(f"failed to finalize SQLite Beads backup: {exc}") from exc
    return backup_path


def repair_event_history_overflow(args: object) -> None:
    """Repair a Beads issue whose event history overflowed and blocked writes."""
    format_value = str(getattr(args, "format", "table") or "table").lower()
    if format_value not in _FORMATS:
        die(f"unsupported format: {format_value}")

    issue_id = str(getattr(args, "issue_id", "") or "").strip()
    if not issue_id:
        die("issue id is required")

    project_root, project_config, _enlistment, repo_root = resolve_current_project_with_repo_root()
    project_data_dir = config.resolve_project_data_dir(project_root, project_config)
    beads_root = config.resolve_beads_root(project_data_dir, repo_root)

    try:
        beads.run_bd_command(["prime"], beads_root=beads_root, cwd=repo_root)
        backend = beads.configured_beads_backend(beads_root) or "sqlite"
        backup_path: Path | None = None
        if backend == "sqlite":
            backup_path = _backup_sqlite_store(beads_root=beads_root, issue_id=issue_id)
        result = beads.repair_issue_event_history_overflow(
            issue_id,
            beads_root=beads_root,
            cwd=repo_root,
        )
    except (RuntimeError, ValueError) as exc:
        die(str(exc))

    payload = {
        "backend": backend,
        "backup_path": str(backup_path) if backup_path is not None else None,
        "issue_id": issue_id,
        "recovery_guidance": beads.event_history_overflow_recovery_guidance(
            issue_id=issue_id,
            backend=backend,
        ),
        "repaired": result.repaired,
        "retained_notes_chars": result.retained_notes_chars,
        "snapshot_bytes_after": result.snapshot_bytes_after,
        "snapshot_bytes_before": result.snapshot_bytes_before,
        "verified_mutable": result.verified_mutable,
    }
    if format_value == "json":
        say(json.dumps(payload, indent=2, sort_keys=True))
        return

    if result.repaired:
        say(f"Done: repaired overflowed issue {issue_id} and verified mutability.")
    else:
        say(f"Done: issue {issue_id} is already mutable; no repair was needed.")
    say(f"-> backend: {backend}")
    if backup_path is not None:
        say(f"-> sqlite backup: {backup_path}")
    say(f"-> snapshot bytes: {result.snapshot_bytes_before} -> {result.snapshot_bytes_after}")
    say(f"-> retained recent notes chars: {result.retained_notes_chars}")
    say(
        "-> recovery guidance: "
        f"{beads.event_history_overflow_recovery_guidance(issue_id=issue_id, backend=backend)}"
    )

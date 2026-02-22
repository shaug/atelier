import datetime as dt
import subprocess
from pathlib import Path

import atelier.planner_sync as planner_sync


def _context(
    tmp_path: Path, *, agent_id: str, worktree_name: str
) -> planner_sync.PlannerSyncContext:
    worktree_path = tmp_path / "worktrees" / worktree_name
    worktree_path.mkdir(parents=True, exist_ok=True)
    return planner_sync.PlannerSyncContext(
        agent_id=agent_id,
        agent_bead_id=f"{agent_id}-bead",
        project_data_dir=tmp_path,
        repo_root=tmp_path,
        beads_root=tmp_path / ".beads",
        worktree_path=worktree_path,
        planner_branch="main-planner",
        default_branch="main",
        git_path="git",
    )


def _metadata_patches(monkeypatch, *, initial: dict[str, str | None]):
    metadata = dict(initial)
    updates: list[dict[str, str | None]] = []

    def fake_issue_fields(_issue_id: str, *, beads_root: Path, cwd: Path) -> dict[str, str]:
        _ = beads_root, cwd
        result: dict[str, str] = {}
        for key, value in metadata.items():
            if value is None:
                continue
            result[key] = value
        return result

    def fake_update_fields(
        _issue_id: str,
        fields: dict[str, str | None],
        *,
        beads_root: Path,
        cwd: Path,
    ) -> dict[str, object]:
        _ = beads_root, cwd
        updates.append(dict(fields))
        for key, value in fields.items():
            metadata[key] = value if value is not None else "null"
        return {}

    monkeypatch.setattr(
        "atelier.planner_sync.beads.issue_description_fields",
        fake_issue_fields,
    )
    monkeypatch.setattr(
        "atelier.planner_sync.beads.update_issue_description_fields",
        fake_update_fields,
    )
    return metadata, updates


def _ok_result() -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=["git"], returncode=0, stdout="", stderr="")


def test_startup_sync_updates_required_metadata(monkeypatch, tmp_path: Path) -> None:
    _metadata, updates = _metadata_patches(monkeypatch, initial={})
    context = _context(tmp_path, agent_id="planner-a", worktree_name="planner-a")
    service = planner_sync.PlannerSyncService(
        context,
        settings=planner_sync.PlannerSyncSettings(interval_seconds=10),
    )

    commands: list[list[str]] = []

    def fake_run_git(args: list[str]):
        commands.append(list(args))
        return _ok_result()

    monkeypatch.setattr(service, "_run_git", fake_run_git)
    monkeypatch.setattr(service, "_resolve_sync_ref", lambda: "origin/main")
    monkeypatch.setattr(service, "_git_rev_parse", lambda _ref: "abc123")

    outcome = service.sync_startup()

    assert outcome.attempted is True
    assert outcome.result == planner_sync.SYNC_OK
    assert updates
    final = updates[-1]
    assert final.get(planner_sync.FIELD_LAST_RESULT) == planner_sync.SYNC_OK
    assert final.get(planner_sync.FIELD_LAST_SYNCED_SHA) == "abc123"
    assert final.get(planner_sync.FIELD_DEFAULT_BRANCH) == "main"
    assert final.get(planner_sync.FIELD_LAST_ATTEMPT_AT)
    assert final.get(planner_sync.FIELD_LAST_SYNCED_AT)
    assert ["fetch", "origin", "main"] in commands
    assert ["checkout", "main-planner"] in commands
    assert ["reset", "--hard", "origin/main"] in commands


def test_periodic_sync_waits_for_interval_then_attempts(monkeypatch, tmp_path: Path) -> None:
    now = dt.datetime(2026, 2, 21, 12, 0, 0, tzinfo=dt.timezone.utc)
    _metadata, updates = _metadata_patches(
        monkeypatch,
        initial={
            planner_sync.FIELD_LAST_ATTEMPT_AT: "2026-02-21T12:00:00Z",
            planner_sync.FIELD_CONSECUTIVE_FAILURES: "0",
        },
    )
    context = _context(tmp_path, agent_id="planner-b", worktree_name="planner-b")
    service = planner_sync.PlannerSyncService(
        context,
        settings=planner_sync.PlannerSyncSettings(interval_seconds=10),
    )
    monkeypatch.setattr(service, "_acquire_lock", lambda _now: None)

    monkeypatch.setattr("atelier.planner_sync._utc_now", lambda: now + dt.timedelta(seconds=5))
    skipped = service.sync_periodic()
    assert skipped.attempted is False
    assert updates == []

    monkeypatch.setattr("atelier.planner_sync._utc_now", lambda: now + dt.timedelta(seconds=11))
    attempted = service.sync_periodic()
    assert attempted.attempted is True
    assert attempted.result == planner_sync.SYNC_LOCK_CONTENDED
    assert updates[-1].get(planner_sync.FIELD_LAST_RESULT) == planner_sync.SYNC_LOCK_CONTENDED


def test_dirty_worktree_records_blocked_and_warns_after_threshold(
    monkeypatch, tmp_path: Path
) -> None:
    _metadata, updates = _metadata_patches(
        monkeypatch,
        initial={
            planner_sync.FIELD_DIRTY_SINCE_AT: "2026-02-21T10:00:00Z",
            planner_sync.FIELD_LAST_ATTEMPT_AT: "2026-02-21T10:05:00Z",
        },
    )
    messages: list[str] = []
    context = _context(tmp_path, agent_id="planner-c", worktree_name="planner-c")
    service = planner_sync.PlannerSyncService(
        context,
        settings=planner_sync.PlannerSyncSettings(
            interval_seconds=10,
            event_debounce_seconds=0,
            dirty_escalation_seconds=900,
        ),
        emit=messages.append,
    )
    monkeypatch.setattr(
        "atelier.planner_sync._utc_now",
        lambda: dt.datetime(2026, 2, 21, 10, 16, 0, tzinfo=dt.timezone.utc),
    )
    monkeypatch.setattr(service, "_git_status_porcelain", lambda: [" M notes.md"])

    outcome = service.sync_event(trigger="hook:pre-compact")

    assert outcome.attempted is True
    assert outcome.result == planner_sync.SYNC_BLOCKED_DIRTY
    assert updates
    final = updates[-1]
    assert final.get(planner_sync.FIELD_LAST_RESULT) == planner_sync.SYNC_BLOCKED_DIRTY
    assert final.get(planner_sync.FIELD_DIRTY_SINCE_AT) == "2026-02-21T10:00:00Z"
    assert final.get(planner_sync.FIELD_LAST_DIRTY_WARNING_AT)
    assert any("15+ minutes" in message for message in messages)


def test_lock_path_isolated_per_agent_and_worktree(tmp_path: Path) -> None:
    service_a = planner_sync.PlannerSyncService(
        _context(tmp_path, agent_id="planner-a", worktree_name="planner-a")
    )
    service_b = planner_sync.PlannerSyncService(
        _context(tmp_path, agent_id="planner-b", worktree_name="planner-b")
    )

    assert service_a.lock_path != service_b.lock_path

"""Planner runtime sync helpers for per-agent worktree freshness."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from . import beads, exec, git
from .agent_home import parse_agent_identity

PlannerSyncResult = Literal[
    "ok",
    "fetch_failed",
    "blocked_dirty",
    "ref_missing",
    "lock_contended",
]

SYNC_OK: PlannerSyncResult = "ok"
SYNC_FETCH_FAILED: PlannerSyncResult = "fetch_failed"
SYNC_BLOCKED_DIRTY: PlannerSyncResult = "blocked_dirty"
SYNC_REF_MISSING: PlannerSyncResult = "ref_missing"
SYNC_LOCK_CONTENDED: PlannerSyncResult = "lock_contended"

ENV_SYNC_ENABLED = "ATELIER_PLANNER_SYNC_ENABLED"
ENV_AGENT_BEAD_ID = "ATELIER_AGENT_BEAD_ID"
ENV_WORKTREE = "ATELIER_PLANNER_WORKTREE"
ENV_BRANCH = "ATELIER_PLANNER_BRANCH"
ENV_DEFAULT_BRANCH = "ATELIER_DEFAULT_BRANCH"

DEFAULT_INTERVAL_SECONDS = 600
MIN_INTERVAL_SECONDS = 300
DEFAULT_EVENT_DEBOUNCE_SECONDS = 60
DEFAULT_LOCK_TTL_SECONDS = 120
DEFAULT_DIRTY_ESCALATION_SECONDS = 900
DEFAULT_POLL_SECONDS = 30

FIELD_LAST_SYNCED_SHA = "planner_sync.last_synced_sha"
FIELD_LAST_SYNCED_AT = "planner_sync.last_synced_at"
FIELD_LAST_ATTEMPT_AT = "planner_sync.last_attempt_at"
FIELD_LAST_RESULT = "planner_sync.last_result"
FIELD_DEFAULT_BRANCH = "planner_sync.default_branch"
FIELD_CONSECUTIVE_FAILURES = "planner_sync.consecutive_failures"
FIELD_DIRTY_SINCE_AT = "planner_sync.dirty_since_at"
FIELD_LAST_DIRTY_WARNING_AT = "planner_sync.last_dirty_warning_at"
FIELD_LAST_EVENT_ATTEMPT_AT = "planner_sync.last_event_attempt_at"


def _utc_now() -> dt.datetime:
    return dt.datetime.now(tz=dt.timezone.utc).replace(microsecond=0)


def _serialize_timestamp(value: dt.datetime | None) -> str | None:
    if value is None:
        return None
    normalized = value.astimezone(dt.timezone.utc).replace(microsecond=0)
    return normalized.isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = f"{raw[:-1]}+00:00"
    try:
        parsed = dt.datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def _parse_int(value: str | None, *, default: int) -> int:
    if value is None:
        return default
    raw = value.strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _failure_backoff_seconds(consecutive_failures: int) -> int:
    if consecutive_failures <= 1:
        return 0
    if consecutive_failures == 2:
        return 120
    return 300


@dataclass(frozen=True)
class PlannerSyncSettings:
    """Runtime settings for planner worktree sync behavior."""

    interval_seconds: int = DEFAULT_INTERVAL_SECONDS
    event_debounce_seconds: int = DEFAULT_EVENT_DEBOUNCE_SECONDS
    lock_ttl_seconds: int = DEFAULT_LOCK_TTL_SECONDS
    dirty_escalation_seconds: int = DEFAULT_DIRTY_ESCALATION_SECONDS
    poll_seconds: int = DEFAULT_POLL_SECONDS

    @classmethod
    def from_environment(cls) -> PlannerSyncSettings:
        """Resolve planner sync settings from environment variables."""
        raw_interval = _parse_int(
            os.environ.get("ATELIER_PLANNER_SYNC_INTERVAL_SECONDS"),
            default=DEFAULT_INTERVAL_SECONDS,
        )
        interval = max(raw_interval, MIN_INTERVAL_SECONDS)
        raw_poll = _parse_int(
            os.environ.get("ATELIER_PLANNER_SYNC_POLL_SECONDS"),
            default=DEFAULT_POLL_SECONDS,
        )
        poll_seconds = max(5, raw_poll)
        return cls(interval_seconds=interval, poll_seconds=poll_seconds)


@dataclass(frozen=True)
class PlannerSyncContext:
    """Identity and path context for per-agent planner sync."""

    agent_id: str
    agent_bead_id: str
    project_data_dir: Path
    repo_root: Path
    beads_root: Path
    worktree_path: Path
    planner_branch: str
    default_branch: str
    git_path: str | None


@dataclass(frozen=True)
class PlannerSyncOutcome:
    """Result payload for a planner sync checkpoint."""

    attempted: bool
    result: PlannerSyncResult | None
    synced_sha: str | None = None


@dataclass
class _PlannerSyncState:
    last_synced_sha: str | None = None
    last_synced_at: dt.datetime | None = None
    last_attempt_at: dt.datetime | None = None
    last_result: str | None = None
    default_branch: str | None = None
    consecutive_failures: int = 0
    dirty_since_at: dt.datetime | None = None
    last_dirty_warning_at: dt.datetime | None = None
    last_event_attempt_at: dt.datetime | None = None


class PlannerSyncService:
    """Coordinate planner worktree sync checkpoints for one agent/worktree."""

    def __init__(
        self,
        context: PlannerSyncContext,
        *,
        settings: PlannerSyncSettings | None = None,
        emit: Callable[[str], None] | None = None,
    ) -> None:
        self.context = context
        self.settings = settings or PlannerSyncSettings.from_environment()
        self._emit = emit

    @property
    def lock_path(self) -> Path:
        """Return the filesystem lock path for this planner agent/worktree."""
        lock_root = self.context.project_data_dir / "locks" / "planner-sync"
        digest = hashlib.sha1(
            f"{self.context.agent_id}|{self.context.worktree_path.resolve()}".encode("utf-8")
        ).hexdigest()
        return lock_root / f"{digest}.lock"

    def sync_startup(self) -> PlannerSyncOutcome:
        """Run a mandatory startup sync checkpoint."""
        return self._sync(trigger="startup", force=True, event_driven=False)

    def sync_periodic(self) -> PlannerSyncOutcome:
        """Run a periodic sync checkpoint when due."""
        return self._sync(trigger="periodic", force=False, event_driven=False)

    def sync_event(self, *, trigger: str) -> PlannerSyncOutcome:
        """Run a debounced event-driven sync checkpoint."""
        return self._sync(trigger=trigger, force=False, event_driven=True)

    def _sync(self, *, trigger: str, force: bool, event_driven: bool) -> PlannerSyncOutcome:
        state = self._load_state()
        now = _utc_now()
        if not force and self._skip_checkpoint(now, state, event_driven=event_driven):
            return PlannerSyncOutcome(attempted=False, result=None)

        attempt_updates: dict[str, str | None] = {
            FIELD_LAST_ATTEMPT_AT: _serialize_timestamp(now),
            FIELD_DEFAULT_BRANCH: self.context.default_branch,
        }
        if event_driven:
            attempt_updates[FIELD_LAST_EVENT_ATTEMPT_AT] = _serialize_timestamp(now)

        lock_path = self._acquire_lock(now)
        if lock_path is None:
            self._persist_updates(
                {
                    **attempt_updates,
                    FIELD_LAST_RESULT: SYNC_LOCK_CONTENDED,
                }
            )
            return PlannerSyncOutcome(attempted=True, result=SYNC_LOCK_CONTENDED)

        try:
            self._refresh_lock(lock_path, now)
            dirty = self._git_status_porcelain()
            if dirty:
                return self._record_dirty(attempt_updates, state, now)

            fetch = self._run_git(["fetch", "origin", self.context.default_branch])
            self._refresh_lock(lock_path, now)
            if fetch is None or fetch.returncode != 0:
                return self._record_failure(attempt_updates, state, SYNC_FETCH_FAILED)

            sync_ref = self._resolve_sync_ref()
            if sync_ref is None:
                return self._record_failure(attempt_updates, state, SYNC_REF_MISSING)

            checkout = self._run_git(["checkout", self.context.planner_branch])
            self._refresh_lock(lock_path, now)
            if checkout is None or checkout.returncode != 0:
                return self._record_failure(attempt_updates, state, SYNC_FETCH_FAILED)

            reset = self._run_git(["reset", "--hard", sync_ref])
            self._refresh_lock(lock_path, now)
            if reset is None or reset.returncode != 0:
                return self._record_failure(attempt_updates, state, SYNC_FETCH_FAILED)

            synced_sha = self._git_rev_parse("HEAD")
            success_updates = {
                **attempt_updates,
                FIELD_LAST_RESULT: SYNC_OK,
                FIELD_LAST_SYNCED_SHA: synced_sha,
                FIELD_LAST_SYNCED_AT: _serialize_timestamp(now),
                FIELD_CONSECUTIVE_FAILURES: "0",
                FIELD_DIRTY_SINCE_AT: None,
                FIELD_LAST_DIRTY_WARNING_AT: None,
            }
            self._persist_updates(success_updates)
            return PlannerSyncOutcome(attempted=True, result=SYNC_OK, synced_sha=synced_sha)
        finally:
            self._release_lock(lock_path)

    def _record_dirty(
        self,
        attempt_updates: dict[str, str | None],
        state: _PlannerSyncState,
        now: dt.datetime,
    ) -> PlannerSyncOutcome:
        dirty_since = state.dirty_since_at or now
        updates = {
            **attempt_updates,
            FIELD_LAST_RESULT: SYNC_BLOCKED_DIRTY,
            FIELD_CONSECUTIVE_FAILURES: "0",
            FIELD_DIRTY_SINCE_AT: _serialize_timestamp(dirty_since),
        }
        elapsed = (now - dirty_since).total_seconds()
        should_warn = elapsed >= self.settings.dirty_escalation_seconds
        if should_warn:
            last_warn = state.last_dirty_warning_at
            if (
                last_warn is None
                or (now - last_warn).total_seconds() >= self.settings.dirty_escalation_seconds
            ):
                self._warn_dirty()
                updates[FIELD_LAST_DIRTY_WARNING_AT] = _serialize_timestamp(now)
        self._persist_updates(updates)
        return PlannerSyncOutcome(attempted=True, result=SYNC_BLOCKED_DIRTY)

    def _record_failure(
        self,
        attempt_updates: dict[str, str | None],
        state: _PlannerSyncState,
        result: PlannerSyncResult,
    ) -> PlannerSyncOutcome:
        failures = state.consecutive_failures + 1
        self._persist_updates(
            {
                **attempt_updates,
                FIELD_LAST_RESULT: result,
                FIELD_CONSECUTIVE_FAILURES: str(failures),
                FIELD_DIRTY_SINCE_AT: None,
                FIELD_LAST_DIRTY_WARNING_AT: None,
            }
        )
        if failures == 3:
            self._emit_warning(
                "Planner sync has failed 3 consecutive times; continuing with backoff."
            )
        return PlannerSyncOutcome(attempted=True, result=result)

    def _skip_checkpoint(
        self, now: dt.datetime, state: _PlannerSyncState, *, event_driven: bool
    ) -> bool:
        if state.last_attempt_at is not None:
            backoff = _failure_backoff_seconds(state.consecutive_failures)
            if backoff > 0:
                earliest = state.last_attempt_at + dt.timedelta(seconds=backoff)
                if now < earliest:
                    return True
        if event_driven:
            if state.last_event_attempt_at is None:
                return False
            earliest = state.last_event_attempt_at + dt.timedelta(
                seconds=self.settings.event_debounce_seconds
            )
            return now < earliest
        if state.last_attempt_at is None:
            return False
        earliest = state.last_attempt_at + dt.timedelta(seconds=self.settings.interval_seconds)
        return now < earliest

    def _load_state(self) -> _PlannerSyncState:
        try:
            fields = beads.issue_description_fields(
                self.context.agent_bead_id,
                beads_root=self.context.beads_root,
                cwd=self.context.repo_root,
            )
        except SystemExit:
            self._emit_warning("Unable to read planner sync metadata from Beads.")
            return _PlannerSyncState()
        return _PlannerSyncState(
            last_synced_sha=self._clean(fields.get(FIELD_LAST_SYNCED_SHA)),
            last_synced_at=_parse_timestamp(fields.get(FIELD_LAST_SYNCED_AT)),
            last_attempt_at=_parse_timestamp(fields.get(FIELD_LAST_ATTEMPT_AT)),
            last_result=self._clean(fields.get(FIELD_LAST_RESULT)),
            default_branch=self._clean(fields.get(FIELD_DEFAULT_BRANCH)),
            consecutive_failures=max(
                _parse_int(fields.get(FIELD_CONSECUTIVE_FAILURES), default=0),
                0,
            ),
            dirty_since_at=_parse_timestamp(fields.get(FIELD_DIRTY_SINCE_AT)),
            last_dirty_warning_at=_parse_timestamp(fields.get(FIELD_LAST_DIRTY_WARNING_AT)),
            last_event_attempt_at=_parse_timestamp(fields.get(FIELD_LAST_EVENT_ATTEMPT_AT)),
        )

    def _persist_updates(self, fields: dict[str, str | None]) -> None:
        try:
            beads.update_issue_description_fields(
                self.context.agent_bead_id,
                fields,
                beads_root=self.context.beads_root,
                cwd=self.context.repo_root,
            )
        except SystemExit:
            self._emit_warning("Unable to persist planner sync metadata to Beads.")

    def _clean(self, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned or cleaned.lower() == "null":
            return None
        return cleaned

    def _resolve_sync_ref(self) -> str | None:
        remote_ref = f"refs/remotes/origin/{self.context.default_branch}"
        if self._git_ref_exists(remote_ref):
            return f"origin/{self.context.default_branch}"
        local_ref = f"refs/heads/{self.context.default_branch}"
        if self._git_ref_exists(local_ref):
            return self.context.default_branch
        return None

    def _git_ref_exists(self, ref: str) -> bool:
        result = self._run_git(["show-ref", "--verify", "--quiet", ref])
        if result is None:
            return False
        return result.returncode == 0

    def _git_rev_parse(self, ref: str) -> str | None:
        result = self._run_git(["rev-parse", ref])
        if result is None or result.returncode != 0:
            return None
        return (result.stdout or "").strip() or None

    def _git_status_porcelain(self) -> list[str]:
        result = self._run_git(["status", "--porcelain"])
        if result is None or result.returncode != 0:
            return []
        return [line for line in (result.stdout or "").splitlines() if line.strip()]

    def _run_git(self, args: list[str]):
        return exec.try_run_command(
            git.git_command(
                ["-C", str(self.context.worktree_path), *args],
                git_path=self.context.git_path,
            )
        )

    def _acquire_lock(self, now: dt.datetime) -> Path | None:
        lock_path = self.lock_path
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            except FileExistsError:
                if not self._lock_is_stale(lock_path, now):
                    return None
                try:
                    lock_path.unlink()
                except OSError:
                    return None
                continue
            payload = {
                "agent_id": self.context.agent_id,
                "worktree": str(self.context.worktree_path),
                "heartbeat_at": _serialize_timestamp(now),
            }
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, separators=(",", ":"))
            return lock_path
        return None

    def _lock_is_stale(self, lock_path: Path, now: dt.datetime) -> bool:
        try:
            raw = lock_path.read_text(encoding="utf-8")
        except OSError:
            return False
        heartbeat_at: dt.datetime | None = None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {}
        if isinstance(payload, dict):
            value = payload.get("heartbeat_at")
            if isinstance(value, str):
                heartbeat_at = _parse_timestamp(value)
        if heartbeat_at is None:
            try:
                modified_at = dt.datetime.fromtimestamp(
                    lock_path.stat().st_mtime,
                    tz=dt.timezone.utc,
                )
            except OSError:
                return False
            heartbeat_at = modified_at
        return (now - heartbeat_at).total_seconds() >= self.settings.lock_ttl_seconds

    def _refresh_lock(self, lock_path: Path, now: dt.datetime) -> None:
        payload = {
            "agent_id": self.context.agent_id,
            "worktree": str(self.context.worktree_path),
            "heartbeat_at": _serialize_timestamp(now),
        }
        try:
            lock_path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
        except OSError:
            return

    def _release_lock(self, lock_path: Path) -> None:
        try:
            lock_path.unlink()
        except OSError:
            return

    def _warn_dirty(self) -> None:
        self._emit_warning(
            "Planner worktree has remained dirty for 15+ minutes; sync is blocked. "
            f"Clean local changes in {self.context.worktree_path} to resume sync."
        )

    def _emit_warning(self, message: str) -> None:
        if self._emit is not None:
            self._emit(f"Warning: {message}")


class PlannerSyncMonitor:
    """Background monitor that runs periodic planner sync checkpoints."""

    def __init__(self, service: PlannerSyncService) -> None:
        self._service = service
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the periodic monitor thread."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="atelier-planner-sync",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the periodic monitor thread."""
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=2.0)
        self._thread = None

    def _run(self) -> None:
        poll_seconds = max(5, self._service.settings.poll_seconds)
        while not self._stop.wait(poll_seconds):
            self._service.sync_periodic()


def runtime_environment(
    *,
    agent_bead_id: str,
    worktree_path: Path,
    planner_branch: str,
    default_branch: str,
) -> dict[str, str]:
    """Build planner sync environment variables for spawned agent runtimes."""
    return {
        ENV_SYNC_ENABLED: "1",
        ENV_AGENT_BEAD_ID: agent_bead_id,
        ENV_WORKTREE: str(worktree_path),
        ENV_BRANCH: planner_branch,
        ENV_DEFAULT_BRANCH: default_branch,
    }


def maybe_sync_from_hook(
    *,
    event: str,
    project_data_dir: Path,
    repo_root: Path,
    beads_root: Path,
    git_path: str | None,
    emit: Callable[[str], None] | None = None,
) -> None:
    """Run a planner event checkpoint from runtime hooks when context exists."""
    if os.environ.get(ENV_SYNC_ENABLED, "").strip() not in {"1", "true", "yes", "on"}:
        return
    agent_id = os.environ.get("ATELIER_AGENT_ID", "").strip()
    role, _name, _session = parse_agent_identity(agent_id)
    if role != "planner":
        return
    worktree_raw = os.environ.get(ENV_WORKTREE, "").strip()
    planner_branch = os.environ.get(ENV_BRANCH, "").strip()
    default_branch = os.environ.get(ENV_DEFAULT_BRANCH, "").strip()
    if not worktree_raw or not planner_branch or not default_branch:
        return
    agent_bead_id = os.environ.get(ENV_AGENT_BEAD_ID, "").strip()
    if not agent_bead_id and agent_id:
        agent_issue = beads.ensure_agent_bead(
            agent_id,
            beads_root=beads_root,
            cwd=repo_root,
            role="planner",
        )
        value = agent_issue.get("id")
        if isinstance(value, str):
            agent_bead_id = value.strip()
    if not agent_bead_id:
        return
    context = PlannerSyncContext(
        agent_id=agent_id,
        agent_bead_id=agent_bead_id,
        project_data_dir=project_data_dir,
        repo_root=repo_root,
        beads_root=beads_root,
        worktree_path=Path(worktree_raw),
        planner_branch=planner_branch,
        default_branch=default_branch,
        git_path=git_path,
    )
    service = PlannerSyncService(context, emit=emit)
    service.sync_event(trigger=f"hook:{event}")

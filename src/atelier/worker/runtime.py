"""Worker runtime loop orchestration helpers."""

from __future__ import annotations

import time
from collections.abc import Callable

from .models import WorkerRunSummary


def run_worker_sessions(
    *,
    args: object,
    mode: str,
    run_mode: str,
    dry_run: bool,
    session_key: str,
    run_worker_once: Callable[..., WorkerRunSummary],
    report_worker_summary: Callable[[WorkerRunSummary, bool], None],
    watch_interval_seconds: Callable[[], int],
    dry_run_log: Callable[[str], None],
    emit: Callable[[str], None],
    sleep_fn: Callable[[float], None] = time.sleep,
) -> None:
    if bool(getattr(args, "queue", False)):
        summary = run_worker_once(
            args, mode=mode, dry_run=dry_run, session_key=session_key
        )
        report_worker_summary(summary, dry_run)
        return

    if dry_run:
        while True:
            summary = run_worker_once(
                args, mode=mode, dry_run=True, session_key=session_key
            )
            report_worker_summary(summary, True)
            if summary.started:
                if run_mode == "once":
                    return
                continue
            if summary.reason == "no_ready_changesets":
                if run_mode == "watch":
                    interval = watch_interval_seconds()
                    dry_run_log(
                        "Watching for updates "
                        f"(sleeping {interval}s before next check)."
                    )
                    sleep_fn(interval)
                continue
            if run_mode != "watch":
                return
            interval = watch_interval_seconds()
            dry_run_log(
                f"Watching for updates (sleeping {interval}s before next check)."
            )
            sleep_fn(interval)
        return

    while True:
        summary = run_worker_once(
            args, mode=mode, dry_run=False, session_key=session_key
        )
        report_worker_summary(summary, False)
        if summary.started:
            if run_mode == "once":
                return
            continue
        if summary.reason == "no_ready_changesets":
            if run_mode == "watch":
                interval = watch_interval_seconds()
                emit(f"No ready work; watching for updates (sleeping {interval}s).")
                sleep_fn(interval)
            continue
        if run_mode == "watch":
            interval = watch_interval_seconds()
            emit(f"No ready work; watching for updates (sleeping {interval}s).")
            sleep_fn(interval)
            continue
        return

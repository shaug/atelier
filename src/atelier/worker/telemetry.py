"""Worker runtime telemetry helpers."""

from __future__ import annotations

import os
import time
from collections.abc import Callable

from .models import WorkerRunSummary


def trace_enabled(env_var: str) -> bool:
    """Return whether command trace output is enabled for an env var."""
    return os.environ.get(env_var, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def step(
    label: str,
    *,
    timings: list[tuple[str, float]],
    trace: bool,
    say: Callable[[str], None],
    log_debug: Callable[[str], None] | None = None,
) -> Callable[[str | None], None]:
    """Render start/finish status for a named command step."""
    say(f"-> {label}")
    if log_debug is not None:
        log_debug(f"step start label={label}")
    start = time.perf_counter()

    def finish(extra: str | None = None) -> None:
        elapsed = time.perf_counter() - start
        timings.append((label, elapsed))
        suffix = f" ({elapsed:.2f}s)" if trace or elapsed >= 0.5 else ""
        if extra:
            say(f"ok {label}{suffix}: {extra}")
            if log_debug is not None:
                log_debug(
                    f"step finish label={label} elapsed={elapsed:.2f}s detail={extra}"
                )
            return
        say(f"ok {label}{suffix}")
        if log_debug is not None:
            log_debug(f"step finish label={label} elapsed={elapsed:.2f}s")

    return finish


def report_timings(
    timings: list[tuple[str, float]], *, trace: bool, say: Callable[[str], None]
) -> None:
    """Render timing summary when trace enabled or step is slow."""
    if not timings:
        return
    slow = [(label, elapsed) for label, elapsed in timings if elapsed >= 0.5]
    if not trace and not slow:
        return
    say("Timing summary:")
    for label, elapsed in sorted(timings, key=lambda item: item[1], reverse=True):
        if not trace and elapsed < 0.5:
            continue
        say(f"- {label}: {elapsed:.2f}s")


def report_worker_summary(
    summary: WorkerRunSummary,
    *,
    dry_run: bool,
    say: Callable[[str], None],
    log_debug: Callable[[str], None] | None = None,
) -> None:
    """Render the worker session summary."""
    prefix = "DRY-RUN " if dry_run else ""
    status = "started worker session" if summary.started else "no worker started"
    say(f"{prefix}Summary: {status}")
    if summary.reason:
        say(f"- Reason: {summary.reason}")
    if summary.epic_id:
        say(f"- Epic: {summary.epic_id}")
    if summary.changeset_id:
        say(f"- Changeset: {summary.changeset_id}")
    if log_debug is not None:
        log_debug(
            "summary "
            f"started={summary.started} reason={summary.reason or 'none'} "
            f"epic={summary.epic_id or 'none'} "
            f"changeset={summary.changeset_id or 'none'} dry_run={dry_run}"
        )

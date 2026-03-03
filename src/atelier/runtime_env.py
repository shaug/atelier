"""Runtime environment sanitization helpers for spawned subprocesses."""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping

LEGACY_AMBIENT_ENV_REMOVAL_DATE = "2026-07-01"
_WARNING_SAMPLE_LIMIT = 6

USER_DEFAULT_ENV_KEYS: frozenset[str] = frozenset(
    {
        "ATELIER_MODE",
        "ATELIER_RUN_MODE",
        "ATELIER_WATCH_INTERVAL",
        "ATELIER_WORK_YES",
        "ATELIER_PLAN_TRACE",
        "ATELIER_WORK_TRACE",
        "ATELIER_LOG_LEVEL",
        "ATELIER_NO_COLOR",
        "ATELIER_STARTUP_DEFERRED_EPIC_SCAN_LIMIT",
    }
)


def sanitize_subprocess_environment(
    *,
    base_env: Mapping[str, str] | None = None,
    preserve_keys: Iterable[str] = (),
) -> tuple[dict[str, str], tuple[str, ...]]:
    """Return a subprocess environment without inherited runtime-routing keys.

    Args:
        base_env: Optional source environment map. When omitted, current process
            environment is used.
        preserve_keys: Additional ``ATELIER_*`` keys that must survive
            sanitization.

    Returns:
        Tuple of ``(sanitized_env, removed_keys)`` where ``removed_keys`` are
        the inherited ``ATELIER_*`` runtime-routing variables dropped from the
        environment before launch.
    """
    env = dict(os.environ if base_env is None else base_env)
    allowed = set(USER_DEFAULT_ENV_KEYS)
    allowed.update(str(key) for key in preserve_keys if str(key).strip())
    removed: list[str] = []
    for key in sorted(env):
        if not key.startswith("ATELIER_"):
            continue
        if key in allowed:
            continue
        removed.append(key)
    for key in removed:
        env.pop(key, None)
    return env, tuple(removed)


def format_ambient_env_warning(removed_keys: Iterable[str]) -> str | None:
    """Build a compatibility warning for dropped inherited runtime env keys.

    Args:
        removed_keys: Iterable of removed ``ATELIER_*`` key names.

    Returns:
        User-facing warning text when keys were removed; otherwise ``None``.
    """
    unique = sorted({key for key in removed_keys if key})
    if not unique:
        return None
    sample = ", ".join(unique[:_WARNING_SAMPLE_LIMIT])
    suffix = ""
    if len(unique) > _WARNING_SAMPLE_LIMIT:
        suffix = f", +{len(unique) - _WARNING_SAMPLE_LIMIT} more"
    return (
        "Warning: ignored inherited runtime routing env keys "
        f"({sample}{suffix}). "
        "Use launch-time project context instead of ambient ATELIER_* routing "
        "state; legacy fallback compatibility is scheduled for removal after "
        f"{LEGACY_AMBIENT_ENV_REMOVAL_DATE}."
    )

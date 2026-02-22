"""Resolve supported ``ATELIER_*`` values into CLI option defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Generic, Literal, TypeVar

from .io import die

T = TypeVar("T")

DefaultSource = Literal["cli", "env", "built-in"]

_WORK_MODE_VALUES = ("prompt", "auto")
_WORK_RUN_MODE_VALUES = ("once", "default", "watch")
_WATCH_INTERVAL_SECONDS = 60
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"0", "false", "no", "off"})


@dataclass(frozen=True)
class CliEnvDefaultMapping:
    """Describe a supported env var to CLI default mapping."""

    flag: str
    env_var: str
    built_in_default: str
    accepted_values: str


@dataclass(frozen=True)
class ResolvedCliDefault(Generic[T]):
    """Represent one resolved CLI default value and where it came from."""

    flag: str
    value: T
    source: DefaultSource
    env_var: str | None = None
    raw_env_value: str | None = None


WORK_CLI_ENV_DEFAULTS: tuple[CliEnvDefaultMapping, ...] = (
    CliEnvDefaultMapping(
        flag="--mode",
        env_var="ATELIER_MODE",
        built_in_default="prompt",
        accepted_values="prompt|auto",
    ),
    CliEnvDefaultMapping(
        flag="--run-mode",
        env_var="ATELIER_RUN_MODE",
        built_in_default="default",
        accepted_values="once|default|watch",
    ),
    CliEnvDefaultMapping(
        flag="--watch-interval-seconds",
        env_var="ATELIER_WATCH_INTERVAL",
        built_in_default="60",
        accepted_values="positive integer",
    ),
    CliEnvDefaultMapping(
        flag="--yes",
        env_var="ATELIER_WORK_YES",
        built_in_default="false",
        accepted_values="1|true|yes|on|0|false|no|off",
    ),
)


WORK_UNSUPPORTED_CLI_DEFAULT_ENV_KEYS: tuple[str, ...] = (
    "ATELIER_PLAN_TRACE",
    "ATELIER_WORK_TRACE",
    "ATELIER_LOG_LEVEL",
    "ATELIER_NO_COLOR",
)


def _normalize_choice(value: str, *, source: str, allowed: tuple[str, ...]) -> str:
    normalized = value.strip().lower()
    if normalized not in allowed:
        die(f"{source} must be one of: " + ", ".join(allowed))
    return normalized


def resolve_work_mode_default(explicit: str | None) -> ResolvedCliDefault[str]:
    """Resolve the default value for ``atelier work --mode``.

    Args:
        explicit: Explicit ``--mode`` value from CLI arguments.

    Returns:
        Resolved mode value and source metadata.
    """
    if explicit is not None:
        return ResolvedCliDefault(
            flag="--mode",
            value=_normalize_choice(explicit, source="mode", allowed=_WORK_MODE_VALUES),
            source="cli",
        )
    raw = os.environ.get("ATELIER_MODE", "").strip()
    if not raw:
        return ResolvedCliDefault(flag="--mode", value="prompt", source="built-in")
    return ResolvedCliDefault(
        flag="--mode",
        value=_normalize_choice(raw, source="ATELIER_MODE", allowed=_WORK_MODE_VALUES),
        source="env",
        env_var="ATELIER_MODE",
        raw_env_value=raw,
    )


def resolve_work_run_mode_default(explicit: str | None) -> ResolvedCliDefault[str]:
    """Resolve the default value for ``atelier work --run-mode``.

    Args:
        explicit: Explicit ``--run-mode`` value from CLI arguments.

    Returns:
        Resolved run mode value and source metadata.
    """
    if explicit is not None:
        return ResolvedCliDefault(
            flag="--run-mode",
            value=_normalize_choice(explicit, source="run mode", allowed=_WORK_RUN_MODE_VALUES),
            source="cli",
        )
    raw = os.environ.get("ATELIER_RUN_MODE", "").strip()
    if not raw:
        return ResolvedCliDefault(flag="--run-mode", value="default", source="built-in")
    return ResolvedCliDefault(
        flag="--run-mode",
        value=_normalize_choice(raw, source="ATELIER_RUN_MODE", allowed=_WORK_RUN_MODE_VALUES),
        source="env",
        env_var="ATELIER_RUN_MODE",
        raw_env_value=raw,
    )


def resolve_work_watch_interval_default() -> ResolvedCliDefault[int]:
    """Resolve default watch-loop interval seconds for ``atelier work``.

    Returns:
        Resolved positive watch interval and source metadata.
    """
    raw = os.environ.get("ATELIER_WATCH_INTERVAL", "").strip()
    if not raw:
        return ResolvedCliDefault(
            flag="--watch-interval-seconds",
            value=_WATCH_INTERVAL_SECONDS,
            source="built-in",
        )
    try:
        value = int(raw)
    except ValueError:
        die("ATELIER_WATCH_INTERVAL must be an integer number of seconds")
    if value <= 0:
        die("ATELIER_WATCH_INTERVAL must be a positive number of seconds")
    return ResolvedCliDefault(
        flag="--watch-interval-seconds",
        value=value,
        source="env",
        env_var="ATELIER_WATCH_INTERVAL",
        raw_env_value=raw,
    )


def resolve_work_yes_default(explicit_yes: bool) -> ResolvedCliDefault[bool]:
    """Resolve the default value for ``atelier work --yes``.

    Args:
        explicit_yes: Whether ``--yes`` was provided explicitly.

    Returns:
        Resolved ``--yes`` boolean and source metadata.
    """
    if explicit_yes:
        return ResolvedCliDefault(flag="--yes", value=True, source="cli")
    raw = os.environ.get("ATELIER_WORK_YES", "").strip()
    if not raw:
        return ResolvedCliDefault(flag="--yes", value=False, source="built-in")
    normalized = raw.lower()
    if normalized in _TRUE_VALUES:
        return ResolvedCliDefault(
            flag="--yes",
            value=True,
            source="env",
            env_var="ATELIER_WORK_YES",
            raw_env_value=raw,
        )
    if normalized in _FALSE_VALUES:
        return ResolvedCliDefault(
            flag="--yes",
            value=False,
            source="env",
            env_var="ATELIER_WORK_YES",
            raw_env_value=raw,
        )
    die("ATELIER_WORK_YES must be one of: 1, true, yes, on, 0, false, no, off")


def describe_translated_default(value: ResolvedCliDefault[object]) -> str:
    """Return a human-readable diagnostics message for env translation.

    Args:
        value: Resolved default metadata.

    Returns:
        Diagnostic string describing env-to-CLI default translation.
    """
    env_var = value.env_var or "<unknown>"
    raw = value.raw_env_value if value.raw_env_value is not None else ""
    return f"translated {env_var}={raw!r} into default {value.flag}={value.value!r}"


__all__ = [
    "WORK_CLI_ENV_DEFAULTS",
    "WORK_UNSUPPORTED_CLI_DEFAULT_ENV_KEYS",
    "CliEnvDefaultMapping",
    "ResolvedCliDefault",
    "describe_translated_default",
    "resolve_work_mode_default",
    "resolve_work_run_mode_default",
    "resolve_work_watch_interval_default",
    "resolve_work_yes_default",
]

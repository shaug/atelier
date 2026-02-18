"""Structured terminal logging for Atelier commands."""

from __future__ import annotations

import os
import sys
from enum import IntEnum

from rich.console import Console
from rich.text import Text


class LogLevel(IntEnum):
    TRACE = 10
    DEBUG = 20
    INFO = 30
    SUCCESS = 35
    WARNING = 40
    ERROR = 50


_LEVEL_BY_NAME = {
    "trace": LogLevel.TRACE,
    "debug": LogLevel.DEBUG,
    "info": LogLevel.INFO,
    "success": LogLevel.SUCCESS,
    "warning": LogLevel.WARNING,
    "warn": LogLevel.WARNING,
    "error": LogLevel.ERROR,
}
_DEFAULT_LEVEL = LogLevel.INFO
_configured_level = None


def _normalize_level(value: str | None) -> LogLevel:
    if value is None:
        return _DEFAULT_LEVEL
    normalized = value.strip().lower()
    if not normalized:
        return _DEFAULT_LEVEL
    return _LEVEL_BY_NAME.get(normalized, _DEFAULT_LEVEL)


def configured_level() -> LogLevel:
    global _configured_level
    if _configured_level is None:
        _configured_level = _normalize_level(os.environ.get("ATELIER_LOG_LEVEL"))
    return _configured_level


def set_level(value: str | None) -> None:
    """Set the active log level."""
    global _configured_level
    _configured_level = _normalize_level(value)


def is_enabled(level: LogLevel) -> bool:
    return level >= configured_level()


def _console(*, stderr: bool) -> Console:
    return Console(
        file=sys.stderr if stderr else sys.stdout,
        soft_wrap=True,
        highlight=False,
        no_color=bool(os.environ.get("NO_COLOR") or os.environ.get("ATELIER_NO_COLOR")),
    )


def _default_style(level: LogLevel) -> str:
    if level is LogLevel.TRACE:
        return "dim"
    if level is LogLevel.DEBUG:
        return "cyan"
    if level is LogLevel.SUCCESS:
        return "green"
    if level is LogLevel.WARNING:
        return "yellow"
    if level is LogLevel.ERROR:
        return "bold red"
    return ""


def emit(
    level: LogLevel,
    message: str,
    *,
    style: str | None = None,
    stderr: bool | None = None,
) -> None:
    if not is_enabled(level):
        return
    target_stderr = stderr if stderr is not None else level >= LogLevel.WARNING
    text = Text(message, style=style or _default_style(level))
    _console(stderr=target_stderr).print(text)


def trace(message: str, *, style: str | None = None) -> None:
    emit(LogLevel.TRACE, message, style=style, stderr=False)


def debug(message: str, *, style: str | None = None) -> None:
    emit(LogLevel.DEBUG, message, style=style, stderr=False)


def info(message: str, *, style: str | None = None) -> None:
    emit(LogLevel.INFO, message, style=style, stderr=False)


def success(message: str, *, style: str | None = None) -> None:
    emit(LogLevel.SUCCESS, message, style=style, stderr=False)


def warning(message: str, *, style: str | None = None) -> None:
    emit(LogLevel.WARNING, message, style=style, stderr=True)


def error(message: str, *, style: str | None = None) -> None:
    emit(LogLevel.ERROR, message, style=style, stderr=True)

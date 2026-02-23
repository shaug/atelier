"""Utilities for constructing deterministic ``bd`` invocations."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Mapping

from . import paths

_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}


def _parse_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in _TRUE_VALUES:
            return True
        if normalized in _FALSE_VALUES:
            return False
    return None


def _load_json_dict(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if isinstance(payload, dict):
        return payload
    return {}


def _project_beads_settings(project_dir: Path) -> dict[str, object]:
    sys_payload = _load_json_dict(paths.project_config_sys_path(project_dir))
    user_payload = _load_json_dict(paths.project_config_user_path(project_dir))
    settings: dict[str, object] = {}
    for payload in (sys_payload, user_payload):
        beads_section = payload.get("beads")
        if isinstance(beads_section, dict):
            settings.update(beads_section)
    return settings


def _daemon_mode_from_settings(settings: Mapping[str, object]) -> bool | None:
    for key in ("daemon", "daemon_enabled", "use_daemon"):
        parsed = _parse_bool(settings.get(key))
        if parsed is not None:
            return parsed

    for key in ("no_daemon", "no-daemon"):
        parsed = _parse_bool(settings.get(key))
        if parsed is not None:
            return not parsed

    for key in ("mode", "invocation", "invocation_mode"):
        value = settings.get(key)
        if not isinstance(value, str):
            continue
        normalized = value.strip().lower().replace("_", "-")
        if normalized == "daemon":
            return True
        if normalized in {"direct", "no-daemon"}:
            return False

    for key in ("daemon.db", "daemon_db"):
        value = settings.get(key)
        if isinstance(value, str) and value.strip():
            return True
    return None


def _candidate_project_dirs(*, beads_dir: str | None, env: Mapping[str, str]) -> list[Path]:
    candidates: list[Path] = []
    seen: set[Path] = set()

    for raw in (env.get("ATELIER_PROJECT"), beads_dir, env.get("BEADS_DIR")):
        if not raw:
            continue
        expanded = Path(raw).expanduser()
        project_dir = expanded
        if expanded.name == paths.BEADS_DIRNAME:
            project_dir = expanded.parent
        if project_dir in seen:
            continue
        seen.add(project_dir)
        candidates.append(project_dir)
    return candidates


def should_use_bd_daemon(*, beads_dir: str | None, env: Mapping[str, str] | None = None) -> bool:
    """Return whether daemon mode is explicitly configured for ``bd`` calls.

    The default is direct mode (``--no-daemon``). Daemon mode is enabled only
    when explicit env/config overrides request it.
    """

    env_map = dict(env or os.environ)

    for key in ("ATELIER_BD_DAEMON", "BEADS_DAEMON"):
        parsed = _parse_bool(env_map.get(key))
        if parsed is not None:
            return parsed

    no_daemon = _parse_bool(env_map.get("BEADS_NO_DAEMON"))
    if no_daemon is True:
        return False
    if no_daemon is False:
        return True

    auto_start_daemon = _parse_bool(env_map.get("BEADS_AUTO_START_DAEMON"))
    if auto_start_daemon is True:
        return True

    beads_db = env_map.get("BEADS_DB")
    if isinstance(beads_db, str) and beads_db.strip():
        return True

    for project_dir in _candidate_project_dirs(beads_dir=beads_dir, env=env_map):
        mode = _daemon_mode_from_settings(_project_beads_settings(project_dir))
        if mode is not None:
            return mode

    return False


def with_bd_mode(
    *args: str, beads_dir: str | None, env: Mapping[str, str] | None = None
) -> list[str]:
    """Return a ``bd`` command with deterministic mode selection."""

    command = ["bd", *args]
    if args and args[0] == "daemon":
        return command
    if "--no-daemon" in command:
        return command
    if should_use_bd_daemon(beads_dir=beads_dir, env=env):
        return command
    command.append("--no-daemon")
    return command

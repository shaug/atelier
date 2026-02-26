"""Utilities for constructing deterministic ``bd`` invocations."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Mapping

MIN_SUPPORTED_BD_VERSION: tuple[int, int, int] = (0, 51, 0)
_SEMVER_PATTERN = re.compile(r"\bv?(\d+)\.(\d+)\.(\d+)\b")


def _format_version(version: tuple[int, int, int]) -> str:
    return f"{version[0]}.{version[1]}.{version[2]}"


def _parse_semver(value: str) -> tuple[int, int, int] | None:
    match = _SEMVER_PATTERN.search(value)
    if match is None:
        return None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


@lru_cache(maxsize=16)
def _read_bd_version_for_executable(executable: str) -> tuple[int, int, int] | None:
    try:
        result = subprocess.run(
            [executable, "--version"],
            check=False,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
        )
    except OSError:
        return None
    output = f"{result.stdout or ''}\n{result.stderr or ''}"
    return _parse_semver(output)


def detect_bd_version(*, env: Mapping[str, str] | None = None) -> tuple[int, int, int]:
    """Return the semantic version for the active ``bd`` executable.

    Args:
        env: Optional environment mapping used for resolving ``PATH``.

    Returns:
        Parsed semantic version tuple for ``bd``.

    Raises:
        RuntimeError: If ``bd`` is missing or its version cannot be parsed.
    """

    env_map = dict(env or os.environ)
    executable = shutil.which("bd", path=env_map.get("PATH"))
    if not executable:
        raise RuntimeError("missing required command: bd")

    detected = _read_bd_version_for_executable(executable)
    if detected is None:
        raise RuntimeError(
            "unsupported bd version: unable to determine version; "
            "Atelier requires a semantic version"
        )
    return detected


def ensure_supported_bd_version(*, env: Mapping[str, str] | None = None) -> None:
    """Validate that the active ``bd`` executable meets Atelier's minimum version.

    Args:
        env: Optional environment mapping used for resolving ``PATH``.

    Raises:
        RuntimeError: If ``bd`` is missing, unparsable, or below the minimum
            supported version.
    """

    detected = detect_bd_version(env=env)
    required = _format_version(MIN_SUPPORTED_BD_VERSION)
    if detected < MIN_SUPPORTED_BD_VERSION:
        detected_str = _format_version(detected)
        raise RuntimeError(
            f"unsupported bd version: {detected_str}; Atelier requires bd >= {required}"
        )


def with_bd_mode(
    *args: str, beads_dir: str | None, env: Mapping[str, str] | None = None
) -> list[str]:
    """Return a ``bd`` command with deterministic database selection."""

    del env
    command = ["bd"]
    has_db_flag = any(argument == "--db" or argument.startswith("--db=") for argument in args)
    if beads_dir and not has_db_flag:
        db_path = Path(beads_dir).expanduser() / "beads.db"
        command.extend(["--db", str(db_path)])
    command.extend(args)
    return command

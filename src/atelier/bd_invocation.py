"""Utilities for constructing deterministic ``bd`` invocations."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from functools import lru_cache
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


def ensure_supported_bd_version(*, env: Mapping[str, str] | None = None) -> None:
    """Validate that the active ``bd`` executable meets Atelier's minimum version.

    Args:
        env: Optional environment mapping used for resolving ``PATH``.

    Raises:
        RuntimeError: If ``bd`` is missing, unparsable, or below the minimum
            supported version.
    """

    env_map = dict(env or os.environ)
    executable = shutil.which("bd", path=env_map.get("PATH"))
    if not executable:
        raise RuntimeError("missing required command: bd")

    detected = _read_bd_version_for_executable(executable)
    required = _format_version(MIN_SUPPORTED_BD_VERSION)
    if detected is None:
        raise RuntimeError(
            f"unsupported bd version: unable to determine version; Atelier requires bd >= {required}"
        )
    if detected < MIN_SUPPORTED_BD_VERSION:
        detected_str = _format_version(detected)
        raise RuntimeError(
            f"unsupported bd version: {detected_str}; Atelier requires bd >= {required}"
        )


def with_bd_mode(
    *args: str, beads_dir: str | None, env: Mapping[str, str] | None = None
) -> list[str]:
    """Return a direct ``bd`` command."""

    del beads_dir, env
    return ["bd", *args]

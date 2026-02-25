"""Utilities for constructing deterministic ``bd`` invocations."""

from __future__ import annotations

from typing import Mapping


def with_bd_mode(
    *args: str, beads_dir: str | None, env: Mapping[str, str] | None = None
) -> list[str]:
    """Return a direct ``bd`` command."""

    del beads_dir, env
    return ["bd", *args]

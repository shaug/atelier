#!/usr/bin/env python3
"""Repair PATH shadowing after a ``uv tool install``.

This helper removes broken console launchers for a tool when they shadow the
``uv tool`` launcher in the user's bin directory. It is intended for use by the
repository's install recipes.
"""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import site
import subprocess
import sys
from pathlib import Path
from typing import Sequence


def _path_directories(path_value: str | None) -> list[Path]:
    directories: list[Path] = []
    seen: set[Path] = set()
    for raw_entry in (path_value or "").split(os.pathsep):
        entry = raw_entry.strip()
        if not entry:
            continue
        path = Path(entry).expanduser()
        if path in seen:
            continue
        seen.add(path)
        directories.append(path)
    return directories


def _user_bin_dir() -> Path:
    base = site.USER_BASE or site.getuserbase()
    dirname = "Scripts" if os.name == "nt" else "bin"
    return Path(base) / dirname


def _candidate_launchers(tool_name: str, path_value: str | None) -> list[Path]:
    candidates: list[Path] = []
    seen: set[Path] = set()
    for directory in _path_directories(path_value):
        candidate = directory / tool_name
        if not candidate.exists():
            continue
        resolved = candidate.resolve(strict=False)
        if resolved in seen:
            continue
        seen.add(resolved)
        candidates.append(candidate)
    return candidates


def _read_first_line(path: Path) -> str | None:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return handle.readline().strip()
    except OSError:
        return None


def _script_contains_import(path: Path, import_target: str) -> bool:
    marker = f"from {import_target} import main"
    try:
        return marker in path.read_text(encoding="utf-8")
    except OSError:
        return False


def _resolve_interpreter(path: Path, path_value: str | None) -> Path | None:
    first_line = _read_first_line(path)
    if not first_line or not first_line.startswith("#!"):
        return None
    parts = shlex.split(first_line[2:])
    if not parts:
        return None
    if Path(parts[0]).name != "env":
        return Path(parts[0]).expanduser()
    for part in parts[1:]:
        if not part or part.startswith("-") or "=" in part:
            continue
        resolved = shutil.which(part, path=path_value)
        return Path(resolved).expanduser() if resolved else None
    return None


def _interpreter_can_import(interpreter: Path | None, import_target: str) -> bool:
    if interpreter is None or not interpreter.exists():
        return False
    result = subprocess.run(
        [str(interpreter), "-c", f"import {import_target}"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def _remove_broken_shadowed_launchers(tool_name: str, import_target: str) -> int:
    path_value = os.environ.get("PATH")
    expected = (_user_bin_dir() / tool_name).resolve(strict=False)
    removed = 0

    for candidate in _candidate_launchers(tool_name, path_value):
        resolved = candidate.resolve(strict=False)
        if resolved == expected:
            continue
        if not _script_contains_import(candidate, import_target):
            continue
        interpreter = _resolve_interpreter(candidate, path_value)
        if _interpreter_can_import(interpreter, import_target):
            print(
                f"warning: {candidate} shadows {_user_bin_dir() / tool_name}",
                file=sys.stderr,
            )
            continue
        candidate.unlink(missing_ok=True)
        removed += 1
        print(f"removed stale launcher: {candidate}", file=sys.stderr)
    return removed


def main(argv: Sequence[str] | None = None) -> int:
    """Remove broken PATH launchers that shadow the installed tool.

    Args:
        argv: Optional CLI arguments. The first positional argument is the tool
            name. The second positional argument is the Python import target
            used by the generated console script.

    Returns:
        Process exit code.
    """

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tool_name")
    parser.add_argument("import_target")
    args = parser.parse_args(argv)
    _remove_broken_shadowed_launchers(args.tool_name, args.import_target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

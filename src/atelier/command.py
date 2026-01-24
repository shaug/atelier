"""Command normalization helpers for Atelier."""

from __future__ import annotations

import os
import shlex
import shutil
from pathlib import Path


def _looks_like_path(value: str) -> bool:
    if not value:
        return False
    if os.name == "nt":
        if "\\" in value or ":" in value:
            return True
        return value.lower().endswith(".exe")
    return "/" in value


def _path_exists(value: str) -> bool:
    try:
        return Path(value).expanduser().exists()
    except OSError:
        return False


def _split_command(value: str) -> list[str]:
    if not value:
        return []
    posix = os.name != "nt"
    try:
        parts = shlex.split(value, posix=posix)
    except ValueError:
        return [value]
    return [part for part in parts if part]


def _merge_existing_paths(parts: list[str]) -> list[str]:
    if len(parts) < 2:
        return parts
    merged: list[str] = []
    index = 0
    while index < len(parts):
        token = parts[index]
        if _looks_like_path(token):
            match: str | None = None
            end_index: int | None = None
            for offset in range(len(parts), index, -1):
                candidate = " ".join(parts[index:offset])
                if _path_exists(candidate):
                    match = candidate
                    end_index = offset
                    break
            if match is not None and end_index is not None:
                merged.append(match)
                index = end_index
                continue
        merged.append(token)
        index += 1
    return merged


def normalize_command(value: object) -> list[str] | None:
    """Normalize command inputs into argv lists."""
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if _path_exists(text):
            return [text]
        if " " not in text and "\t" not in text and shutil.which(text):
            return [text]
        parts = _split_command(text)
        if not parts:
            return []
        return _merge_existing_paths(parts)
    return None

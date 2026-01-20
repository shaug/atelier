"""Codex session discovery helpers."""

import json
from pathlib import Path

from .workspace import workspace_identifier


def read_first_user_message(path: Path) -> str | None:
    """Read the first user message from a session transcript file.

    Supports JSON and JSONL session formats.

    Args:
        path: Path to the session file.

    Returns:
        First user message text, or ``None`` if unavailable.

    Example:
        >>> read_first_user_message(Path("missing.json")) is None
        True
    """
    try:
        if path.suffix == ".jsonl":
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        return None
                    if isinstance(data, dict) and data.get("type") == "session_meta":
                        payload = data.get("payload")
                        if isinstance(payload, dict):
                            instructions = payload.get("instructions")
                            if instructions:
                                return str(instructions)
                    return extract_first_user_from_obj(data)
            return None
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    content = raw.lstrip()
    if content == "":
        return None
    if content[0] == "{":
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return extract_first_user_from_obj(data)
    if content[0] == "[":
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return extract_first_user_from_obj(data)
    # JSONL is handled above.
    return None


def read_session_id(path: Path) -> str | None:
    """Read the session ID from a Codex JSONL transcript file.

    Args:
        path: Path to the session file.

    Returns:
        Session ID string or ``None`` if not found.

    Example:
        >>> read_session_id(Path("missing.jsonl")) is None
        True
    """
    if path.suffix == ".jsonl":
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        return None
                    if isinstance(data, dict) and data.get("type") == "session_meta":
                        payload = data.get("payload")
                        if isinstance(payload, dict):
                            session_id = payload.get("id")
                            if session_id:
                                return str(session_id)
                    return None
        except OSError:
            return None
    return None


def extract_first_user_from_obj(data: object) -> str | None:
    """Extract the first user message from a structured object.

    Args:
        data: Parsed JSON object or list.

    Returns:
        First user message text, or ``None``.

    Example:
        >>> extract_first_user_from_obj({"messages": [{"role": "user", "content": "hi"}]})
        'hi'
    """
    if isinstance(data, dict):
        if "messages" in data and isinstance(data["messages"], list):
            return extract_first_user_from_list(data["messages"])
        if "history" in data and isinstance(data["history"], list):
            return extract_first_user_from_list(data["history"])
    if isinstance(data, list):
        return extract_first_user_from_list(data)
    return None


def extract_first_user_from_list(messages: list) -> str | None:
    """Extract the first user message from a list of message objects.

    Args:
        messages: List of message dicts.

    Returns:
        First user message text, or ``None`` if not found.

    Example:
        >>> extract_first_user_from_list([{"role": "user", "content": "hi"}])
        'hi'
    """
    for item in messages:
        if not isinstance(item, dict):
            continue
        role = item.get("role") or item.get("type")
        if role != "user":
            continue
        content = item.get("content") or item.get("text")
        if content is None:
            continue
        if isinstance(content, list):
            chunks: list[str] = []
            for part in content:
                if isinstance(part, dict):
                    text = part.get("text")
                    if text:
                        chunks.append(str(text))
                elif isinstance(part, str):
                    chunks.append(part)
            return "".join(chunks) if chunks else None
        return str(content)
    return None


def find_codex_session(project_enlistment: str, workspace_branch: str) -> str | None:
    """Find the most recent Codex session for a workspace.

    Args:
        project_enlistment: Absolute path to the local enlistment.
        workspace_branch: Workspace branch name.

    Returns:
        Session ID string when found, otherwise ``None``.

    Example:
        >>> find_codex_session(\"/repo\", \"feat/demo\") is None or True
        True
    """
    sessions_root = Path.home() / ".codex" / "sessions"
    if not sessions_root.exists():
        return None
    target = workspace_identifier(project_enlistment, workspace_branch)
    matches: list[tuple[float, Path, str | None]] = []
    for path in sessions_root.rglob("*"):
        if path.suffix not in {".json", ".jsonl"}:
            continue
        message = read_first_user_message(path)
        if not message:
            continue
        if target not in message:
            continue
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        session_id = read_session_id(path)
        matches.append((mtime, path, session_id))
    if not matches:
        return None
    matches.sort(key=lambda item: item[0], reverse=True)
    _, path, session_id = matches[0]
    return session_id or path.stem

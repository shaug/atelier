"""Codex session discovery helpers."""

import json
from collections.abc import Iterator
from pathlib import Path

from .workspace import workspace_identifier


def read_first_user_message(path: Path) -> str | None:
    """Read the first command-line user message from a session transcript file.

    Supports JSON and JSONL session formats.

    Args:
        path: Path to the session file.

    Returns:
        First command-line user message text, or ``None`` if unavailable.

    Example:
        >>> read_first_user_message(Path("missing.json")) is None
        True
    """
    try:
        if path.suffix == ".jsonl":
            fallback_instructions: str | None = None
            fallback_message: str | None = None
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        return None
                    if isinstance(data, dict):
                        if data.get("type") == "session_meta":
                            payload = data.get("payload")
                            if isinstance(payload, dict):
                                instructions = payload.get("instructions")
                                if instructions:
                                    fallback_instructions = str(instructions)
                            continue
                        message = extract_user_message_from_record(data)
                        if message:
                            return message
                        if fallback_message is None:
                            for message in iter_user_messages_from_record(data):
                                fallback_message = message
                                break
                    else:
                        if fallback_message is None:
                            for message in iter_user_messages_from_obj(data):
                                fallback_message = message
                                break
            return fallback_message or fallback_instructions
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
        if data.get("role") == "user":
            content = data.get("content") or data.get("text")
            return extract_message_content(content)
    if isinstance(data, list):
        return extract_first_user_from_list(data)
    return None


def iter_user_messages_from_obj(data: object) -> Iterator[str]:
    """Iterate user message text from structured objects."""
    if isinstance(data, dict):
        if "messages" in data and isinstance(data["messages"], list):
            yield from iter_user_messages_from_list(data["messages"])
        if "history" in data and isinstance(data["history"], list):
            yield from iter_user_messages_from_list(data["history"])
        if data.get("role") == "user":
            content = data.get("content") or data.get("text")
            text = extract_message_content(content)
            if text:
                yield text
    if isinstance(data, list):
        yield from iter_user_messages_from_list(data)


def iter_user_messages_from_list(messages: list) -> Iterator[str]:
    """Iterate user message text from a list of message objects."""
    for item in messages:
        if not isinstance(item, dict):
            continue
        role = item.get("role") or item.get("type")
        if role != "user":
            continue
        content = item.get("content") or item.get("text")
        text = extract_message_content(content)
        if text:
            yield text


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
    for text in iter_user_messages_from_list(messages):
        return text
    return None


def extract_message_content(content: object) -> str | None:
    """Normalize message content into plain text."""
    if content is None:
        return None
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        text = content.get("text")
        if text:
            return str(text)
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
    return None


def extract_user_message_from_record(data: dict) -> str | None:
    """Extract the first command-line user prompt from Codex JSONL records."""
    record_type = data.get("type")
    if record_type != "event_msg":
        return None
    payload = data.get("payload")
    if isinstance(payload, dict) and payload.get("type") == "user_message":
        message = payload.get("message")
        if message:
            return str(message)
    return None


def iter_user_messages_from_record(data: dict) -> Iterator[str]:
    """Iterate user messages from Codex JSONL records."""
    payload = data.get("payload")
    if data.get("type") == "response_item" and isinstance(payload, dict):
        if payload.get("type") == "message" and payload.get("role") == "user":
            content = payload.get("content") or payload.get("text")
            text = extract_message_content(content)
            if text:
                yield text
        elif payload.get("role") == "user":
            content = payload.get("content") or payload.get("text")
            text = extract_message_content(content)
            if text:
                yield text
    yield from iter_user_messages_from_obj(data)


def session_contains_target(path: Path, target: str) -> bool:
    """Check if the first command-line user message contains the target."""
    message = read_first_user_message(path)
    if not message:
        return False
    return target in message


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
        if not session_contains_target(path, target):
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

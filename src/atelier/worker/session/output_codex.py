"""Codex exec --json JSON Lines event schemas and parsing helpers."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict

# Codex item types that represent tool/command execution
_CODEX_TOOL_ITEM_TYPES = frozenset(
    {"command_execution", "mcp_tool_call", "web_search", "file_change"}
)
# Codex item types that carry agent text for preview
_CODEX_TEXT_ITEM_TYPES = frozenset({"agent_message", "reasoning"})


class CodexEvent(BaseModel):
    """
    Lenient model for Codex exec --json JSON Lines events.

    Event types: thread.started, turn.started, turn.completed, turn.failed,
    item.started, item.completed, error. Items include agent_message, reasoning,
    command_execution, file_change, mcp_tool_call, web_search, plan_update.

    See: https://developers.openai.com/codex/noninteractive/#create-structured-outputs-with-a-schema
    """

    model_config = ConfigDict(extra="allow")
    type: str = ""
    thread_id: str | None = None
    item: dict[str, Any] | None = None
    usage: dict[str, Any] | None = None
    error: dict[str, Any] | None = None


def parse_codex_event(line: str) -> CodexEvent | None:
    """Parse a JSON line into a CodexEvent, or return None if not parseable."""
    if not line or not line.strip().startswith("{"):
        return None
    try:
        raw = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(raw, dict):
        return None
    event_type = raw.get("type")
    if not isinstance(event_type, str) or not event_type:
        return None
    try:
        return CodexEvent.model_validate(raw)
    except Exception:
        return None


def extract_preview_text(event: CodexEvent) -> str | None:
    """Extract agent text from item.completed with type agent_message or reasoning."""
    if event.item is None:
        return None
    item_type = (event.item.get("type") or "").lower()
    if item_type not in _CODEX_TEXT_ITEM_TYPES:
        return None
    text = event.item.get("text")
    if isinstance(text, str) and text.strip():
        return " ".join(text.split())
    return None


def is_tool_event(event: CodexEvent) -> bool:
    """Return True if this event represents tool/command execution."""
    if event.item is None:
        return False
    item_type = (event.item.get("type") or "").lower()
    return item_type in _CODEX_TOOL_ITEM_TYPES or "tool" in item_type or "command" in item_type


def is_error_event(event: CodexEvent) -> bool:
    """Return True if this event indicates an error."""
    event_type = (event.type or "").lower()
    if event_type in ("error", "turn.failed"):
        return True
    return event.error is not None


def extract_error_message(event: CodexEvent) -> str | None:
    """Extract error message from an error event."""
    if event.error and isinstance(event.error, dict):
        msg = event.error.get("message")
        if isinstance(msg, str) and msg.strip():
            return " ".join(msg.split())
    text = extract_preview_text(event)
    if text and "failed" in (event.type or "").lower():
        return text
    return None

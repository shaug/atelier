"""Claude session/stream JSON event schemas and parsing helpers."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict

# Event types that carry assistant text for preview (session format)
_ASSISTANT_PREVIEW_TYPES = frozenset({"assistant", "message"})
# Event types that carry stream-format text deltas
_STREAM_TEXT_TYPES = frozenset({"content_block_delta", "content_block_start"})
# Event types that indicate tool use
_TOOL_EVENT_TYPES = frozenset({"tool_use", "tool_use_block_start", "tool_call", "tool_call_delta"})
# Event types that indicate errors
_ERROR_EVENT_TYPES = frozenset({"error", "error_event", "api_error"})


class ClaudeEvent(BaseModel):
    """
    Lenient model for Claude session/stream JSON events.

    One JSON object per line. Supports both session format (assistant/user with
    nested message.content) and stream format (content_block_delta with delta.text).
    """

    model_config = ConfigDict(extra="allow")
    type: str = ""
    subtype: str | None = None
    message: dict[str, Any] | None = None
    delta: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    result: str | None = None
    output: str | None = None


def parse_claude_event(line: str) -> ClaudeEvent | None:
    """Parse a JSON line into a ClaudeEvent, or return None if not parseable."""
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
        return ClaudeEvent.model_validate(raw)
    except Exception:
        return None


def extract_preview_text(event: ClaudeEvent) -> str | None:
    """
    Extract first user-facing text from an event for preview.

    Session format: assistant/user message.content with text blocks (not
    thinking). Stream format: content_block_delta.delta.text.
    """
    event_type = (event.type or "").lower()
    # Stream format
    if event_type in _STREAM_TEXT_TYPES and event.delta:
        text = event.delta.get("text")
        if isinstance(text, str) and text.strip():
            return " ".join(text.split())
        return None
    # Error payload
    if event.error and isinstance(event.error, dict):
        msg = event.error.get("message")
        if isinstance(msg, str) and msg.strip():
            return " ".join(msg.split())
    # Session format: assistant/user with message.content
    if event_type in _ASSISTANT_PREVIEW_TYPES or event_type in ("assistant", "user"):
        msg = event.message
        if msg is None:
            return None
        content = msg.get("content")
        if not isinstance(content, list):
            return None
        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = (block.get("type") or "").lower()
            if block_type == "thinking":
                continue
            if block_type == "text":
                text = block.get("text")
                if isinstance(text, str) and text.strip():
                    return " ".join(text.split())
                return None
            if block_type == "tool_result":
                text = block.get("content")
                if isinstance(text, str) and text.strip():
                    return " ".join(text.split())
                return None
    # Result event
    if event_type == "result" and event.result:
        s = str(event.result).strip()
        if s:
            return " ".join(s.split())
    return None


def is_tool_event(event: ClaudeEvent) -> bool:
    """Return True if this event represents a tool use/call."""
    event_type = (event.type or "").lower()
    if "tool" in event_type:
        return True
    # Session format: message.content has tool_use blocks
    if event_type in ("assistant", "user") and event.message:
        content = event.message.get("content", [])
        for block in content:
            if isinstance(block, dict):
                bt = (block.get("type") or "").lower()
                if "tool" in bt:
                    return True
    return False


def is_error_event(event: ClaudeEvent) -> bool:
    """Return True if this event indicates an error."""
    event_type = (event.type or "").lower()
    if event_type in _ERROR_EVENT_TYPES:
        return True
    if "error" in event_type:
        return True
    return event.error is not None


def extract_error_message(event: ClaudeEvent) -> str | None:
    """Extract error message from an error event."""
    if event.error and isinstance(event.error, dict):
        msg = event.error.get("message")
        if isinstance(msg, str) and msg.strip():
            return " ".join(msg.split())
    text = extract_preview_text(event)
    if text and ("error" in (event.type or "").lower() or "failed" in (event.type or "").lower()):
        return text
    return None

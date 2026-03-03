"""Claude session/stream JSON event schemas and parsing helpers."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict

from .output_contract import AdapterOutput, RenderEvent, RenderEventKind

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


def extract_tool_activity(event: ClaudeEvent) -> tuple[RenderEventKind, str] | None:
    """Extract normalized tool or command activity from a Claude event."""
    candidates = _tool_candidates(event)
    for candidate in candidates:
        name = candidate.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        name = name.strip()
        tool_input = candidate.get("input")
        command = _extract_command_from_tool_input(tool_input)
        if command is not None:
            return RenderEventKind.COMMAND, command
        return RenderEventKind.TOOL, name
    return None


def extract_reasoning_activity(event: ClaudeEvent) -> str | None:
    """Extract concise reasoning text from Claude thinking content blocks."""
    if event.message is None:
        return None
    content = event.message.get("content")
    if not isinstance(content, list):
        return None
    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = str(block.get("type") or "").lower()
        if block_type != "thinking":
            continue
        thinking = block.get("thinking")
        if isinstance(thinking, str) and thinking.strip():
            return " ".join(thinking.split())
    return None


def adapt_claude_line(line: str) -> AdapterOutput | None:
    """Adapt one Claude JSONL line to the shared render-event contract."""
    event = parse_claude_event(line)
    if event is None:
        return None

    events: list[RenderEvent] = []
    tool_activity = extract_tool_activity(event)
    if tool_activity is not None:
        kind, text = tool_activity
        events.append(RenderEvent(kind=kind, text=text))
    reasoning_activity = extract_reasoning_activity(event)
    if reasoning_activity:
        events.append(RenderEvent(kind=RenderEventKind.REASONING, text=reasoning_activity))
    diagnostic = extract_error_message(event)
    if diagnostic:
        events.append(RenderEvent(kind=RenderEventKind.ERROR, text=diagnostic))

    return AdapterOutput(
        consumed=True,
        structured=True,
        tool_event=is_tool_event(event),
        events=tuple(events),
        preview=extract_preview_text(event),
        diagnostic=diagnostic,
    )


def _tool_candidates(event: ClaudeEvent) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    if event.message is not None:
        content = event.message.get("content")
        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                block_type = str(block.get("type") or "").lower()
                if block_type == "tool_use":
                    candidates.append(block)
    event_type = str(event.type or "").lower()
    if event_type in _TOOL_EVENT_TYPES:
        candidate: dict[str, Any] = {}
        event_name = getattr(event, "name", None)
        event_input = getattr(event, "input", None)
        if isinstance(event_name, str) and event_name.strip():
            candidate["name"] = event_name
        if event_input is not None:
            candidate["input"] = event_input
        if isinstance(event.message, dict):
            if candidate.get("name") is None:
                candidate["name"] = event.message.get("name")
            if candidate.get("input") is None:
                candidate["input"] = event.message.get("input")
        if isinstance(event.delta, dict):
            if candidate.get("name") is None:
                candidate["name"] = event.delta.get("name")
            if candidate.get("input") is None:
                candidate["input"] = event.delta.get("input")
        if candidate.get("name") is not None:
            candidates.append(candidate)
    return candidates


def _extract_command_from_tool_input(tool_input: object) -> str | None:
    if not isinstance(tool_input, dict):
        return None
    command = tool_input.get("command")
    if isinstance(command, str) and command.strip():
        return " ".join(command.split())
    return None

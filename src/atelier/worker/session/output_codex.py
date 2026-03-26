"""Codex exec --json JSON Lines event schemas and parsing helpers."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict

from .output_contract import AdapterOutput, RenderEvent, RenderEventKind

# Codex item types that represent tool/command execution
_CODEX_TOOL_ITEM_TYPES = frozenset(
    {"command_execution", "mcp_tool_call", "web_search", "file_change"}
)
# Codex item types that carry agent text for preview
_CODEX_TEXT_ITEM_TYPES = frozenset({"agent_message", "reasoning"})
_MAX_TOOL_ACTIVITY_CHARS = 140
_MAX_REASONING_ACTIVITY_CHARS = 160


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


def extract_tool_activity(event: CodexEvent) -> str | None:
    """Extract concise tool activity text from a Codex event."""
    if event.item is None:
        return None
    item_type = (event.item.get("type") or "").lower()
    if item_type == "command_execution":
        command = event.item.get("command")
        if isinstance(command, str) and command.strip():
            return _clip_activity(f"command: {' '.join(command.split())}")
        return "command"
    if item_type == "mcp_tool_call":
        name = _first_string(event.item.get("name"), event.item.get("tool_name"))
        server = _first_string(event.item.get("server"), event.item.get("server_name"))
        if name and server:
            return _clip_activity(f"tool: {server}/{name}")
        if name:
            return _clip_activity(f"tool: {name}")
        return "tool call"
    if item_type == "web_search":
        query = _first_string(event.item.get("query"), event.item.get("text"))
        if query:
            return _clip_activity(f"search: {' '.join(query.split())}")
        return "web search"
    if item_type == "file_change":
        path = _first_string(event.item.get("path"), event.item.get("file_path"))
        if path:
            return _clip_activity(f"file: {path}")
        return "file change"
    if "tool" in item_type or "command" in item_type:
        return _clip_activity(item_type.replace("_", " "))
    return None


def extract_reasoning_activity(event: CodexEvent) -> str | None:
    """Extract concise reasoning text from a Codex reasoning event."""
    if event.item is None:
        return None
    item_type = (event.item.get("type") or "").lower()
    if item_type != "reasoning":
        return None
    text = event.item.get("text")
    if not isinstance(text, str) or not text.strip():
        return None
    return _clip_reasoning(" ".join(text.split()))


def adapt_codex_line(line: str) -> AdapterOutput | None:
    """Adapt one Codex JSONL line to the shared render-event contract."""
    event = parse_codex_event(line)
    if event is None:
        return None

    events: list[RenderEvent] = []
    tool_activity = extract_tool_activity(event)
    if tool_activity:
        kind, text = _render_event_from_tool_activity(tool_activity)
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
        session_id=event.thread_id.strip()
        if isinstance(event.thread_id, str) and event.thread_id.strip()
        else None,
    )


def _first_string(*values: object) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _render_event_from_tool_activity(activity: str) -> tuple[RenderEventKind, str]:
    if activity.startswith("command: "):
        return RenderEventKind.COMMAND, activity.removeprefix("command: ")
    if activity.startswith("tool: "):
        return RenderEventKind.TOOL, activity.removeprefix("tool: ")
    if activity.startswith("search: "):
        return RenderEventKind.TOOL, activity.removeprefix("search: ")
    if activity.startswith("file: "):
        return RenderEventKind.TOOL, activity.removeprefix("file: ")
    return RenderEventKind.TOOL, activity


def _clip_activity(value: str) -> str:
    text = " ".join(value.split())
    if len(text) <= _MAX_TOOL_ACTIVITY_CHARS:
        return text
    return f"{text[: _MAX_TOOL_ACTIVITY_CHARS - 3].rstrip()}..."


def _clip_reasoning(value: str) -> str:
    text = " ".join(value.split())
    if len(text) <= _MAX_REASONING_ACTIVITY_CHARS:
        return text
    return f"{text[: _MAX_REASONING_ACTIVITY_CHARS - 3].rstrip()}..."

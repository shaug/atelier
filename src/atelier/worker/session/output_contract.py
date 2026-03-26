"""Shared render-event contract for worker session output adapters."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

_MAX_RENDER_TEXT_CHARS = 160


class RenderEventKind(StrEnum):
    """Normalized event categories for worker-session terminal rendering."""

    REASONING = "reasoning"
    COMMAND = "command"
    TOOL = "tool"
    RESULT = "result"
    ERROR = "error"


@dataclass(frozen=True)
class RenderEvent:
    """Normalized render event emitted by an agent-specific adapter."""

    kind: RenderEventKind
    text: str


@dataclass(frozen=True)
class AdapterOutput:
    """Normalized output from a line adapter."""

    consumed: bool
    structured: bool
    tool_event: bool
    events: tuple[RenderEvent, ...] = ()
    preview: str | None = None
    diagnostic: str | None = None
    session_id: str | None = None


def normalize_render_text(text: str, *, max_chars: int = _MAX_RENDER_TEXT_CHARS) -> str:
    """Return a compact single-line render payload with deterministic clipping."""
    compact = " ".join(text.split())
    if len(compact) <= max_chars:
        return compact
    return f"{compact[: max_chars - 3].rstrip()}..."


def event_summary_snippet(event: RenderEvent) -> str:
    """Return a summary-friendly snippet for one render event."""
    label = {
        RenderEventKind.REASONING: "Reasoning",
        RenderEventKind.COMMAND: "Command",
        RenderEventKind.TOOL: "Tool",
        RenderEventKind.RESULT: "Result",
        RenderEventKind.ERROR: "Error",
    }[event.kind]
    return f"{label}: {normalize_render_text(event.text)}"


def render_event_line(event: RenderEvent) -> str:
    """Render a normalized terminal line for one event."""
    snippet = event_summary_snippet(event)
    return f"• {snippet}"

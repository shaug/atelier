"""Deterministic plain-text fallback adapter for worker session output."""

from __future__ import annotations

import re

from .output_contract import AdapterOutput, RenderEvent, RenderEventKind, normalize_render_text

_REASONING_PREFIX = re.compile(
    r"^(?:thinking|reasoning|analysis|analyzing|plan|planning|considering)\s*[:\-]\s*(.+)$",
    re.IGNORECASE,
)
_COMMAND_PREFIX = re.compile(r"^\$\s+(.+)$")
_COMMAND_VERB_PREFIX = re.compile(
    r"^(?:running|ran|executing|execute|command)\s*[:\-]\s*(.+)$",
    re.IGNORECASE,
)
_TOOL_PREFIX = re.compile(r"^(?:tool|mcp|api)\s*[:\-]\s*(.+)$", re.IGNORECASE)
_RESULT_PREFIX = re.compile(
    r"^(?:result|summary|done|completed|success)\s*[:\-]\s*(.+)$",
    re.IGNORECASE,
)
_ERROR_RE = re.compile(r"\b(error|failed|exception|traceback)\b", re.IGNORECASE)
_COMMAND_STARTS = (
    "git ",
    "bash ",
    "sh ",
    "python ",
    "uv ",
    "just ",
    "bd ",
    "gh ",
)


def adapt_plain_text_line(line: str, *, source: str) -> AdapterOutput | None:
    """Classify one plain-text output line into the render contract."""
    text = normalize_render_text(line)
    if not text:
        return None

    if _ERROR_RE.search(text):
        return _error_output(text)

    command_match = _COMMAND_PREFIX.match(text) or _COMMAND_VERB_PREFIX.match(text)
    if command_match:
        command = normalize_render_text(command_match.group(1))
        return AdapterOutput(
            consumed=True,
            structured=False,
            tool_event=True,
            events=(RenderEvent(RenderEventKind.COMMAND, command),),
        )

    lowered = text.lower()
    if lowered.startswith(_COMMAND_STARTS):
        return AdapterOutput(
            consumed=True,
            structured=False,
            tool_event=True,
            events=(RenderEvent(RenderEventKind.COMMAND, text),),
        )

    reasoning_match = _REASONING_PREFIX.match(text)
    if reasoning_match:
        return AdapterOutput(
            consumed=True,
            structured=False,
            tool_event=False,
            events=(RenderEvent(RenderEventKind.REASONING, reasoning_match.group(1).strip()),),
        )

    tool_match = _TOOL_PREFIX.match(text)
    if tool_match:
        return AdapterOutput(
            consumed=True,
            structured=False,
            tool_event=True,
            events=(RenderEvent(RenderEventKind.TOOL, tool_match.group(1).strip()),),
        )

    result_match = _RESULT_PREFIX.match(text)
    if result_match:
        result_text = result_match.group(1).strip() or text
        return AdapterOutput(
            consumed=True,
            structured=False,
            tool_event=False,
            events=(RenderEvent(RenderEventKind.RESULT, result_text),),
            preview=result_text,
        )

    return None


def _error_output(text: str) -> AdapterOutput:
    return AdapterOutput(
        consumed=True,
        structured=False,
        tool_event=False,
        events=(RenderEvent(RenderEventKind.ERROR, text),),
        diagnostic=text,
    )

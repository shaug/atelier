"""Structured capture and shared rendering for worker agent output."""

from __future__ import annotations

import re
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field

from ... import codex
from . import output_claude, output_codex, output_fallback
from .output_contract import (
    AdapterOutput,
    RenderEvent,
    RenderEventKind,
    event_summary_snippet,
    normalize_render_text,
    render_event_line,
)

_TRUTHY_VALUES = {"1", "true", "yes", "on"}
_DIFF_MARKERS = ("diff --git ", "@@ ", "+++ ", "--- ", "```diff")
_NOISE_PREFIXES = (
    "thinking",
    "assistant",
    "user",
    "codex",
    "openai codex",
    "tokens used",
    "mcp:",
)
_ERROR_LINE_RE = re.compile(r"\b(error|failed|exception|traceback)\b", re.IGNORECASE)
_MAX_SNIPPETS = 4
_MAX_TAIL = 24
_MAX_PREVIEW_CHARS = 280
_MAX_RENDER_EVENTS = 96


@dataclass
class AgentOutputCapture:
    """Capture output and emit normalized render events across agent adapters."""

    agent_name: str
    raw_line_count: int = 0
    suppressed_line_count: int = 0
    structured_event_count: int = 0
    tool_event_count: int = 0
    _tail: deque[str] = field(default_factory=lambda: deque(maxlen=_MAX_TAIL))
    _actionable: list[str] = field(default_factory=list)
    _diagnostics: list[str] = field(default_factory=list)
    _seen_lines: dict[str, int] = field(default_factory=dict)
    _assistant_preview: str = ""
    _assistant_char_count: int = 0
    _tool_activity_seq: int = 0
    _latest_tool_activity: str = ""
    _reasoning_activity_seq: int = 0
    _latest_reasoning_activity: str = ""
    _render_event_seq: int = 0
    _render_events: deque[tuple[int, RenderEvent]] = field(
        default_factory=lambda: deque(maxlen=_MAX_RENDER_EVENTS)
    )
    _last_render_text_by_kind: dict[RenderEventKind, str] = field(default_factory=dict)
    helper_session_id: str | None = None

    def feed_stdout_line(self, raw_line: str) -> None:
        """Consume one stdout line from the agent process."""
        self._feed_line(raw_line, source="stdout")

    def feed_stderr_line(self, raw_line: str) -> None:
        """Consume one stderr line from the agent process."""
        self._feed_line(raw_line, source="stderr")

    def feed_stdout_text(self, text: str) -> None:
        """Consume multi-line stdout text from a completed command result."""
        for line in text.splitlines():
            self.feed_stdout_line(line)

    def feed_stderr_text(self, text: str) -> None:
        """Consume multi-line stderr text from a completed command result."""
        for line in text.splitlines():
            self.feed_stderr_line(line)

    def render_summary_lines(self, *, failed: bool) -> list[str]:
        """Render deterministic output summary lines for worker thread logs."""
        label = self.agent_name.strip() or "agent"
        if self.structured_event_count > 0:
            return self._render_structured_summary(label=label, failed=failed)
        return self._render_text_summary(label=label, failed=failed)

    def assistant_preview_text(self, *, max_chars: int | None = None) -> str | None:
        """Return captured assistant preview text, optionally truncated."""
        preview = self._assistant_preview.strip()
        if not preview:
            return None
        if max_chars is None or max_chars <= 0:
            return preview
        if len(preview) <= max_chars:
            return preview
        if max_chars <= 3:
            return "." * max_chars
        clipped = preview[: max_chars - 3].rstrip()
        return f"{clipped}..."

    def latest_tool_activity(self) -> tuple[int, str] | None:
        """Return the most recently captured tool/command marker."""
        activity = self._latest_tool_activity.strip()
        if not activity:
            return None
        return self._tool_activity_seq, activity

    def latest_reasoning_activity(self) -> tuple[int, str] | None:
        """Return the most recently captured reasoning marker."""
        activity = self._latest_reasoning_activity.strip()
        if not activity:
            return None
        return self._reasoning_activity_seq, activity

    def render_events_since(self, *, after_seq: int = 0) -> tuple[int, tuple[RenderEvent, ...]]:
        """Return normalized render events after a given sequence cursor."""
        cursor = after_seq
        events: list[RenderEvent] = []
        for sequence, event in self._render_events:
            if sequence <= after_seq:
                continue
            cursor = sequence
            events.append(event)
        return cursor, tuple(events)

    def _feed_line(self, raw_line: str, *, source: str) -> None:
        line = _normalize_line(raw_line)
        if not line:
            return
        self.raw_line_count += 1
        self._tail.append(line)

        adapted = self._adapt_line(line, source=source)
        if adapted is not None:
            self._consume_adapter_output(adapted)
            if adapted.consumed:
                return

        seen_count = self._seen_lines.get(line, 0)
        self._seen_lines[line] = seen_count + 1
        if seen_count >= 2:
            self.suppressed_line_count += 1
            return
        if _is_noise_line(line):
            self.suppressed_line_count += 1
            return
        if _ERROR_LINE_RE.search(line):
            self._append_unique(self._diagnostics, line)
            return
        self._append_unique(self._actionable, line)

    def _adapt_line(self, line: str, *, source: str) -> AdapterOutput | None:
        label = self.agent_name.strip().lower()
        if label == "claude":
            adapted = output_claude.adapt_claude_line(line)
            if adapted is not None:
                return adapted
        if label == "codex":
            adapted = output_codex.adapt_codex_line(line)
            if adapted is not None:
                return adapted
        return output_fallback.adapt_plain_text_line(line, source=source)

    def _consume_adapter_output(self, adapted: AdapterOutput) -> None:
        if adapted.structured:
            self.structured_event_count += 1
        if adapted.tool_event:
            self.tool_event_count += 1
        if adapted.session_id and self.helper_session_id is None:
            self.helper_session_id = adapted.session_id
        if adapted.diagnostic:
            self._append_unique(self._diagnostics, adapted.diagnostic)
        if adapted.preview:
            self._assistant_char_count += len(adapted.preview)
            if len(self._assistant_preview) < _MAX_PREVIEW_CHARS:
                self._append_assistant_preview(adapted.preview)
        for event in adapted.events:
            self._record_render_event(event)

    def _record_render_event(self, event: RenderEvent) -> None:
        text = normalize_render_text(event.text)
        if not text:
            return
        if self._last_render_text_by_kind.get(event.kind) == text:
            return
        normalized_event = RenderEvent(kind=event.kind, text=text)
        self._last_render_text_by_kind[event.kind] = text
        self._render_event_seq += 1
        self._render_events.append((self._render_event_seq, normalized_event))

        if event.kind == RenderEventKind.REASONING:
            self._reasoning_activity_seq += 1
            self._latest_reasoning_activity = text
            self._append_unique(self._actionable, event_summary_snippet(normalized_event))
            return
        if event.kind == RenderEventKind.COMMAND:
            self._tool_activity_seq += 1
            self._latest_tool_activity = f"command: {text}"
            self._append_unique(self._actionable, event_summary_snippet(normalized_event))
            return
        if event.kind == RenderEventKind.TOOL:
            self._tool_activity_seq += 1
            self._latest_tool_activity = f"tool: {text}"
            self._append_unique(self._actionable, event_summary_snippet(normalized_event))
            return
        if event.kind == RenderEventKind.RESULT:
            self._append_unique(self._actionable, event_summary_snippet(normalized_event))
            return
        if event.kind == RenderEventKind.ERROR:
            self._append_unique(self._diagnostics, text)
            return

    def _append_assistant_preview(self, message: str) -> None:
        remaining = _MAX_PREVIEW_CHARS - len(self._assistant_preview)
        if remaining <= 0:
            return
        clipped = message[:remaining].strip()
        if not clipped:
            return
        if self._assistant_preview:
            self._assistant_preview = f"{self._assistant_preview} {clipped}".strip()
        else:
            self._assistant_preview = clipped

    def _append_unique(self, target: list[str], line: str) -> None:
        if line in target:
            return
        if len(target) >= _MAX_SNIPPETS:
            return
        target.append(line)

    def _render_structured_summary(self, *, label: str, failed: bool) -> list[str]:
        status = "failed" if failed else "completed"
        first_line = (
            f"Agent output ({label}): {status}; events={self.structured_event_count}; "
            f"tools={self.tool_event_count}; suppressed={self.suppressed_line_count}"
        )
        lines = [first_line]
        if self._assistant_preview:
            lines.append(f"- Assistant preview: {self._assistant_preview}")
        if failed:
            diagnostic = self._diagnostics[0] if self._diagnostics else self._tail_signal()
            if diagnostic:
                lines.append(f"- Diagnostic: {diagnostic}")
            lines.append("- Set ATELIER_WORK_AGENT_TRACE=1 for full raw output.")
        return lines

    def _render_text_summary(self, *, label: str, failed: bool) -> list[str]:
        status = "failed" if failed else "completed"
        lines = [
            (
                f"Agent output ({label}): {status}; meaningful={len(self._actionable)}; "
                f"suppressed={self.suppressed_line_count}"
            )
        ]
        snippets = self._diagnostics if failed and self._diagnostics else self._actionable
        if not snippets:
            tail = self._tail_signal()
            if tail:
                snippets = [tail]
        for snippet in snippets[:_MAX_SNIPPETS]:
            lines.append(f"- {snippet}")
        if failed:
            lines.append("- Set ATELIER_WORK_AGENT_TRACE=1 for full raw output.")
        return lines

    def _tail_signal(self) -> str | None:
        for line in reversed(self._tail):
            if _is_noise_line(line):
                continue
            return line
        return None


def trace_output_requested(env: Mapping[str, str] | None) -> bool:
    """Return whether the worker should stream full raw agent output."""
    if env is None:
        return False
    for key in ("ATELIER_WORK_AGENT_TRACE", "ATELIER_WORK_TRACE"):
        value = env.get(key, "").strip().lower()
        if value in _TRUTHY_VALUES:
            return True
    return False


def render_live_event(event: RenderEvent) -> str:
    """Render a normalized live-progress line for one adapter event."""
    return render_event_line(event)


def _normalize_line(raw_line: str) -> str:
    return codex.strip_ansi(raw_line).replace("\r", "").strip()


def _is_noise_line(line: str) -> bool:
    if not line:
        return True
    lowered = line.lower()
    if lowered.startswith(_NOISE_PREFIXES):
        return True
    if lowered.startswith(_DIFF_MARKERS):
        return True
    if set(lowered) <= {"-", "=", "*", "_"} and len(lowered) >= 4:
        return True
    return False

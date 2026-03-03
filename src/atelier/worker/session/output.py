"""Structured capture and concise rendering for worker agent output."""

from __future__ import annotations

import re
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field

from ... import codex
from . import output_claude, output_codex

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


@dataclass
class AgentOutputCapture:
    """Capture agent output and synthesize concise, deterministic summaries."""

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
        if label == "claude" and self.structured_event_count > 0:
            return self._render_structured_summary(label="claude", failed=failed)
        if label == "codex" and self.structured_event_count > 0:
            return self._render_structured_summary(label="codex", failed=failed)
        return self._render_text_summary(label=label, failed=failed)

    def _feed_line(self, raw_line: str, *, source: str) -> None:
        line = _normalize_line(raw_line)
        if not line:
            return
        self.raw_line_count += 1
        self._tail.append(line)
        if self.agent_name == "claude" and self._consume_claude_event(line):
            return
        if self.agent_name == "codex" and self._consume_codex_event(line):
            return
        seen_count = self._seen_lines.get(line, 0)
        self._seen_lines[line] = seen_count + 1
        if seen_count >= 2:
            self.suppressed_line_count += 1
            return
        if _is_noise_line(line):
            self.suppressed_line_count += 1
            return
        if source == "stderr" or _ERROR_LINE_RE.search(line):
            self._append_unique(self._diagnostics, line)
            return
        self._append_unique(self._actionable, line)

    def _consume_claude_event(self, line: str) -> bool:
        """Parse and consume a Claude JSON event; return True if consumed."""
        event = output_claude.parse_claude_event(line)
        if event is None:
            return False
        self.structured_event_count += 1
        if output_claude.is_tool_event(event):
            self.tool_event_count += 1
        err_msg = output_claude.extract_error_message(event)
        if err_msg:
            self._append_unique(self._diagnostics, err_msg)
        preview = output_claude.extract_preview_text(event)
        if preview:
            self._assistant_char_count += len(preview)
            if len(self._assistant_preview) < _MAX_PREVIEW_CHARS:
                self._append_assistant_preview(preview)
        return True

    def _consume_codex_event(self, line: str) -> bool:
        """Parse and consume a Codex JSON event; return True if consumed."""
        event = output_codex.parse_codex_event(line)
        if event is None:
            return False
        self.structured_event_count += 1
        if output_codex.is_tool_event(event):
            self.tool_event_count += 1
        err_msg = output_codex.extract_error_message(event)
        if err_msg:
            self._append_unique(self._diagnostics, err_msg)
        preview = output_codex.extract_preview_text(event)
        if preview:
            self._assistant_char_count += len(preview)
            if len(self._assistant_preview) < _MAX_PREVIEW_CHARS:
                self._append_assistant_preview(preview)
        return True

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

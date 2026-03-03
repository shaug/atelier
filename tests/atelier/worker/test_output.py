"""Tests for worker session output capture and agent event parsing."""

from __future__ import annotations

from atelier.worker.session import output_claude, output_codex
from atelier.worker.session.output import (
    AgentOutputCapture,
    trace_output_requested,
)

# ---------------------------------------------------------------------------
# _parse_claude_event
# ---------------------------------------------------------------------------


def test_parse_claude_event_valid_json_returns_event() -> None:
    """Valid JSON with type parses to ClaudeEvent."""
    event = output_claude.parse_claude_event('{"type":"assistant","message":{"content":[]}}')
    assert event is not None
    assert event.type == "assistant"
    assert event.message is not None
    assert event.message.get("content") == []


def test_parse_claude_event_preserves_extra_fields() -> None:
    """Extra fields are preserved via model_config extra=allow."""
    event = output_claude.parse_claude_event(
        '{"type":"system","subtype":"init","session_id":"abc-123"}'
    )
    assert event is not None
    assert event.type == "system"
    assert event.subtype == "init"


def test_parse_claude_event_invalid_json_returns_none() -> None:
    """Non-JSON or missing type returns None."""
    assert output_claude.parse_claude_event("") is None
    assert output_claude.parse_claude_event("not json") is None
    assert output_claude.parse_claude_event("{}") is None
    assert output_claude.parse_claude_event('{"other":"field"}') is None


def test_parse_claude_event_non_object_returns_none() -> None:
    """Array or primitive JSON returns None."""
    assert output_claude.parse_claude_event("[]") is None
    assert output_claude.parse_claude_event("null") is None
    assert output_claude.parse_claude_event('"string"') is None


def test_parse_claude_event_whitespace_only_before_brace_returns_none() -> None:
    """Line must start with { to be considered JSON."""
    assert output_claude.parse_claude_event("  \n  ") is None


# ---------------------------------------------------------------------------
# _extract_preview_text
# ---------------------------------------------------------------------------


def test_extract_preview_text_stream_delta() -> None:
    """Stream format content_block_delta extracts delta.text."""
    event = output_claude.ClaudeEvent(type="content_block_delta", delta={"text": "Hello world"})
    assert output_claude.extract_preview_text(event) == "Hello world"


def test_extract_preview_text_stream_delta_empty_returns_none() -> None:
    """Empty or whitespace delta.text returns None."""
    event = output_claude.ClaudeEvent(type="content_block_delta", delta={"text": "   "})
    assert output_claude.extract_preview_text(event) is None


def test_extract_preview_text_assistant_text_block() -> None:
    """Session format assistant message with text block."""
    event = output_claude.ClaudeEvent(
        type="assistant",
        message={"content": [{"type": "text", "text": "Summary of work done."}]},
    )
    assert output_claude.extract_preview_text(event) == "Summary of work done."


def test_extract_preview_text_assistant_tool_result_block() -> None:
    """Session format user message with tool_result content."""
    event = output_claude.ClaudeEvent(
        type="user",
        message={"content": [{"type": "tool_result", "content": "Command output here."}]},
    )
    assert output_claude.extract_preview_text(event) == "Command output here."


def test_extract_preview_text_skips_thinking_block() -> None:
    """Thinking blocks are excluded from preview."""
    event = output_claude.ClaudeEvent(
        type="assistant",
        message={
            "content": [
                {"type": "thinking", "thinking": "Internal reasoning..."},
                {"type": "text", "text": "User-facing text."},
            ]
        },
    )
    assert output_claude.extract_preview_text(event) == "User-facing text."


def test_extract_preview_text_result_event() -> None:
    """Result event uses result field."""
    event = output_claude.ClaudeEvent(type="result", result="Session completed successfully.")
    assert output_claude.extract_preview_text(event) == "Session completed successfully."


def test_extract_preview_text_error_event_uses_error_message() -> None:
    """Error event uses error.message when present."""
    event = output_claude.ClaudeEvent(
        type="error",
        error={"message": "API rate limit exceeded"},
    )
    assert output_claude.extract_preview_text(event) == "API rate limit exceeded"


def test_extract_preview_text_unknown_type_returns_none() -> None:
    """Unknown event types return None."""
    event = output_claude.ClaudeEvent(type="rate_limit_event", message=None)
    assert output_claude.extract_preview_text(event) is None


# ---------------------------------------------------------------------------
# _is_tool_event
# ---------------------------------------------------------------------------


def test_is_tool_event_detects_tool_use_type() -> None:
    """Tool events are detected from type."""
    assert (
        output_claude.is_tool_event(output_claude.ClaudeEvent(type="tool_use", message=None))
        is True
    )
    assert (
        output_claude.is_tool_event(
            output_claude.ClaudeEvent(type="tool_use_block_start", message=None)
        )
        is True
    )
    assert (
        output_claude.is_tool_event(output_claude.ClaudeEvent(type="tool_call", message=None))
        is True
    )


def test_is_tool_event_detects_tool_use_in_content() -> None:
    """Session format: tool_use block in message.content."""
    assert (
        output_claude.is_tool_event(
            output_claude.ClaudeEvent(
                type="assistant",
                message={"content": [{"type": "tool_use", "name": "Bash"}]},
            )
        )
        is True
    )


def test_is_tool_event_non_tool_returns_false() -> None:
    """Non-tool events return False."""
    assert (
        output_claude.is_tool_event(output_claude.ClaudeEvent(type="assistant", message=None))
        is False
    )
    assert (
        output_claude.is_tool_event(output_claude.ClaudeEvent(type="user", message=None)) is False
    )
    assert (
        output_claude.is_tool_event(output_claude.ClaudeEvent(type="system", message=None)) is False
    )


# ---------------------------------------------------------------------------
# _is_error_event
# ---------------------------------------------------------------------------


def test_is_error_event_detects_error_type() -> None:
    """Error events are detected from type."""
    assert (
        output_claude.is_error_event(output_claude.ClaudeEvent(type="error", message=None)) is True
    )
    assert (
        output_claude.is_error_event(
            output_claude.ClaudeEvent(type="error_event", error={"message": "x"})
        )
        is True
    )


def test_is_error_event_detects_error_field() -> None:
    """Event with error field is treated as error."""
    assert (
        output_claude.is_error_event(
            output_claude.ClaudeEvent(type="message", error={"message": "x"})
        )
        is True
    )


def test_is_error_event_non_error_returns_false() -> None:
    """Non-error events return False."""
    assert (
        output_claude.is_error_event(output_claude.ClaudeEvent(type="assistant", message=None))
        is False
    )


# ---------------------------------------------------------------------------
# _extract_error_message
# ---------------------------------------------------------------------------


def test_extract_error_message_from_error_field() -> None:
    """Error message extracted from error.message."""
    event = output_claude.ClaudeEvent(type="error", error={"message": "tool call failed"})
    assert output_claude.extract_error_message(event) == "tool call failed"


def test_extract_error_message_no_error_returns_none() -> None:
    """Event without error returns None."""
    event = output_claude.ClaudeEvent(type="assistant", message=None)
    assert output_claude.extract_error_message(event) is None


# ---------------------------------------------------------------------------
# AgentOutputCapture
# ---------------------------------------------------------------------------


def test_agent_output_capture_feed_stream_json_counts_events() -> None:
    """Feed stream-json lines and verify event counts."""
    capture = AgentOutputCapture(agent_name="claude")
    capture.feed_stdout_line('{"type":"content_block_delta","delta":{"text":"Hi"}}')
    capture.feed_stdout_line('{"type":"tool_use","name":"Bash","input":{}}')
    capture.feed_stdout_line('{"type":"tool_use","name":"Read","input":{}}')
    assert capture.structured_event_count == 3
    assert capture.tool_event_count == 2


def test_agent_output_capture_feed_stdout_text() -> None:
    """feed_stdout_text processes each line."""
    capture = AgentOutputCapture(agent_name="claude")
    capture.feed_stdout_text(
        '{"type":"assistant","message":{"content":[{"type":"text","text":"Done"}]}}\n'
    )
    assert capture.structured_event_count == 1
    summary = capture.render_summary_lines(failed=False)
    assert any("Assistant preview: Done" in line for line in summary)


def test_agent_output_capture_assistant_preview_text_truncates() -> None:
    """assistant_preview_text clips preview text when max_chars is set."""
    capture = AgentOutputCapture(agent_name="codex")
    capture.feed_stdout_line(
        '{"type":"item.completed","item":{"type":"agent_message","text":"'
        'This is a long assistant message preview for clipping behavior."}}'
    )
    preview = capture.assistant_preview_text(max_chars=24)
    assert preview == "This is a long assist..."


def test_agent_output_capture_error_event_adds_diagnostic() -> None:
    """Error events add to diagnostics."""
    capture = AgentOutputCapture(agent_name="claude")
    capture.feed_stdout_line('{"type":"error","error":{"message":"tool call failed"}}')
    summary = capture.render_summary_lines(failed=True)
    assert any("Diagnostic: tool call failed" in line for line in summary)


def test_agent_output_capture_non_claude_uses_text_summary() -> None:
    """Non-Claude agents use text summary path."""
    capture = AgentOutputCapture(agent_name="codex")
    capture.feed_stdout_line("Some plain output")
    capture.feed_stdout_line("Another line")
    summary = capture.render_summary_lines(failed=False)
    assert "Agent output (codex):" in summary[0]
    assert "meaningful=" in summary[0]


def test_agent_output_capture_example_session_fixture(
    claude_session_fixture_content: str,
) -> None:
    """Feed example session fixture; verify parse and summary."""
    capture = AgentOutputCapture(agent_name="claude")
    capture.feed_stdout_text(claude_session_fixture_content)
    assert capture.structured_event_count > 0
    assert capture.tool_event_count > 0
    summary = capture.render_summary_lines(failed=False)
    assert len(summary) >= 1
    assert "Agent output (claude):" in summary[0]
    assert "events=" in summary[0]
    assert "tools=" in summary[0]
    assert any("Assistant preview:" in line for line in summary)


# ---------------------------------------------------------------------------
# trace_output_requested
# ---------------------------------------------------------------------------


def test_trace_output_requested() -> None:
    """trace_output_requested checks env vars."""
    assert trace_output_requested(None) is False
    assert trace_output_requested({}) is False
    assert trace_output_requested({"ATELIER_WORK_AGENT_TRACE": "1"}) is True
    assert trace_output_requested({"ATELIER_WORK_TRACE": "true"}) is True
    assert trace_output_requested({"ATELIER_WORK_AGENT_TRACE": "0"}) is False
    assert trace_output_requested({"ATELIER_WORK_TRACE": "yes"}) is True


# ---------------------------------------------------------------------------
# Codex event parsing (codex exec --json)
# ---------------------------------------------------------------------------


def test_parse_codex_event_valid_json_returns_event() -> None:
    """Valid Codex JSON with type parses to CodexEvent."""
    event = output_codex.parse_codex_event(
        '{"type":"item.completed","item":{"id":"item_3","type":"agent_message",'
        '"text":"Repo contains docs."}}'
    )
    assert event is not None
    assert event.type == "item.completed"
    assert event.item is not None
    assert event.item.get("type") == "agent_message"
    assert event.item.get("text") == "Repo contains docs."


def test_parse_codex_event_thread_started() -> None:
    """thread.started event parses with thread_id."""
    event = output_codex.parse_codex_event(
        '{"type":"thread.started","thread_id":"0199a213-81c0-7800-8aa1-bbab2a035a53"}'
    )
    assert event is not None
    assert event.type == "thread.started"
    assert event.thread_id == "0199a213-81c0-7800-8aa1-bbab2a035a53"


def test_parse_codex_event_invalid_returns_none() -> None:
    """Non-JSON or missing type returns None."""
    assert output_codex.parse_codex_event("") is None
    assert output_codex.parse_codex_event("plain text") is None
    assert output_codex.parse_codex_event("{}") is None


def test_extract_codex_preview_text_agent_message() -> None:
    """item.completed with agent_message extracts text."""
    event = output_codex.CodexEvent(
        type="item.completed",
        item={"type": "agent_message", "text": "Repo contains docs, sdk."},
    )
    assert output_codex.extract_preview_text(event) == "Repo contains docs, sdk."


def test_extract_codex_preview_text_reasoning() -> None:
    """item.completed with reasoning extracts text."""
    event = output_codex.CodexEvent(
        type="item.completed",
        item={"type": "reasoning", "text": "Analyzing structure..."},
    )
    assert output_codex.extract_preview_text(event) == "Analyzing structure..."


def test_extract_codex_preview_text_command_execution_returns_none() -> None:
    """command_execution items have no text for preview."""
    event = output_codex.CodexEvent(
        type="item.completed",
        item={"type": "command_execution", "status": "completed"},
    )
    assert output_codex.extract_preview_text(event) is None


def test_is_codex_tool_event_detects_command_execution() -> None:
    """command_execution items are tool events."""
    event = output_codex.CodexEvent(
        type="item.completed",
        item={"type": "command_execution", "command": "bash -lc ls"},
    )
    assert output_codex.is_tool_event(event) is True


def test_is_codex_tool_event_agent_message_returns_false() -> None:
    """agent_message is not a tool event."""
    event = output_codex.CodexEvent(
        type="item.completed",
        item={"type": "agent_message", "text": "Done"},
    )
    assert output_codex.is_tool_event(event) is False


def test_is_codex_error_event_detects_error_type() -> None:
    """error and turn.failed are error events."""
    assert output_codex.is_error_event(output_codex.CodexEvent(type="error", error={})) is True
    assert output_codex.is_error_event(output_codex.CodexEvent(type="turn.failed")) is True


def test_extract_codex_error_message_from_error_field() -> None:
    """Error message extracted from error.message."""
    event = output_codex.CodexEvent(type="error", error={"message": "API rate limit exceeded"})
    assert output_codex.extract_error_message(event) == "API rate limit exceeded"


def test_extract_codex_tool_activity_command_execution() -> None:
    """Command execution tool events include a compact command label."""
    event = output_codex.CodexEvent(
        type="item.completed",
        item={"type": "command_execution", "command": "bash -lc ls -la"},
    )
    assert output_codex.extract_tool_activity(event) == "command: bash -lc ls -la"


def test_extract_codex_tool_activity_mcp_tool_call() -> None:
    """MCP tool call events include server/tool identity."""
    event = output_codex.CodexEvent(
        type="item.started",
        item={"type": "mcp_tool_call", "server": "linear", "name": "list_issues"},
    )
    assert output_codex.extract_tool_activity(event) == "tool: linear/list_issues"


def test_extract_codex_reasoning_activity_reasoning_item() -> None:
    """Reasoning events expose concise reasoning activity text."""
    event = output_codex.CodexEvent(
        type="item.completed",
        item={"type": "reasoning", "text": "Planning update strategy"},
    )
    assert output_codex.extract_reasoning_activity(event) == "Planning update strategy"


def test_agent_output_capture_codex_json_counts_events() -> None:
    """Feed Codex JSON lines; verify event and tool counts."""
    capture = AgentOutputCapture(agent_name="codex")
    capture.feed_stdout_line('{"type":"item.completed","item":{"type":"command_execution"}}')
    capture.feed_stdout_line(
        '{"type":"item.completed","item":{"type":"agent_message","text":"Done"}}'
    )
    assert capture.structured_event_count == 2
    assert capture.tool_event_count == 1
    summary = capture.render_summary_lines(failed=False)
    assert "Agent output (codex):" in summary[0]
    assert "events=2" in summary[0]
    assert any("Assistant preview: Done" in line for line in summary)


def test_agent_output_capture_codex_mixed_json_text_interleaving_is_deterministic() -> None:
    """Mixed plain-text and JSON lines stay deterministic."""
    capture = AgentOutputCapture(agent_name="codex")
    capture.feed_stdout_line("status: bootstrapping workspace")
    capture.feed_stdout_line('{"type":"thread.started","thread_id":"thread_1"}')
    capture.feed_stdout_line('{"type":"schema.evolved","meta":{"version":2}}')
    capture.feed_stdout_line(
        '{"type":"item.completed","item":{"type":"command_execution","command":"bash -lc ls"}}'
    )
    capture.feed_stdout_line("assistant: hidden protocol noise")
    capture.feed_stdout_line(
        '{"type":"item.completed","item":{"type":"agent_message","text":"Done"}}'
    )

    assert capture.raw_line_count == 6
    assert capture.structured_event_count == 4
    assert capture.tool_event_count == 1
    assert capture.suppressed_line_count == 1

    summary = capture.render_summary_lines(failed=False)
    assert "Agent output (codex): completed" in summary[0]
    assert "events=4" in summary[0]
    assert "tools=1" in summary[0]
    assert "suppressed=1" in summary[0]
    assert "meaningful=" not in summary[0]
    assert any("Assistant preview: Done" in line for line in summary)


def test_agent_output_capture_codex_latest_reasoning_activity_dedupes_repeats() -> None:
    """Repeated identical reasoning events should not create new markers."""
    capture = AgentOutputCapture(agent_name="codex")
    capture.feed_stdout_line(
        '{"type":"item.completed","item":{"type":"reasoning","text":"Inspecting files"}}'
    )
    first = capture.latest_reasoning_activity()
    assert first is not None
    capture.feed_stdout_line(
        '{"type":"item.completed","item":{"type":"reasoning","text":"Inspecting files"}}'
    )
    second = capture.latest_reasoning_activity()
    assert second == first


def test_agent_output_capture_codex_latest_tool_activity_dedupes_repeats() -> None:
    """Repeated identical tool events should not create new activity markers."""
    capture = AgentOutputCapture(agent_name="codex")
    capture.feed_stdout_line(
        '{"type":"item.completed","item":{"type":"command_execution","command":"bash -lc ls"}}'
    )
    first = capture.latest_tool_activity()
    assert first is not None
    capture.feed_stdout_line(
        '{"type":"item.completed","item":{"type":"command_execution","command":"bash -lc ls"}}'
    )
    second = capture.latest_tool_activity()
    assert second == first


def test_agent_output_capture_codex_fixture(
    codex_session_fixture_content: str,
) -> None:
    """Feed example Codex fixture; verify parse and summary."""
    capture = AgentOutputCapture(agent_name="codex")
    capture.feed_stdout_text(codex_session_fixture_content)
    assert capture.structured_event_count > 0
    assert capture.tool_event_count > 0
    summary = capture.render_summary_lines(failed=False)
    assert "Agent output (codex):" in summary[0]
    assert "events=" in summary[0]
    assert "tools=" in summary[0]
    assert any("Assistant preview:" in line for line in summary)

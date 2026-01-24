import atelier.codex as codex


def test_parse_codex_resume_line_extracts_command_and_id() -> None:
    session_id, resume_command = codex.parse_codex_resume_line(
        "To resume this session, run: codex resume sess-123"
    )
    assert session_id == "sess-123"
    assert resume_command == "codex resume sess-123"


def test_parse_codex_resume_line_handles_session_id_label() -> None:
    session_id, resume_command = codex.parse_codex_resume_line("Session ID: sess-456")
    assert session_id == "sess-456"
    assert resume_command is None


def test_extract_session_id_from_command_with_flags() -> None:
    session_id = codex.extract_session_id_from_command(
        "codex resume --profile fast sess-789"
    )
    assert session_id == "sess-789"


def test_parse_codex_resume_line_strips_ansi() -> None:
    line = "\x1b[32mResume with: codex resume sess-999\x1b[0m"
    session_id, resume_command = codex.parse_codex_resume_line(line)
    assert session_id == "sess-999"
    assert resume_command == "codex resume sess-999"

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
    session_id = codex.extract_session_id_from_command("codex resume --profile fast sess-789")
    assert session_id == "sess-789"


def test_parse_codex_resume_line_strips_ansi() -> None:
    line = "\x1b[32mResume with: codex resume sess-999\x1b[0m"
    session_id, resume_command = codex.parse_codex_resume_line(line)
    assert session_id == "sess-999"
    assert resume_command == "codex resume sess-999"


def test_run_codex_command_disables_stdin_passthrough_when_not_streaming(monkeypatch) -> None:
    seen: dict[str, bool] = {}

    def _run_pty_command(
        cmd: list[str],
        *,
        cwd,
        capture,
        env,
        stream_output: bool,
        passthrough_stdin: bool,
    ) -> int:
        del cmd, cwd, capture, env
        seen["stream_output"] = stream_output
        seen["passthrough_stdin"] = passthrough_stdin
        return 0

    monkeypatch.setattr(codex.shutil, "which", lambda _cmd: "/usr/bin/codex")
    monkeypatch.setattr(codex, "_run_pty_command", _run_pty_command)

    result = codex.run_codex_command(["codex", "exec", "hello"], stream_output=False)

    assert result is not None
    assert seen["stream_output"] is False
    assert seen["passthrough_stdin"] is False


def test_run_codex_command_enables_stdin_passthrough_when_streaming(monkeypatch) -> None:
    seen: dict[str, bool] = {}

    def _run_pty_command(
        cmd: list[str],
        *,
        cwd,
        capture,
        env,
        stream_output: bool,
        passthrough_stdin: bool,
    ) -> int:
        del cmd, cwd, capture, env
        seen["stream_output"] = stream_output
        seen["passthrough_stdin"] = passthrough_stdin
        return 0

    monkeypatch.setattr(codex.shutil, "which", lambda _cmd: "/usr/bin/codex")
    monkeypatch.setattr(codex, "_run_pty_command", _run_pty_command)

    result = codex.run_codex_command(["codex", "exec", "hello"], stream_output=True)

    assert result is not None
    assert seen["stream_output"] is True
    assert seen["passthrough_stdin"] is True

"""Codex-specific helpers for session capture via PTY."""

from __future__ import annotations

import fcntl
import os
import pty
import re
import select
import shlex
import shutil
import signal
import struct
import sys
import termios
import tty
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .io import die

_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_SESSION_ID_RE = re.compile(r"session\s*id\s*[:=]\s*([A-Za-z0-9._-]+)", re.IGNORECASE)
_RESUME_COMMAND_RE = re.compile(r"(codex\s+resume\s+\S+)", re.IGNORECASE)
_SESSION_TOKEN_RE = re.compile(r"^[A-Za-z0-9._-]{4,}$")


@dataclass(frozen=True)
class CodexRunResult:
    """Captured Codex run results."""

    returncode: int
    session_id: str | None
    resume_command: str | None


def strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text."""
    return _ANSI_ESCAPE_RE.sub("", text)


def _clean_token(token: str) -> str:
    return token.strip().strip(").,;:\"'`")


def _looks_like_session_id(token: str) -> bool:
    if not _SESSION_TOKEN_RE.match(token):
        return False
    if any(char.isdigit() for char in token):
        return True
    return "-" in token or "_" in token


def extract_session_id_from_command(command: str) -> str | None:
    """Extract a session ID from a resume command."""
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()
    tokens = [token for token in tokens if token]
    for index, token in enumerate(tokens):
        if token.lower() != "resume":
            continue
        candidates = [
            _clean_token(item)
            for item in tokens[index + 1 :]
            if item and not item.startswith("-")
        ]
        for candidate in candidates:
            if _looks_like_session_id(candidate):
                return candidate
        if candidates:
            return candidates[0]
        return None
    return None


def parse_codex_resume_line(line: str) -> tuple[str | None, str | None]:
    """Parse a resume line for session metadata."""
    cleaned = strip_ansi(line).strip()
    if not cleaned:
        return None, None
    session_id: str | None = None
    resume_command: str | None = None
    match = _RESUME_COMMAND_RE.search(cleaned)
    if match:
        resume_command = match.group(1).strip().rstrip(").,;:")
        session_id = extract_session_id_from_command(resume_command)
        if session_id:
            return session_id, resume_command
    match = _SESSION_ID_RE.search(cleaned)
    if match:
        session_id = _clean_token(match.group(1))
    return session_id, resume_command


class CodexSessionCapture:
    """Capture Codex session metadata from streamed output."""

    def __init__(self) -> None:
        self.session_id: str | None = None
        self.resume_command: str | None = None
        self._buffer: str = ""

    def feed(self, data: bytes) -> None:
        if not data:
            return
        text = data.decode("utf-8", errors="ignore")
        if not text:
            return
        text = text.replace("\r", "\n")
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self._handle_line(line)

    def finalize(self) -> None:
        if self._buffer:
            self._handle_line(self._buffer)
            self._buffer = ""

    def _handle_line(self, line: str) -> None:
        session_id, resume_command = parse_codex_resume_line(line)
        if resume_command:
            self.resume_command = resume_command
        if session_id:
            self.session_id = session_id


def run_codex_command(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    allow_missing: bool = False,
    env: Mapping[str, str] | None = None,
) -> CodexRunResult | None:
    """Run Codex with a PTY and capture session metadata."""
    if shutil.which(cmd[0]) is None:
        if allow_missing:
            return None
        die(f"missing required command: {cmd[0]}")
    capture = CodexSessionCapture()
    returncode = _run_pty_command(cmd, cwd=cwd, capture=capture, env=env)
    capture.finalize()
    return CodexRunResult(
        returncode=returncode,
        session_id=capture.session_id,
        resume_command=capture.resume_command,
    )


def _run_pty_command(
    cmd: list[str],
    *,
    cwd: Path | None,
    capture: CodexSessionCapture,
    env: Mapping[str, str] | None,
) -> int:
    pid, master_fd = pty.fork()
    if pid == 0:
        if cwd is not None:
            os.chdir(cwd)
        if env is None:
            os.execvp(cmd[0], cmd)
        os.execvpe(cmd[0], cmd, dict(env))
        os._exit(1)
    _apply_winsize(master_fd, pid)
    previous_winch = signal.getsignal(signal.SIGWINCH)
    signal.signal(signal.SIGWINCH, lambda signum, frame: _apply_winsize(master_fd, pid))
    try:
        mode = termios.tcgetattr(sys.stdin.fileno())
        tty.setraw(sys.stdin.fileno())
        restore = True
    except termios.error:
        restore = False
        mode = None
    try:
        _copy_with_capture(master_fd, capture)
    finally:
        if restore and mode is not None:
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSAFLUSH, mode)
        signal.signal(signal.SIGWINCH, previous_winch)
    os.close(master_fd)
    _, status = os.waitpid(pid, 0)
    return os.waitstatus_to_exitcode(status)


def _copy_with_capture(master_fd: int, capture: CodexSessionCapture) -> None:
    if os.get_blocking(master_fd):
        os.set_blocking(master_fd, False)
        try:
            _copy_with_capture(master_fd, capture)
        finally:
            os.set_blocking(master_fd, True)
        return
    high_waterlevel = 4096
    stdin_avail = master_fd != 0
    stdout_avail = master_fd != 1
    i_buf = b""
    o_buf = b""
    while True:
        rfds: list[int] = []
        wfds: list[int] = []
        if stdin_avail and len(i_buf) < high_waterlevel:
            rfds.append(0)
        if stdout_avail and len(o_buf) < high_waterlevel:
            rfds.append(master_fd)
        if stdout_avail and o_buf:
            wfds.append(1)
        if i_buf:
            wfds.append(master_fd)
        if not rfds and not wfds:
            return
        rfds, wfds, _ = select.select(rfds, wfds, [])
        if 1 in wfds:
            try:
                written = os.write(1, o_buf)
                o_buf = o_buf[written:]
            except OSError:
                stdout_avail = False
        if master_fd in rfds:
            try:
                data = os.read(master_fd, 1024)
            except OSError:
                data = b""
            if not data:
                return
            capture.feed(data)
            o_buf += data
        if master_fd in wfds and i_buf:
            written = os.write(master_fd, i_buf)
            i_buf = i_buf[written:]
        if stdin_avail and 0 in rfds:
            data = os.read(0, 1024)
            if not data:
                stdin_avail = False
            else:
                i_buf += data


def _read_winsize() -> tuple[int, int, int, int] | None:
    if sys.stdin.isatty():
        return _winsize_from_fd(sys.stdin.fileno())
    if sys.stdout.isatty():
        return _winsize_from_fd(sys.stdout.fileno())
    return _winsize_from_env()


def _winsize_from_fd(fd: int) -> tuple[int, int, int, int] | None:
    try:
        packed = fcntl.ioctl(fd, termios.TIOCGWINSZ, struct.pack("HHHH", 0, 0, 0, 0))
    except OSError:
        return _winsize_from_env()
    rows, cols, xpix, ypix = struct.unpack("HHHH", packed)
    if rows <= 0 or cols <= 0:
        return _winsize_from_env()
    return rows, cols, xpix, ypix


def _winsize_from_env() -> tuple[int, int, int, int] | None:
    try:
        rows = int(os.environ.get("LINES", "0"))
        cols = int(os.environ.get("COLUMNS", "0"))
    except ValueError:
        return None
    if rows <= 0 or cols <= 0:
        return None
    return rows, cols, 0, 0


def _apply_winsize(master_fd: int, pid: int) -> None:
    winsize = _read_winsize()
    if winsize is None:
        return
    try:
        fcntl.ioctl(master_fd, termios.TIOCSWINSZ, struct.pack("HHHH", *winsize))
    except OSError:
        return
    try:
        os.kill(pid, signal.SIGWINCH)
    except OSError:
        return

"""Pytest fixtures for worker tests."""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def claude_session_fixture_path() -> Path:
    """Path to the example Claude session JSONL fixture."""
    return FIXTURES_DIR / "example_claude_session.jsonl"


@pytest.fixture
def claude_session_fixture_content(claude_session_fixture_path: Path) -> str:
    """Raw content of the example Claude session (stdout as from agent run)."""
    if not claude_session_fixture_path.exists():
        pytest.skip("example_claude_session.jsonl fixture not present")
    return claude_session_fixture_path.read_text(encoding="utf-8")


@pytest.fixture
def codex_session_fixture_path() -> Path:
    """Path to the example Codex session JSONL fixture."""
    return FIXTURES_DIR / "example_codex_session.jsonl"


@pytest.fixture
def codex_session_fixture_content(codex_session_fixture_path: Path) -> str:
    """Raw content of the example Codex session (stdout from codex exec --json)."""
    if not codex_session_fixture_path.exists():
        pytest.skip("example_codex_session.jsonl fixture not present")
    return codex_session_fixture_path.read_text(encoding="utf-8")

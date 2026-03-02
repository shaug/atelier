"""Tests for user-facing I/O helpers."""

from __future__ import annotations

import pytest

from atelier import io


def test_die_preserves_exit_code_and_message() -> None:
    with pytest.raises(SystemExit) as excinfo:
        io.die("boom", code=7)
    assert excinfo.value.code == 7
    assert str(excinfo.value) == "boom"

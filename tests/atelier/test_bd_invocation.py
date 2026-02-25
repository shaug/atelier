from __future__ import annotations

from atelier.bd_invocation import with_bd_mode


def test_with_bd_mode_returns_direct_command() -> None:
    command = with_bd_mode("list", "--json", beads_dir=None, env={})

    assert command == ["bd", "list", "--json"]


def test_with_bd_mode_preserves_arguments() -> None:
    command = with_bd_mode("show", "at-1", beads_dir=None, env={})

    assert command == ["bd", "show", "at-1"]

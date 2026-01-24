import os
from unittest.mock import patch

from atelier import term


def test_workspace_title_prefers_repo_and_branch() -> None:
    title = term.workspace_title("/tmp/atelier", "feat/demo")
    assert title == "atelier:feat/demo"


def test_workspace_title_falls_back_to_branch() -> None:
    title = term.workspace_title("", "feat/demo")
    assert title == "feat/demo"


def test_resolve_terminal_adapter_prefers_wezterm() -> None:
    with patch.dict(
        os.environ,
        {"WEZTERM_PANE_ID": "1", "KITTY_WINDOW_ID": "2", "TMUX": "1"},
        clear=True,
    ):
        adapter = term.resolve_terminal_adapter()
        assert adapter.name == "wezterm"


def test_resolve_terminal_adapter_kitty_when_available() -> None:
    with patch.dict(os.environ, {"KITTY_WINDOW_ID": "2"}, clear=True):
        adapter = term.resolve_terminal_adapter()
        assert adapter.name == "kitty"


def test_resolve_terminal_adapter_tmux_when_available() -> None:
    with patch.dict(os.environ, {"TMUX": "1"}, clear=True):
        adapter = term.resolve_terminal_adapter()
        assert adapter.name == "tmux"


def test_resolve_terminal_adapter_noop_when_missing() -> None:
    with patch.dict(os.environ, {}, clear=True):
        adapter = term.resolve_terminal_adapter()
        assert adapter.name == "noop"

"""tmux terminal adapter."""

from __future__ import annotations

from .. import exec as exec_util
from .base import TerminalAdapter


class TmuxAdapter(TerminalAdapter):
    """Best-effort tmux adapter for the active pane."""

    name = "tmux"

    def set_pane_title(self, title: str) -> bool:
        result = exec_util.try_run_command(["tmux", "select-pane", "-T", title])
        if result and result.returncode == 0:
            return True
        fallback = exec_util.try_run_command(["tmux", "rename-window", title])
        return bool(fallback and fallback.returncode == 0)

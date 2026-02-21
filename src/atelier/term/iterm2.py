"""iTerm2 terminal adapter."""

from __future__ import annotations

import sys
from typing import Mapping

from .base import TerminalAdapter, WorkspaceState, format_workspace_title


class Iterm2Adapter(TerminalAdapter):
    """Adapter for iTerm2 panes and tabs."""

    name = "iterm2"

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Iterm2Adapter | None:
        if env.get("TERM_PROGRAM") != "iTerm.app":
            return None
        return cls()

    def _write_osc(self, code: int, title: str) -> bool:
        if not sys.stdout.isatty():
            return False
        safe = title.replace("\033", "").replace("\007", "").replace("\n", " ").replace("\r", " ")
        try:
            sys.stdout.write(f"\033]{code};{safe}\007")
            sys.stdout.flush()
        except Exception:
            return False
        return True

    def set_pane_title(self, title: str) -> bool:
        return self._write_osc(1, title)

    def set_window_title(self, title: str) -> bool:
        return self._write_osc(2, title)

    def set_workspace_state(self, state: WorkspaceState) -> bool:
        title = format_workspace_title(state)
        pane_ok = self.set_pane_title(title)
        window_ok = self.set_window_title(title)
        return pane_ok or window_ok

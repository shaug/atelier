"""WezTerm terminal adapter."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Mapping

from .base import TerminalAdapter


@dataclass(frozen=True)
class WezTermAdapter(TerminalAdapter):
    """Adapter for WezTerm panes."""

    pane_id: str
    name = "wezterm"

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> WezTermAdapter | None:
        pane_id = env.get("WEZTERM_PANE_ID") or env.get("WEZTERM_PANE")
        if not pane_id:
            return None
        return cls(pane_id=pane_id)

    def set_pane_title(self, title: str) -> bool:
        if not sys.stdout.isatty():
            return False
        safe = title.replace("\033", "").replace("\007", "").replace("\n", " ").replace("\r", " ")
        try:
            sys.stdout.write(f"\033]2;{safe}\007")
            sys.stdout.flush()
        except Exception:
            return False
        return True

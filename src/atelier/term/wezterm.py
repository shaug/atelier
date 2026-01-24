"""WezTerm terminal adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .. import exec as exec_util
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
        cmd = [
            "wezterm",
            "cli",
            "set-pane-title",
            "--pane-id",
            self.pane_id,
            title,
        ]
        result = exec_util.try_run_command(cmd)
        return bool(result and result.returncode == 0)

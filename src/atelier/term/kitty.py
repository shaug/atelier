"""Kitty terminal adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .. import exec as exec_util
from .base import TerminalAdapter


@dataclass(frozen=True)
class KittyAdapter(TerminalAdapter):
    """Adapter for Kitty panes via remote control."""

    window_id: str
    name = "kitty"

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> KittyAdapter | None:
        window_id = env.get("KITTY_WINDOW_ID")
        if not window_id:
            return None
        return cls(window_id=window_id)

    def set_pane_title(self, title: str) -> bool:
        cmd = [
            "kitty",
            "@",
            "set-window-title",
            "--match",
            f"id:{self.window_id}",
            title,
        ]
        result = exec_util.try_run_command(cmd)
        return bool(result and result.returncode == 0)

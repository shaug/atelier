"""Terminal integration helpers."""

from __future__ import annotations

import os
from typing import Mapping

from .base import (
    NoOpAdapter,
    TerminalAdapter,
    WorkspaceState,
    build_workspace_state,
    format_workspace_title,
    workspace_title,
)

__all__ = [
    "NoOpAdapter",
    "TerminalAdapter",
    "WorkspaceState",
    "apply_workspace_identity",
    "build_workspace_state",
    "format_workspace_title",
    "resolve_terminal_adapter",
    "workspace_title",
]


def resolve_terminal_adapter(
    env: Mapping[str, str] | None = None,
) -> TerminalAdapter:
    """Return the best adapter based on terminal environment variables."""
    from .kitty import KittyAdapter
    from .tmux import TmuxAdapter
    from .wezterm import WezTermAdapter

    env = env or os.environ

    wezterm_adapter = WezTermAdapter.from_env(env)
    if wezterm_adapter is not None:
        return wezterm_adapter

    kitty_adapter = KittyAdapter.from_env(env)
    if kitty_adapter is not None:
        return kitty_adapter

    if env.get("TMUX"):
        return TmuxAdapter()

    return NoOpAdapter()


def apply_workspace_identity(
    project_enlistment: str,
    workspace_branch: str,
    *,
    status: str | None = None,
    env: Mapping[str, str] | None = None,
) -> None:
    """Apply workspace identity to the current terminal when supported."""
    adapter = resolve_terminal_adapter(env)
    state = build_workspace_state(
        project_enlistment,
        workspace_branch,
        status=status,
    )
    try:
        adapter.set_workspace_state(state)
    except Exception:
        return

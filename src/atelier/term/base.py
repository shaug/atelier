"""Shared terminal integration types and helpers."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO


@dataclass(frozen=True)
class WorkspaceState:
    """Describe the workspace state used for terminal decoration."""

    project: str
    branch: str
    title: str
    status: str | None = None


def workspace_title(project_enlistment: str, workspace_branch: str) -> str:
    """Build a short workspace title for terminal chrome.

    Args:
        project_enlistment: Absolute path to the local enlistment.
        workspace_branch: Workspace branch name.

    Returns:
        Concise title string (``repo:branch`` when possible).
    """
    repo_name = Path(project_enlistment).name if project_enlistment else ""
    branch = (workspace_branch or "").lstrip("/")
    if repo_name and branch:
        return f"{repo_name}:{branch}"
    return repo_name or branch or "workspace"


def build_workspace_state(
    project_enlistment: str,
    workspace_branch: str,
    *,
    status: str | None = None,
) -> WorkspaceState:
    """Build a terminal-friendly workspace state description."""
    project_name = Path(project_enlistment).name if project_enlistment else ""
    title = workspace_title(project_enlistment, workspace_branch)
    return WorkspaceState(
        project=project_name or project_enlistment or workspace_branch,
        branch=workspace_branch,
        title=title,
        status=status,
    )


def format_workspace_title(state: WorkspaceState) -> str:
    """Return the pane title string for a workspace state."""
    if state.status:
        return f"{state.title} ({state.status})"
    return state.title


def emit_title_escape(title: str, *, stream: TextIO | None = None) -> bool:
    """Emit a terminal title escape sequence when possible."""
    stream = stream or sys.stdout
    if not getattr(stream, "isatty", lambda: False)():
        return False
    safe_title = title.replace("\033", "")
    try:
        stream.write(f"\033]0;{safe_title}\007")
        stream.flush()
    except Exception:
        return False
    return True


class TerminalAdapter:
    """Base terminal adapter with no-op defaults."""

    name = "base"

    def set_pane_title(self, title: str) -> bool:
        """Attempt to set the current pane title."""
        _ = title
        return False

    def set_workspace_state(self, state: WorkspaceState) -> bool:
        """Apply workspace state to terminal chrome."""
        return self.set_pane_title(format_workspace_title(state))

    def clear_pane_identity(self) -> bool:
        """Clear any terminal decoration for the current pane."""
        return self.set_pane_title("")


class NoOpAdapter(TerminalAdapter):
    """Terminal adapter that intentionally does nothing."""

    name = "noop"

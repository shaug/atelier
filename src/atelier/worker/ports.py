"""Typed callable ports used by worker services."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class ChangesetSelectionPorts:
    """Dependency ports used by changeset selection."""

    run_bd_json: Callable[..., list[dict[str, object]]]
    resolve_epic_id_for_changeset: Callable[..., str | None]
    next_changeset: Callable[..., dict[str, object] | None]

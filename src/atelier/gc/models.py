"""GC action model."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class GcAction:
    """A single garbage-collection action with description and apply callback."""

    description: str
    apply: Callable[[], None]
    details: tuple[str, ...] = ()

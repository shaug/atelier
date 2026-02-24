"""Functional helpers used by command and service orchestration modules."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterable
from typing import TypeVar

T = TypeVar("T")


def apply(fn: Callable[[T], object], values: Iterable[T]) -> None:
    """Apply a function to every value in an iterable.

    Args:
        fn: Callback invoked once per item in ``values``.
        values: Items to apply the callback to.

    Returns:
        ``None``. The callback side effects are evaluated eagerly.
    """
    deque(map(fn, values), maxlen=0)

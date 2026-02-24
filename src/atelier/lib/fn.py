"""Functional helpers used by command and service orchestration modules."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterable
from typing import TypeVar

T = TypeVar("T")


def apply(values: Iterable[T], fn: Callable[[T], object]) -> None:
    """Apply a function to every value in an iterable.

    Args:
        values: Items to apply the callback to.
        fn: Callback invoked once per item in ``values``.

    Returns:
        ``None``. The callback side effects are evaluated eagerly.
    """
    deque(map(fn, values), maxlen=0)

"""Atelier package metadata.

Exports the package version resolved from build metadata or installed
distribution information.

Example:
    >>> from atelier import __version__
    >>> isinstance(__version__, str)
    True
"""

from __future__ import annotations

__all__ = ["__version__"]

try:
    from ._version import __version__
except Exception:  # pragma: no cover - fallback for editable installs
    try:
        from importlib.metadata import PackageNotFoundError, version
    except Exception:  # pragma: no cover - import edge cases
        __version__ = "0.0.0"
    else:
        try:
            __version__ = version("atelier")
        except PackageNotFoundError:
            __version__ = "0.0.0"

"""Backward-compatible facade for worker command helper functions.

This module stays intentionally thin. Implementations live in specialized
runtime modules and are re-exported here for legacy imports.
"""

from __future__ import annotations

from .. import root_branch as root_branch_module
from . import work_finalization_runtime as _work_finalization_runtime
from . import work_runtime_common as _work_runtime_common
from . import work_startup_runtime as _work_startup_runtime
from .models import PublishSignalDiagnostics
from .review import ReviewFeedbackSelection
from .work_finalization_runtime import *  # noqa: F401,F403
from .work_runtime_common import *  # noqa: F401,F403
from .work_startup_runtime import *  # noqa: F401,F403

root_branch = root_branch_module

# Compatibility aliases for existing tests/callers.
_ReviewFeedbackSelection = ReviewFeedbackSelection
_PublishSignalDiagnostics = PublishSignalDiagnostics


def __getattr__(name: str) -> object:
    """Expose private helpers across split runtime modules for legacy imports."""
    for module in (
        _work_startup_runtime,
        _work_finalization_runtime,
        _work_runtime_common,
    ):
        if hasattr(module, name):
            return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

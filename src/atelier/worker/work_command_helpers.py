"""Backward-compatible facade for worker command helper functions.

This module stays intentionally thin. Implementations live in specialized
runtime modules and are re-exported here for legacy imports.
"""

from __future__ import annotations

from .. import root_branch as root_branch_module
from .models import PublishSignalDiagnostics
from .review import ReviewFeedbackSelection
from .work_finalization_runtime import *  # noqa: F401,F403
from .work_runtime_common import *  # noqa: F401,F403
from .work_startup_runtime import *  # noqa: F401,F403

root_branch = root_branch_module

# Compatibility aliases for existing tests/callers.
_ReviewFeedbackSelection = ReviewFeedbackSelection
_PublishSignalDiagnostics = PublishSignalDiagnostics

"""Publish-gate helpers for finalize pipeline."""

from __future__ import annotations

from .models import FinalizeResult


def review_pending_result() -> FinalizeResult:
    """Return the canonical review-pending finalize result."""
    return FinalizeResult(continue_running=True, reason="changeset_review_pending")

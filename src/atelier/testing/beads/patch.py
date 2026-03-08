"""Helpers for patching Atelier to use the in-memory Beads backend."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch

from atelier import exec as exec_util
from atelier.testing.beads.backend import InMemoryBeadsBackend, InMemoryBeadsCommandRunner


@contextmanager
def patch_in_memory_beads(backend: InMemoryBeadsBackend):
    """Route ``atelier.beads`` command execution to an in-memory backend.

    Args:
        backend: Seeded backend instance to install for the duration of the
            context manager.

    Yields:
        Installed command runner for optional test assertions.
    """

    runner = InMemoryBeadsCommandRunner(backend)
    with (
        patch.object(exec_util, "_DEFAULT_COMMAND_RUNNER", runner),
        patch("atelier.beads.bd_invocation.ensure_supported_bd_version", return_value=None),
        patch("atelier.beads.bd_invocation.detect_bd_version", return_value=(0, 56, 1)),
        patch("atelier.beads._resolve_dolt_commit_decision", return_value=None),
        patch("atelier.beads._attempt_startup_auto_migration", return_value=None),
        patch("atelier.beads._normalize_dolt_runtime_metadata_once", return_value=None),
        patch("atelier.beads._should_emit_startup_auto_migration_diagnostic", return_value=False),
        patch("atelier.beads._ensure_dolt_server_preflight", return_value=None),
    ):
        yield runner


__all__ = ["patch_in_memory_beads"]

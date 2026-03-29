from __future__ import annotations

from pathlib import Path
from typing import Literal

from atelier.lib.beads import BeadsCommandRequest, BeadsCommandResult, SubprocessBeadsClient
from atelier.store import build_atelier_store
from atelier.testing.beads import (
    InMemoryBeadsBackend,
    IssueFixtureBuilder,
    build_in_memory_beads_client,
)

BackendKind = Literal["in-memory", "subprocess"]

issue_builder = IssueFixtureBuilder()


class _InMemorySubprocessTransport:
    """Drive ``SubprocessBeadsClient`` from the in-memory backend."""

    def __init__(self, backend: InMemoryBeadsBackend) -> None:
        self._backend = backend

    async def execute(self, request: BeadsCommandRequest) -> BeadsCommandResult:
        completed = self._backend.run(request.argv, cwd=request.cwd, env=request.env)
        return BeadsCommandResult(
            argv=request.argv,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )


def make_store_for_backend(backend: BackendKind, *, issues: tuple[dict[str, object], ...]):
    """Build a real Atelier store over in-memory or subprocess-transport backends."""
    if backend == "in-memory":
        client, _backend = build_in_memory_beads_client(issues=issues)
        store = build_atelier_store(beads=client)
        return client, store
    if backend == "subprocess":
        in_memory_backend = InMemoryBeadsBackend(seeded_issues=issues)
        client = SubprocessBeadsClient(transport=_InMemorySubprocessTransport(in_memory_backend))
        store = build_atelier_store(beads=client)
        return client, store
    raise AssertionError(f"unsupported backend: {backend!r}")


def runtime_paths(tmp_path: Path) -> tuple[Path, Path]:
    """Return deterministic beads/repo placeholder paths for script context patches."""
    return tmp_path / ".beads", tmp_path / "repo"

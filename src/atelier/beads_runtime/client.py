"""Shared Beads runtime client protocol for extracted domain modules."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path
from subprocess import CompletedProcess
from tempfile import NamedTemporaryFile
from typing import Literal, NoReturn, Protocol, overload

FailureHandler = Callable[[str], NoReturn]


class RuntimeBeadsClient(Protocol):
    """Bound Beads command client consumed by domain runtime modules."""

    def issue_write_lock(self, issue_id: str) -> AbstractContextManager[None]:
        """Acquire an issue-scoped write lock context."""
        ...

    @overload
    def bd(
        self,
        args: list[str],
        *,
        json_mode: Literal[False] = False,
        allow_failure: bool = False,
    ) -> CompletedProcess[str]: ...

    @overload
    def bd(
        self,
        args: list[str],
        *,
        json_mode: Literal[True],
        allow_failure: bool = False,
    ) -> list[dict[str, object]]: ...

    def bd(
        self,
        args: list[str],
        *,
        json_mode: bool = False,
        allow_failure: bool = False,
    ) -> CompletedProcess[str] | list[dict[str, object]]:
        """Run a Beads command in raw or JSON mode."""
        ...


def run_json(client: RuntimeBeadsClient, args: list[str]) -> list[dict[str, object]]:
    """Run a Beads JSON command and return parsed issue payload rows."""
    payload = client.bd(args, json_mode=True)
    if isinstance(payload, list):
        return payload
    raise RuntimeError(f"expected JSON payload for `bd {' '.join(args)}`")


def run_command(
    client: RuntimeBeadsClient,
    args: list[str],
    *,
    allow_failure: bool = False,
) -> CompletedProcess[str]:
    """Run a raw Beads command and return the subprocess result."""
    result = client.bd(args, allow_failure=allow_failure)
    if isinstance(result, list):
        raise RuntimeError(f"expected command result for `bd {' '.join(args)}`")
    return result


def show_issue(client: RuntimeBeadsClient, issue_id: str) -> dict[str, object] | None:
    """Load one issue payload by id."""
    issues = run_json(client, ["show", issue_id])
    return issues[0] if issues else None


def issue_label(name: str) -> str:
    """Build a namespaced issue label."""
    cleaned = name.strip()
    if not cleaned:
        return cleaned
    if ":" in cleaned:
        return cleaned
    return f"at:{cleaned}"


def create_issue_with_body(
    client: RuntimeBeadsClient,
    args: list[str],
    description: str,
) -> str:
    """Create an issue using a body-file workflow and return the issue id."""
    temp_path = _write_temp_body_file(description)
    try:
        result = run_command(client, [*args, "--body-file", str(temp_path), "--silent"])
    finally:
        temp_path.unlink(missing_ok=True)
    issue_id = (result.stdout or "").strip()
    if not issue_id:
        raise RuntimeError("failed to create bead")
    return issue_id


def update_issue_description(
    client: RuntimeBeadsClient,
    issue_id: str,
    description: str,
) -> None:
    """Persist full issue description text via ``bd update --body-file``."""
    temp_path = _write_temp_body_file(description)
    try:
        run_command(client, ["update", issue_id, "--body-file", str(temp_path)])
    finally:
        temp_path.unlink(missing_ok=True)


def _write_temp_body_file(description: str) -> Path:
    with NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
        handle.write(description)
        return Path(handle.name)

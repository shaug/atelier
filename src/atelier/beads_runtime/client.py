"""Shared Beads runtime client protocol for extracted domain modules."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from subprocess import CompletedProcess
from typing import Literal, NoReturn, Protocol, overload

FailureHandler = Callable[[str], NoReturn]


class RuntimeBeadsClient(Protocol):
    """Bound Beads command client consumed by domain runtime modules."""

    def issue_write_lock(self, issue_id: str) -> AbstractContextManager[None]:
        """Acquire an issue-scoped write lock context."""
        ...

    @overload
    def run(
        self,
        args: list[str],
        *,
        json_mode: Literal[False] = False,
        allow_failure: bool = False,
    ) -> CompletedProcess[str]: ...

    @overload
    def run(
        self,
        args: list[str],
        *,
        json_mode: Literal[True],
        allow_failure: bool = False,
    ) -> list[dict[str, object]]: ...

    def run(
        self,
        args: list[str],
        *,
        json_mode: bool = False,
        allow_failure: bool = False,
    ) -> CompletedProcess[str] | list[dict[str, object]]:
        """Run a Beads command in raw or JSON mode."""
        ...

    def show_issue(self, issue_id: str) -> dict[str, object] | None:
        """Load one issue payload by id."""
        ...

    def issue_label(self, name: str) -> str:
        """Build a label using the configured issue prefix."""
        ...

    def create_issue_with_body(self, args: list[str], description: str) -> str:
        """Create an issue with description body and return its id."""
        ...

    def update_issue_description(self, issue_id: str, description: str) -> None:
        """Persist full issue description text for an issue."""
        ...

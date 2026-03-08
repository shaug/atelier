"""Command-harness adapters layered on the shared in-memory issue store."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from atelier import exec as exec_util

from .contract import InMemoryBeadsCommandRoute
from .core_issues import InMemoryCoreIssuesHandler
from .dispatcher import CommandEnvelope, CommandInvocation, InMemoryBeadsDispatcher
from .store import InMemoryIssueStore


def _strip_json_flag(tokens: Sequence[str]) -> list[str]:
    return [token for token in tokens if token != "--json"]


class InMemoryOwnershipSlotsHandler:
    """Handle Tier 1 slot routes against the shared in-memory issue store."""

    def __init__(self, store: InMemoryIssueStore) -> None:
        self._store = store

    def __call__(
        self,
        route: InMemoryBeadsCommandRoute,
        invocation: CommandInvocation,
    ) -> CommandEnvelope:
        tokens = _strip_json_flag(invocation.command_tokens[len(route.command) :])
        try:
            if route.command == ("slot", "show"):
                return self._show(tokens)
            if route.command == ("slot", "set"):
                return self._set(tokens)
            if route.command == ("slot", "clear"):
                return self._clear(tokens)
        except ValueError as exc:
            return CommandEnvelope.usage_error(str(exc))
        return CommandEnvelope.not_implemented(route)

    def _show(self, tokens: Sequence[str]) -> CommandEnvelope:
        if len(tokens) != 1:
            raise ValueError("slot show requires exactly one issue id")
        return CommandEnvelope.json_payload({"slots": self._store.show_slots(tokens[0])})

    def _set(self, tokens: Sequence[str]) -> CommandEnvelope:
        if len(tokens) != 3:
            raise ValueError("slot set requires issue id, slot, and value")
        issue_id, slot_name, slot_value = tokens
        self._store.set_slot(issue_id, slot_name, slot_value)
        return CommandEnvelope()

    def _clear(self, tokens: Sequence[str]) -> CommandEnvelope:
        if len(tokens) != 2:
            raise ValueError("slot clear requires issue id and slot")
        issue_id, slot_name = tokens
        self._store.clear_slot(issue_id, slot_name)
        return CommandEnvelope()


class InMemoryBeadsBackend(InMemoryBeadsDispatcher):
    """Command-style backend composed from the shared in-memory issue store."""

    def __init__(
        self,
        *,
        seeded_issues: Sequence[Mapping[str, object]] = (),
        slots: Mapping[str, Mapping[str, str]] | None = None,
        issue_store: InMemoryIssueStore | None = None,
        prefix: str = "at",
    ) -> None:
        if issue_store is None:
            issue_store = InMemoryIssueStore(issues=seeded_issues, prefix=prefix, slots=slots)
        else:
            for issue_id, slot_map in (slots or {}).items():
                for slot_name, slot_value in slot_map.items():
                    issue_store.set_slot(issue_id, slot_name, slot_value)
        self._issue_store = issue_store
        super().__init__(
            family_handlers={
                "core-issues": InMemoryCoreIssuesHandler(issue_store),
                "ownership-slots": InMemoryOwnershipSlotsHandler(issue_store),
            }
        )

    @property
    def state(self) -> InMemoryIssueStore:
        """Return the shared mutable store for assertions in tests."""

        return self._issue_store


@dataclass(frozen=True)
class InMemoryBeadsCommandRunner:
    """Command-runner adapter for routing ``bd`` requests to the backend."""

    backend: InMemoryBeadsBackend

    def run(self, request: exec_util.CommandRequest) -> exec_util.CommandResult | None:
        if not request.argv or Path(request.argv[0]).name != "bd":
            return None
        result = self.backend.run(request.argv, cwd=request.cwd, env=request.env)
        return exec_util.CommandResult(
            argv=tuple(str(token) for token in result.args),
            returncode=result.returncode,
            stdout=result.stdout or "",
            stderr=result.stderr or "",
        )


__all__ = [
    "InMemoryBeadsBackend",
    "InMemoryBeadsCommandRunner",
    "InMemoryOwnershipSlotsHandler",
]

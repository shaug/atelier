"""In-memory command dispatcher harness for deterministic Beads tests."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol, Sequence, runtime_checkable

from .contract import (
    DEFAULT_UNIMPLEMENTED_RETURN_CODE,
    DOCUMENTED_COMMAND_ROUTES,
    IN_MEMORY_BEADS_VERSION,
    SUPPORTED_GLOBAL_FLAGS,
    InMemoryBeadsCommandRoute,
    documented_route_index,
)

_VALUE_GLOBAL_FLAGS = ("--actor", "--db", "--dolt-auto-commit")
_BOOLEAN_GLOBAL_FLAGS = tuple(
    flag for flag in SUPPORTED_GLOBAL_FLAGS if flag not in _VALUE_GLOBAL_FLAGS
)
_ROUTE_INDEX = documented_route_index()
_SORTED_ROUTES = tuple(
    sorted(DOCUMENTED_COMMAND_ROUTES, key=lambda route: len(route.command), reverse=True)
)


@dataclass(frozen=True)
class CommandInvocation:
    """Normalized command invocation for in-memory dispatch.

    Args:
        argv: Original command argv.
        command_tokens: Tokens remaining after stripping the optional ``bd``
            executable and supported leading global flags.
        global_tokens: Supported leading global flags preserved for assertions.
        cwd: Optional working directory supplied by the caller.
        env: Optional environment supplied by the caller.
    """

    argv: tuple[str, ...]
    command_tokens: tuple[str, ...]
    global_tokens: tuple[str, ...] = ()
    cwd: Path | None = None
    env: Mapping[str, str] | None = None

    @property
    def requests_help(self) -> bool:
        """Return whether the invocation asked for help output."""

        return "--help" in self.command_tokens or "-h" in self.command_tokens

    @property
    def requests_json(self) -> bool:
        """Return whether the invocation asked for JSON output."""

        return "--json" in self.command_tokens


@dataclass(frozen=True)
class CommandEnvelope:
    """CompletedProcess-like result payload before argv binding."""

    returncode: int = 0
    stdout: str = ""
    stderr: str = ""

    @classmethod
    def json_payload(
        cls,
        payload: object,
        *,
        returncode: int = 0,
        stderr: str = "",
    ) -> "CommandEnvelope":
        """Return an envelope with deterministic JSON stdout."""

        return cls(returncode=returncode, stdout=json.dumps(payload, sort_keys=True), stderr=stderr)

    @classmethod
    def usage_error(cls, message: str) -> "CommandEnvelope":
        """Return the canonical CLI usage error envelope."""

        return cls(returncode=2, stderr=message)

    @classmethod
    def not_implemented(cls, route: InMemoryBeadsCommandRoute) -> "CommandEnvelope":
        """Return the canonical explicit-unimplemented marker."""

        return cls(
            returncode=DEFAULT_UNIMPLEMENTED_RETURN_CODE,
            stderr=(
                "in-memory Beads semantics not implemented yet for "
                f"{route.family_id}: {route.command_label}"
            ),
        )

    def bind(self, argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        """Return a ``CompletedProcess`` bound to one argv value."""

        return subprocess.CompletedProcess(tuple(argv), self.returncode, self.stdout, self.stderr)


@runtime_checkable
class InMemoryBeadsCommandBackend(Protocol):
    """Test-only command-style execution interface for the in-memory backend."""

    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]: ...


class CommandFamilyHandler(Protocol):
    """Handler contract for one documented command family."""

    def __call__(
        self,
        route: InMemoryBeadsCommandRoute,
        invocation: CommandInvocation,
    ) -> CommandEnvelope: ...


def normalize_invocation(
    argv: Sequence[str],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> CommandInvocation:
    """Normalize argv for in-memory Beads dispatch."""

    tokens = tuple(str(token) for token in argv)
    if tokens and Path(tokens[0]).name == "bd":
        tokens = tokens[1:]
    global_tokens, command_tokens = _consume_leading_global_tokens(tokens)
    return CommandInvocation(
        argv=tuple(str(token) for token in argv),
        command_tokens=command_tokens,
        global_tokens=global_tokens,
        cwd=cwd,
        env=env,
    )


class InMemoryBeadsDispatcher(InMemoryBeadsCommandBackend):
    """Route normalized argv into family handlers with CLI-like envelopes."""

    def __init__(
        self,
        *,
        family_handlers: Mapping[str, CommandFamilyHandler] | None = None,
        version: str = IN_MEMORY_BEADS_VERSION,
    ) -> None:
        self._family_handlers = dict(family_handlers or {})
        self._version = version

    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        invocation = normalize_invocation(argv, cwd=cwd, env=env)
        envelope = self._dispatch(invocation)
        return envelope.bind(invocation.argv)

    def _dispatch(self, invocation: CommandInvocation) -> CommandEnvelope:
        if not invocation.command_tokens:
            return self._render_root_help()
        if invocation.command_tokens == ("--version",):
            return CommandEnvelope(stdout=f"bd version {self._version} (in-memory)\n")
        route = _match_route(invocation.command_tokens)
        if route is None:
            first = invocation.command_tokens[0]
            return CommandEnvelope.usage_error(f'unknown command "{first}"')
        if invocation.requests_help:
            return self._render_route_help(route)
        handler = self._family_handlers.get(route.family_id)
        if handler is None:
            return CommandEnvelope.not_implemented(route)
        return handler(route, invocation)

    def _render_root_help(self) -> CommandEnvelope:
        lines = [
            "In-memory Beads dispatcher",
            "",
            "Usage:",
            "  bd <command> [arguments] [flags]",
            "",
            "Documented commands:",
        ]
        seen: set[tuple[str, ...]] = set()
        for route in DOCUMENTED_COMMAND_ROUTES:
            if route.command in seen:
                continue
            seen.add(route.command)
            lines.append(f"  {route.command_label:<18} {route.summary}")
        return CommandEnvelope(stdout="\n".join(lines) + "\n")

    def _render_route_help(self, route: InMemoryBeadsCommandRoute) -> CommandEnvelope:
        lines = [
            route.summary,
            "",
            "Usage:",
            f"  bd {route.command_label} [flags]",
            "",
            "Flags:",
            "  -h, --help   help for command",
        ]
        if route.supports_json_output:
            lines.append("      --json   Output in JSON format")
        return CommandEnvelope(stdout="\n".join(lines) + "\n")


def _consume_leading_global_tokens(
    tokens: tuple[str, ...],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    consumed: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token in _BOOLEAN_GLOBAL_FLAGS:
            consumed.append(token)
            index += 1
            continue
        if token in _VALUE_GLOBAL_FLAGS:
            consumed.append(token)
            if index + 1 < len(tokens):
                consumed.append(tokens[index + 1])
                index += 2
            else:
                index += 1
            continue
        matched_flag = next(
            (flag for flag in _VALUE_GLOBAL_FLAGS if token.startswith(f"{flag}=")),
            None,
        )
        if matched_flag is not None:
            consumed.append(token)
            index += 1
            continue
        break
    return tuple(consumed), tokens[index:]


def _match_route(command_tokens: tuple[str, ...]) -> InMemoryBeadsCommandRoute | None:
    sanitized = tuple(token for token in command_tokens if token not in {"--help", "-h"})
    for route in _SORTED_ROUTES:
        if sanitized[: len(route.command)] == route.command:
            return _ROUTE_INDEX[route.command]
    return None


__all__ = [
    "CommandEnvelope",
    "CommandFamilyHandler",
    "CommandInvocation",
    "InMemoryBeadsCommandBackend",
    "InMemoryBeadsDispatcher",
    "normalize_invocation",
]

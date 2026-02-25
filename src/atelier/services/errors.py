"""Service failure contracts.

Services return typed outcomes on success and raise ServiceFailure on expected
domain/policy/runtime failures. Programmer bugs raise normal exceptions.
"""

from __future__ import annotations

from typing import Literal

ServiceFailureCode = Literal[
    "validation_failed",
    "dependency_missing",
    "policy_blocked",
    "external_command_failed",
    "io_failed",
    "unexpected_state",
]


class ServiceFailure(Exception):
    """Expected service failure: validation, policy, or runtime error.

    Raised by services instead of returning a failure value. Use ``raise
    ServiceFailure(...) from exc`` to chain a causing exception; it is
    available as ``__cause__``. Callers catch ServiceFailure and handle per
    their interface (CLI dies, web returns 4xx/5xx, native app shows dialog).
    """

    def __init__(
        self,
        code: ServiceFailureCode,
        message: str,
        *,
        recovery_hint: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.recovery_hint = recovery_hint


class ValidationFailedError(ServiceFailure):
    """Validation failed (invalid input, constraint violation)."""

    def __init__(self, message: str, *, recovery_hint: str | None = None) -> None:
        super().__init__("validation_failed", message, recovery_hint=recovery_hint)


class DependencyMissingError(ServiceFailure):
    """Required dependency is missing or unavailable."""

    def __init__(self, message: str, *, recovery_hint: str | None = None) -> None:
        super().__init__("dependency_missing", message, recovery_hint=recovery_hint)


class PolicyBlockedError(ServiceFailure):
    """Policy gate blocked the operation."""

    def __init__(self, message: str, *, recovery_hint: str | None = None) -> None:
        super().__init__("policy_blocked", message, recovery_hint=recovery_hint)


class ExternalCommandFailedError(ServiceFailure):
    """External command (git, gh, etc.) failed."""

    def __init__(self, message: str, *, recovery_hint: str | None = None) -> None:
        super().__init__("external_command_failed", message, recovery_hint=recovery_hint)


class IoFailedError(ServiceFailure):
    """I/O operation failed (read, write, config)."""

    def __init__(self, message: str, *, recovery_hint: str | None = None) -> None:
        super().__init__("io_failed", message, recovery_hint=recovery_hint)


class UnexpectedStateError(ServiceFailure):
    """Unexpected or inconsistent state."""

    def __init__(self, message: str, *, recovery_hint: str | None = None) -> None:
        super().__init__("unexpected_state", message, recovery_hint=recovery_hint)

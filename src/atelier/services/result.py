"""Common service result contracts for orchestration entrypoints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Literal, TypeVar

ServiceFailureCode = Literal[
    "validation_failed",
    "dependency_missing",
    "policy_blocked",
    "external_command_failed",
    "io_failed",
    "unexpected_state",
]

T = TypeVar("T")


@dataclass(frozen=True)
class ServiceSuccess(Generic[T]):
    """Container for successful service outcomes.

    Args:
        outcome: Typed outcome payload returned by a service.
    """

    outcome: T


@dataclass(frozen=True)
class ServiceFailure:
    """Deterministic failure result for expected service errors.

    Args:
        code: Stable failure code for callers and tests.
        message: Human-readable failure summary.
        recovery_hint: Optional actionable hint for recovery.
    """

    code: ServiceFailureCode
    message: str
    recovery_hint: str | None = None


ServiceResult = ServiceSuccess[T] | ServiceFailure


def service_success(outcome: T) -> ServiceSuccess[T]:
    """Create a successful service result.

    Args:
        outcome: Typed outcome payload to return.

    Returns:
        ``ServiceSuccess`` wrapping ``outcome``.
    """

    return ServiceSuccess(outcome=outcome)


def service_failure(
    *,
    code: ServiceFailureCode,
    message: str,
    recovery_hint: str | None = None,
) -> ServiceFailure:
    """Create a deterministic service failure result.

    Args:
        code: Stable failure code.
        message: Human-readable failure summary.
        recovery_hint: Optional actionable hint for callers.

    Returns:
        ``ServiceFailure`` describing the expected failure.
    """

    return ServiceFailure(code=code, message=message, recovery_hint=recovery_hint)

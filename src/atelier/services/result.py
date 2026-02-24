from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Literal, TypeGuard, TypeVar

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
    outcome: T
    success: Literal[True] = True


@dataclass(frozen=True)
class ServiceFailure:
    code: ServiceFailureCode
    message: str
    recovery_hint: str | None = None
    success: Literal[False] = False


ServiceResult = ServiceSuccess[T] | ServiceFailure


def is_service_failure(result: ServiceResult[T]) -> TypeGuard[ServiceFailure]:
    """Return whether a service result represents a failure payload.

    Args:
        result: Service result union to inspect.

    Returns:
        ``True`` when ``result`` is a ``ServiceFailure`` instance.
    """
    return result.success is False


def is_service_success(result: ServiceResult[T]) -> TypeGuard[ServiceSuccess[T]]:
    """Return whether a service result represents a success payload.

    Args:
        result: Service result union to inspect.

    Returns:
        ``True`` when ``result`` is a ``ServiceSuccess`` instance.
    """
    return result.success is True
